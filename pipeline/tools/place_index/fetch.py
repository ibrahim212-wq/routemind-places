"""Fetch every source into a data directory — streamed and cut to Egypt, never a global dump.

    python -m tools.place_index.fetch --data <dir> [--only overture,geofabrik,hot,wikidata,geonames,fsq]

  overture   the latest Overture release on S3 (anonymous): places + divisions, only the parquet
             row groups whose bbox statistics touch Egypt (≈ 40 MB read of ≈ 11 GB)
  geofabrik  africa/egypt-latest.osm.pbf (≈ 200 MB) — OSM with every tag (the refresh pipeline)
  hot        HOT's Egypt export on S3 (GeoParquet, a tag subset) — the desk / fallback OSM
  wikidata   items located in Egypt with an Arabic or English label and their sitelink count
  geonames   EG.zip → EG.txt (villages and hamlets with Arabic alternate names)
  fsq        Foursquare OS Places, Egypt box, through the Places Portal's Iceberg catalog when
             FSQ_PORTAL_TOKEN is set, else its Hugging Face copy when HF_TOKEN is set (free accounts;
             docs/place-search-2026-10.md §9)
  learning   the places users added + the anonymous search → pick aggregates (two public RPCs;
             SUPABASE_URL + SUPABASE_ANON_KEY)

A source that fails is reported and skipped; build.py builds from whatever arrived.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

X0, X1, Y0, Y1 = 24.6, 37.0, 21.6, 31.8  # Egypt's box (records.EG_BBOX)
UA = "RouteMind-place-index/1.0 (https://github.com/ibrahim212-wq; routemind place index build)"


def log(*a):
    print("[fetch]", *a, flush=True)


def _s3(region: str):
    # the AWS SDK inside pyarrow ≥ 21 validates response checksums by default and rejects some
    # multipart-uploaded objects («Response checksums mismatch», HOT's buildings layer, 2026-10-16) —
    # validate only where the object requires it (the reads stay TLS-protected)
    os.environ.setdefault("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required")
    import pyarrow.fs as fs
    kw = {"anonymous": True, "region": region}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        kw["proxy_options"] = proxy
    ca = os.environ.get("AWS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca and os.path.exists(ca):
        kw["tls_ca_file_path"] = ca
    return fs.S3FileSystem(**kw)


def overture_latest(s3) -> str:
    import pyarrow.fs as fs
    infos = s3.get_file_info(fs.FileSelector("overturemaps-us-west-2/release/"))
    rels = sorted(i.path.rsplit("/", 1)[-1] for i in infos if i.type == fs.FileType.Directory)
    return rels[-1]


def _retry(what: str, fn, tries: int = 5):
    """S3 and HTTP reads over a long run meet transient resets (2026-10-16: NETWORK_CONNECTION on
    one Overture file failed the whole refresh). Retry with backoff; the last error propagates."""
    wait = 5
    for k in range(tries):
        try:
            return fn()
        except OSError as e:  # pyarrow's S3 errors and urllib's are OSErrors
            if k == tries - 1:
                raise
            pause = wait
            if getattr(e, "code", None) == 429:  # rate-limited (Wikidata's query service): wait as asked
                try:
                    pause = max(wait, int(e.headers.get("Retry-After", "60")))
                except (TypeError, ValueError, AttributeError):
                    pause = max(wait, 60)
            log(what, f"retry {k + 1}/{tries - 1} in {pause}s after", f"{type(e).__name__}: {str(e)[:160]}")
            time.sleep(pause)
            wait *= 2


def _extract(s3, release: str, theme: str, typ: str, out: str) -> int:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    base = f"overturemaps-us-west-2/release/{release}/theme={theme}/type={typ}/"
    tables = []

    def read_one(path):
        f = pq.ParquetFile(path, filesystem=s3)
        md = f.metadata
        cols = [md.schema.column(k).path for k in range(md.num_columns)]
        ix, iy, ixx, iyy = (cols.index(c) for c in ("bbox.xmin", "bbox.ymin", "bbox.xmax", "bbox.ymax"))
        groups = []
        for r in range(md.num_row_groups):
            rg = md.row_group(r)
            if (rg.column(ixx).statistics.max >= X0 and rg.column(ix).statistics.min <= X1 and
                    rg.column(iyy).statistics.max >= Y0 and rg.column(iy).statistics.min <= Y1):
                groups.append(r)
        if not groups:
            return None
        t = f.read_row_groups(groups)
        b = t.column("bbox")
        m = pc.and_(pc.and_(pc.greater_equal(pc.struct_field(b, "xmax"), X0), pc.less_equal(pc.struct_field(b, "xmin"), X1)),
                    pc.and_(pc.greater_equal(pc.struct_field(b, "ymax"), Y0), pc.less_equal(pc.struct_field(b, "ymin"), Y1)))
        return t.filter(m)

    for info in _retry(f"list {theme}/{typ}", lambda: s3.get_file_info(fs.FileSelector(base))):
        if not info.path.endswith(".parquet"):
            continue
        t = _retry(info.path.rsplit("/", 1)[-1], lambda p=info.path: read_one(p))
        if t is not None:
            tables.append(t)
    if not tables:
        raise RuntimeError(f"no {theme}/{typ} rows in the Egypt box")
    T = pa.concat_tables(tables, promote_options="default")
    pq.write_table(T, out, compression="zstd")
    return T.num_rows


def fetch_overture(data: str) -> dict:
    s3 = _s3("us-west-2")
    rel = os.environ.get("OVERTURE_RELEASE") or overture_latest(s3)
    d = os.path.join(data, "overture")
    os.makedirs(d, exist_ok=True)
    n = {"release": rel}
    n["places"] = _extract(s3, rel, "places", "place", os.path.join(d, "places_eg_bbox.parquet"))
    n["division"] = _extract(s3, rel, "divisions", "division", os.path.join(d, "division_eg.parquet"))
    n["division_area"] = _extract(s3, rel, "divisions", "division_area", os.path.join(d, "division_area_eg.parquet"))
    return n


HOT_LAYERS = ("points_of_interest", "health_facilities", "education_facilities", "financial_services",
              "cultural_places", "populated_places", "airports", "railways", "sea_ports", "buildings")


def fetch_hot(data: str) -> dict:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    s3 = _s3("us-east-1")
    d = os.path.join(data, "osm_hot")
    os.makedirs(d, exist_ok=True)
    n = {}
    for layer in HOT_LAYERS:
        def copy(layer=layer):
            with s3.open_input_file(f"production-raw-data-api/ISO3/EGY/_layers/osm/{layer}.parquet") as src, \
                    open(os.path.join(d, layer + ".parquet"), "wb") as dst:
                dst.write(src.read())
        _retry(layer, copy)
        n[layer] = pq.ParquetFile(os.path.join(d, layer + ".parquet")).metadata.num_rows
    cols = ["id", "name", "name_en", "name_ar", "highway", "adm1_name", "adm2_name", "adm3_name", "geom"]

    def roads():
        f = pq.ParquetFile("production-raw-data-api/ISO3/EGY/_layers/osm/roads.parquet", filesystem=s3)
        parts = []
        for i in range(f.metadata.num_row_groups):
            t = f.read_row_group(i, columns=cols)
            parts.append(t.filter(pc.or_(pc.or_(pc.is_valid(t["name"]), pc.is_valid(t["name_ar"])), pc.is_valid(t["name_en"]))))
        return pa.concat_tables(parts)
    T = _retry("roads", roads)
    pq.write_table(T, os.path.join(d, "roads_named.parquet"), compression="zstd")
    n["roads_named"] = T.num_rows
    return n


def _download(url: str, path: str, timeout: int = 600) -> int:
    def once():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
            total = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        return total
    return _retry(url.rsplit("/", 1)[-1], once)


def fetch_geofabrik(data: str) -> dict:
    path = os.path.join(data, "egypt-latest.osm.pbf")
    n = _download("https://download.geofabrik.de/africa/egypt-latest.osm.pbf", path)
    return {"bytes": n}


def fetch_geonames(data: str) -> dict:
    tmp = os.path.join(data, "EG.zip")
    _download("https://download.geonames.org/export/dump/EG.zip", tmp)
    with zipfile.ZipFile(tmp) as z:
        with z.open("EG.txt") as src, open(os.path.join(data, "EG.txt"), "wb") as dst:
            dst.write(src.read())
    os.remove(tmp)
    with open(os.path.join(data, "EG.txt"), encoding="utf-8") as f:
        return {"rows": sum(1 for _ in f)}


# Wikidata classes → display category (the item's P31 / P279* chain is matched in SPARQL by VALUES)
WD_CLASSES = {
    "Q16917": "hospital", "Q3918": "university", "Q11303": "mall", "Q33506": "museum",
    "Q839954": "historic_site", "Q570116": "attraction", "Q1248784": "airport", "Q55488": "train_station",
    "Q928830": "metro_station", "Q483110": "stadium", "Q32815": "mosque", "Q16970": "church",
    "Q44613": "monastery", "Q174782": "square", "Q12280": "bridge", "Q22698": "park", "Q40080": "beach",
    "Q27686": "hotel", "Q44539": "historic_site", "Q12518": "tower",
    "Q4989906": "monument", "Q1060829": "theater", "Q24354": "theater", "Q41176": "building",
    "Q515": "city", "Q3957": "town", "Q532": "village", "Q123705": "neighbourhood",
}


def fetch_wikidata(data: str) -> dict:
    # one query per class: the single query over every class (P31/P279* × 28 classes) times out at the
    # endpoint's 60 s limit (HTTP 504, 2026-10-16); each class alone answers in seconds. The bindings
    # are the same rows, so the merge below is unchanged.
    # A class whose subclass tree is too wide for the endpoint (Q41176 "building": HTTP 500 after 60 s,
    # every time) falls back to its direct instances; a class that still fails is skipped and reported
    # — never the whole source.
    bindings, skipped = [], []

    def ask(q: str, path: str) -> list:
        query = f"""
