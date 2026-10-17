"""Build the place index: sources → records → merge → streets → enrich → tiles.

    python -m tools.place_index.build --data <dir> --out <dir> [--sources osm,overture,div,fsq,wd,gn]
                                      [--osm hot|pbf] [--version 2026-10-15]

`--data` holds what fetch.py wrote (overture/, osm_hot/ or egypt-latest.osm.pbf, fsq.parquet,
wikidata.json, EG.txt). A source whose file is missing is skipped with a line in the report, so the
same command builds the desk index (Overture + the HOT OSM export) and the refresh pipeline's
(Overture + Geofabrik + Foursquare + Wikidata + GeoNames). `--sources` builds a single-source index
for the benchmark («how good is OSM alone»).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import Counter

from . import enrich as E
from . import media as MD
from . import merge as M
from . import records as R
from . import sources as S
from . import streets as ST
from . import taxonomy as T
from . import tiles as TL

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))
LEXICON = os.path.join(APP, "assets", "search", "egypt_lexicon.json")


def log(*a):
    print("[place_index]", *a, flush=True)


def egypt_inside(division_area_parquet: str):
    import pyarrow.parquet as pq
    import shapely
    from shapely import prepared
    rows = pq.read_table(division_area_parquet, columns=["subtype", "country", "class", "geometry"]).to_pylist()
    geoms = [shapely.from_wkb(a["geometry"]) for a in rows
             if a["subtype"] == "country" and a["country"] == "EG" and a["class"] == "land"]
    eg = prepared.prep(shapely.union_all(geoms).buffer(0.01))

    def inside(lat, lng):
        if not (R.EG_BBOX[1] <= lat <= R.EG_BBOX[3] and R.EG_BBOX[0] <= lng <= R.EG_BBOX[2]):
            return False
        return eg.contains(shapely.Point(lng, lat))
    return inside


def load(data: str, sources: set[str], osm_mode: str, report: dict):
    ov_dir = os.path.join(data, "overture")
    div_area = os.path.join(ov_dir, "division_area_eg.parquet")
    inside = egypt_inside(div_area)
    recs: list[R.Record] = []
    segs = []

    def have(path):
        ok = os.path.exists(path)
        if not ok:
            report.setdefault("skipped", []).append(os.path.basename(path))
        return ok

    if "overture" in sources and have(os.path.join(ov_dir, "places_eg_bbox.parquet")):
        t = time.time()
        rows = list(S.overture_places(os.path.join(ov_dir, "places_eg_bbox.parquet"), inside))
        recs += rows
        log("overture places", len(rows), f"{time.time() - t:.0f}s")
    if "div" in sources and have(os.path.join(ov_dir, "division_eg.parquet")):
        rows = list(S.overture_areas(os.path.join(ov_dir, "division_eg.parquet"), div_area))
        recs += rows
        log("overture divisions", len(rows))
    def optional(name, fn):
        """A secondary source that breaks is skipped and reported — never the whole release."""
        try:
            rows = list(fn())
        except Exception as e:  # noqa: BLE001 — any adapter failure
            log(name, "FAILED, skipped:", repr(e)[:300])
            report.setdefault("failed", []).append(f"{name}: {e!r}"[:300])
            return []
        log(name, len(rows))
        return rows

    if "osm" in sources:
        pbf_ok = False
        if osm_mode == "pbf" and have(os.path.join(data, "egypt-latest.osm.pbf")):
            t = time.time()
            try:
                rows, segs = S.osm_pbf(os.path.join(data, "egypt-latest.osm.pbf"))
                rows = [r for r in rows if inside(r.lat, r.lng)]
                recs += rows
                pbf_ok = True
                log("osm pbf", len(rows), "segments", len(segs), f"{time.time() - t:.0f}s")
            except Exception as e:  # noqa: BLE001 — fall back to HOT's export below
                log("osm pbf FAILED:", repr(e)[:300])
                report.setdefault("failed", []).append(f"osm pbf: {e!r}"[:300])
                segs = []
        if not pbf_ok and have(os.path.join(data, "osm_hot", "points_of_interest.parquet")):
            rows = [r for r in S.osm_hot(os.path.join(data, "osm_hot")) if inside(r.lat, r.lng)]
            recs += rows
            if os.path.exists(os.path.join(data, "osm_hot", "roads_named.parquet")):
                segs = list(S.osm_hot_streets(os.path.join(data, "osm_hot")))
            log("osm hot", len(rows), "segments", len(segs))
    if "fsq" in sources and have(os.path.join(data, "fsq.parquet")):
        recs += optional("foursquare", lambda: S.fsq_places(os.path.join(data, "fsq.parquet"), inside))
    if "wd" in sources and have(os.path.join(data, "wikidata.json")):
        recs += optional("wikidata", lambda: S.wikidata_places(os.path.join(data, "wikidata.json"), inside))
    if "gn" in sources and have(os.path.join(data, "EG.txt")):
        recs += optional("geonames", lambda: S.geonames_places(os.path.join(data, "EG.txt"), inside))
    return recs, segs, div_area


def run(data: str, out: str, sources: set[str], osm_mode: str, version: str, cache: str | None = None,
        media: bool = True) -> dict:
    report: dict = {"version": version, "sources": sorted(sources)}
    t0 = time.time()
    if cache and os.path.exists(cache):
        import pickle
        with open(cache, "rb") as f:
            places, streets, report, div_area = pickle.load(f)
        log("reused merge cache", cache, len(places), len(streets))
        lex = E.load_lexicon(LEXICON)
    else:
        recs, segs, div_area = load(data, sources, osm_mode, report)
        n0 = len(recs)
        recs = [r for r in recs if E.keep(r)]
        for r in recs:
            if r.kind == "poi":
                r.cat = T.refine_by_name(r.cat, [n for n, _ in r.names])
        report["records"] = {"loaded": n0, "kept": len(recs), "by_source": dict(Counter(r.src for r in recs))}
        log("records kept", len(recs), "of", n0)
        lex = E.load_lexicon(LEXICON)
        missing = T.validate({c["id"] for c in lex["categories"]})
        if missing:
            raise SystemExit(f"taxonomy points at search categories the lexicon lacks: {missing}")
        M.set_area_tokens([n for r in recs if r.kind == "area" for n, _ in r.names])
        commons_by_key = {r.key: r.extra["commons"] for r in recs if r.extra.get("commons")}
        brand_by_key = {r.key: r.brand_wd for r in recs if r.brand_wd and str(r.brand_wd).startswith("Q")}
        t = time.time()
        places = M.merge(recs)
        report["osm_commons"] = {p.pid: commons_by_key[k] for p in places for k in p.members if k in commons_by_key}
        report["brand_wd"] = {p.pid: brand_by_key[k] for p in places for k in reversed(p.members) if k in brand_by_key}
        log("merged places", len(places), f"{time.time() - t:.0f}s")
        streets = ST.build_streets(segs) if segs else []
        log("street pieces", len(streets))
        if cache:
            import pickle
            with open(cache, "wb") as f:
                pickle.dump((places, streets, report, div_area), f)
    M.set_area_tokens([n for p in places if p.kind == "area" for n in (p.name_ar, p.name_en) if n])

    gov = E.GovLocator(div_area)
    areas = [p for p in places if p.kind == "area"]
    al = E.AreaLocator(areas)
    bm = E.BrandMatcher(lex)
    for p in places + streets:
        p.gov = gov.locate(p.lat, p.lng)
        if p.kind != "area":
            a = al.locate(p.lat, p.lng)
            if a:
                p.area_ar, p.area_en = a.name_ar, a.name_en
        if p.kind == "poi":
            c = T.BY_ID.get(p.cat)
            p.brand_key = bm.match([x for x in (p.name_ar, p.name_en, *p.alt) if x], p.cat, c.scat if c else None, p.brand)
    autob = E.auto_brands(places, bm.descriptive)
    for p in places:
        if not p.brand_key and p.pid in autob:
            p.brand_key = autob[p.pid]
    allp = places + streets
    if media:
        # freely licensed photos where the open data names or shows the place, credited (docs/place-photos-2026-10.md)
        md = MD.collect([p for p in places if p.kind != "street"], report.get("osm_commons", {}),
                        brand_wd=report.get("brand_wd", {}), others=streets)
        TL.set_media(md)
        how = Counter(ph.how for m in md.values() for ph in m.photos)
        report["media"] = {"places": len(md), "with_photo": sum(1 for m in md.values() if m.photos),
                           "photos": sum(how.values()), "by_how": dict(how),
                           "with_logo": sum(1 for m in md.values() if m.logo),
                           "pois_with_photo": sum(1 for p in places if p.kind == "poi" and md.get(p.pid) and md[p.pid].photos)}
    report.pop("osm_commons", None)
    report.pop("brand_wd", None)
    t = time.time()
    ment = E.mentions(allp)
    for p in allp:
        n = ment.get(p.pid, 0)
        if n:
            p.pop = round(min(1.0, p.pop + E.mention_boost(n)), 3)
    log("mentions", len(ment), f"{time.time() - t:.0f}s")
    report["places"] = {"total": len(allp), "by_kind": dict(Counter(p.kind for p in allp)),
                        "multi_source": sum(1 for p in places if bin(p.srcs).count("1") > 1),
                        "with_phone": sum(1 for p in places if p.phone), "with_hours": sum(1 for p in places if p.hours),
                        "with_website": sum(1 for p in places if p.website),
                        "branded": sum(1 for p in places if p.brand_key)}
    return _emit(allp, out, sources, version, report, t0)


def _emit(allp, out, sources, version, report, t0):
    meta = {"version": version, "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "license": "ODbL-1.0 (https://opendatacommons.org/licenses/odbl/1-0/)",
            "attribution": "© OpenStreetMap contributors; Overture Maps Foundation; Foursquare OS Places (Apache-2.0); "
                           "Wikidata (CC0); GeoNames (CC BY 4.0)",
            "sources": ",".join(sorted(sources))}
    manifest = TL.build_tiles(allp, out, meta)
    report["tiles"] = manifest["totals"]
    report["seconds"] = round(time.time() - t0)
    with open(os.path.join(out, "build_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    log("done", json.dumps(report["tiles"]))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sources", default="osm,overture,div,fsq,wd,gn")
    ap.add_argument("--osm", default="pbf", choices=["pbf", "hot"])
    ap.add_argument("--version", default=dt.date.today().isoformat())
    ap.add_argument("--cache", help="pickle of the merged places: written after a merge, reused when present")
    ap.add_argument("--no-media", action="store_true", help="skip the Commons photos (no network)")
    a = ap.parse_args(argv)
    run(a.data, a.out, set(a.sources.split(",")), a.osm, a.version, a.cache, media=not a.no_media)


if __name__ == "__main__":
    main()