SELECT ?item ?cls ?lat ?lng ?ar ?en ?sl ?pop WHERE {{
  ?item wdt:P17 wd:Q79; wdt:P625 ?coord; wikibase:sitelinks ?sl .
  ?item {path} ?cls . VALUES ?cls {{ wd:{q} }}
  BIND(geof:latitude(?coord) AS ?lat) BIND(geof:longitude(?coord) AS ?lng)
  OPTIONAL {{ ?item rdfs:label ?ar FILTER(LANG(?ar) = "ar") }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P1082 ?pop }}
}}"""
        url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)

        def once():
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                # strict=False: a label with a raw control character (2026-10-31: char 38,889,396) is not a failed fetch
                return json.load(r, strict=False)
        return _retry(f"wikidata {q} {path}", once, tries=2)["results"]["bindings"]

    for q in WD_CLASSES:
        try:
            bindings += ask(q, "wdt:P31/wdt:P279*")
        except OSError:
            try:
                bindings += ask(q, "wdt:P31")
                log("wikidata", q, "subclass tree too wide — direct instances only")
            except OSError as e:
                skipped.append(q)
                log("wikidata", q, "skipped:", str(e)[:120])
        time.sleep(1)  # the endpoint's etiquette: one query at a time, a pause between
    rows: dict[str, dict] = {}
    for b in bindings:
        if "lat" not in b or "lng" not in b:  # a coordinate on another globe / a malformed point
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        cls = b["cls"]["value"].rsplit("/", 1)[-1]
        row = rows.setdefault(qid, {"qid": qid, "lat": float(b["lat"]["value"]), "lng": float(b["lng"]["value"]),
                                    "ar": b.get("ar", {}).get("value"), "en": b.get("en", {}).get("value"),
                                    "sitelinks": int(b["sl"]["value"]), "cat": WD_CLASSES.get(cls),
                                    "population": int(float(b["pop"]["value"])) if "pop" in b else 0})
        # the most specific class wins: a mosque that is also a building stays a mosque
        if row["cat"] in ("building", None):
            row["cat"] = WD_CLASSES.get(cls)
    out = [r for r in rows.values() if r["ar"] or r["en"]]
    with open(os.path.join(data, "wikidata.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    if not out:
        raise RuntimeError(f"no Wikidata item answered (skipped classes: {skipped})")
    return {"items": len(out), **({"skipped_classes": skipped} if skipped else {})}


FSQ_CATALOG = "https://catalog.h3-hub.foursquare.com/iceberg"
FSQ_HF_REPO = "foursquare/fsq-os-places"
FSQ_COLS = ("fsq_place_id", "name", "latitude", "longitude", "address", "tel", "website", "facebook_id",
            "date_refreshed", "date_closed", "fsq_category_labels", "country")


def fetch_fsq(data: str) -> dict:
    """Foursquare OS Places, Egypt: the Places Portal's Iceberg catalog when FSQ_PORTAL_TOKEN is set, else
    the same open release on Hugging Face (`foursquare/fsq-os-places`, a gated dataset that admits any free
    account at once) when HF_TOKEN is set. Overture carries only the ~7k Egyptian Foursquare rows it could
    conflate; the open release itself is the long tail of cafés, restaurants and shops."""
    token = os.environ.get("FSQ_PORTAL_TOKEN")
    if not token:
        if os.environ.get("HF_TOKEN"):
            return fetch_fsq_hf(data, os.environ["HF_TOKEN"])
        return {"skipped": "neither FSQ_PORTAL_TOKEN nor HF_TOKEN is set"}
    from pyiceberg.catalog.rest import RestCatalog
    from pyiceberg.expressions import And, GreaterThanOrEqual, LessThanOrEqual
    cat = RestCatalog("fsq", uri=FSQ_CATALOG, warehouse="places", token=token)
    tbl = cat.load_table("datasets.places_os")
    flt = And(And(GreaterThanOrEqual("latitude", Y0), LessThanOrEqual("latitude", Y1)),
              And(GreaterThanOrEqual("longitude", X0), LessThanOrEqual("longitude", X1)))
    cols = ("fsq_place_id", "name", "latitude", "longitude", "address", "tel", "website", "facebook_id",
            "date_refreshed", "date_closed", "fsq_category_labels", "country")
    t = tbl.scan(row_filter=flt, selected_fields=cols).to_arrow()
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t = t.filter(pc.equal(t["country"], "EG"))
    pq.write_table(t, os.path.join(data, "fsq.parquet"), compression="zstd")
    return {"rows": t.num_rows}


def fetch_fsq_hf(data: str, token: str) -> dict:
    """The newest `release/dt=…/places/parquet/*.parquet` of the Hugging Face copy, read by range requests:
    only the row groups whose latitude / longitude statistics touch Egypt's box (all of them when a file
    carries no statistics), then only the Egyptian rows."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{FSQ_HF_REPO}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        files = [s["rfilename"] for s in json.load(r).get("siblings", [])]
    rels = sorted({f.split("/")[1] for f in files if f.startswith("release/dt=") and "/places/parquet/" in f})
    if not rels:
        raise RuntimeError("no places release in the Hugging Face listing")
    rel = os.environ.get("FSQ_RELEASE") or rels[-1]
    parts = sorted(f for f in files if f.startswith(f"release/{rel}/places/parquet/") and f.endswith(".parquet"))
    fs = HfFileSystem(token=token)
    tables, scanned, read = [], 0, 0
    for part in parts:
        def one(p=part):
            with fs.open(f"datasets/{FSQ_HF_REPO}/{p}", "rb", block_size=8 << 20) as fh:
                pf = pq.ParquetFile(fh)
                md = pf.metadata
                names = [md.schema.column(k).name for k in range(md.num_columns)]
                cols = [c for c in FSQ_COLS if c in names]
                ilat, ilng = names.index("latitude"), names.index("longitude")
                groups = []
                for g in range(md.num_row_groups):
                    a, b = md.row_group(g).column(ilat).statistics, md.row_group(g).column(ilng).statistics
                    if a is None or b is None or not a.has_min_max or not b.has_min_max or (
                            a.max >= Y0 and a.min <= Y1 and b.max >= X0 and b.min <= X1):
                        groups.append(g)
                if not groups:
                    return None, md.num_row_groups, 0
                t = pf.read_row_groups(groups, columns=cols)
                m = pc.and_(pc.and_(pc.greater_equal(t["latitude"], Y0), pc.less_equal(t["latitude"], Y1)),
                            pc.and_(pc.greater_equal(t["longitude"], X0), pc.less_equal(t["longitude"], X1)))
                t = t.filter(m)
                if "country" in t.column_names:
                    t = t.filter(pc.equal(t["country"], "EG"))
                return t, md.num_row_groups, len(groups)
        t, n, k = _retry(part.rsplit("/", 1)[-1], one)
        scanned += n
        read += k
        if t is not None and t.num_rows:
            tables.append(t)
    if not tables:
        raise RuntimeError(f"no Egyptian rows in {rel}")
    T = pa.concat_tables(tables, promote_options="default")
    pq.write_table(T, os.path.join(data, "fsq.parquet"), compression="zstd")
    return {"rows": T.num_rows, "release": rel, "files": len(parts), "row_groups": scanned, "row_groups_read": read,
            "via": "huggingface"}


def fetch_learning(data: str) -> dict:
    """What users taught the index (docs/search-learning-migration.sql): the places they added that the
    export rule accepted, and the anonymous search → pick aggregates. Two public RPCs read with the app's
    own anon key (SUPABASE_URL / SUPABASE_ANON_KEY — the same values every phone carries)."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return {"skipped": "SUPABASE_URL / SUPABASE_ANON_KEY not set"}
    out = {}
    for rpc, fn, body in (("ugc_places_export", "ugc_places.json", {}),
                          ("search_selections_export", "selections.json", {"min_n": 3})):
        req = urllib.request.Request(url.rstrip("/") + "/rest/v1/rpc/" + rpc, data=json.dumps(body).encode(),
                                     headers={"apikey": key, "Authorization": "Bearer " + key,
                                              "Content-Type": "application/json", "User-Agent": UA}, method="POST")
        rows = _retry(rpc, lambda r=req: json.load(urllib.request.urlopen(r, timeout=120)))
        with open(os.path.join(data, fn), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        out[rpc] = len(rows)
    return out


FETCHERS = {"overture": fetch_overture, "geofabrik": fetch_geofabrik, "hot": fetch_hot,
            "wikidata": fetch_wikidata, "geonames": fetch_geonames, "fsq": fetch_fsq, "learning": fetch_learning}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--only", default="overture,geofabrik,wikidata,geonames,fsq,learning")
    a = ap.parse_args(argv)
    os.makedirs(a.data, exist_ok=True)
    rpath = os.path.join(a.data, "fetch_report.json")
    report = {}
    if os.path.exists(rpath):  # a re-run of one source keeps what the others reported
        with open(rpath) as f:
            report = json.load(f)
    for name in a.only.split(","):
        t = time.time()
        try:
            report[name] = FETCHERS[name](a.data)
            report[name]["seconds"] = round(time.time() - t)
            log(name, json.dumps(report[name]))
        except Exception as e:  # a missing source is a smaller index, never a failed refresh
            report[name] = {"error": f"{type(e).__name__}: {e}"}
            log(name, "FAILED", report[name]["error"])
    with open(rpath, "w") as f:
        json.dump(report, f, indent=1)
    if "overture" in report and "error" in report["overture"]:
        sys.exit("overture is required")  # without it there is no index worth publishing


if __name__ == "__main__":
    main()
