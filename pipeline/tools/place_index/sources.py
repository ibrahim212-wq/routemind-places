"""Source adapters: each turns one open dataset into Records (records.py).

    overture_places   Overture Places (Meta, Microsoft, Foursquare, AllThePlaces, PinMeTo rows)
    overture_areas    Overture Divisions (neighbourhoods, localities, markaz, governorates; ODbL)
    osm_hot           OpenStreetMap from HOT's Egypt export (S3 GeoParquet; desk runs and fallback)
    osm_pbf           OpenStreetMap from the Geofabrik extract via pyosmium (the refresh pipeline)
    fsq_places        Foursquare OS Places via the Places Portal's Iceberg catalog (token-gated)
    wikidata_places   Wikidata items located in Egypt (landmarks, popularity = sitelinks)
    geonames_places   GeoNames EG dump (villages and hamlets with Arabic alternate names)

Every adapter is pure transformation over files fetch.py already wrote; none of them calls a
network except fsq_places / wikidata (which fetch.py drives).
"""
from __future__ import annotations

import json
import math
import re
from typing import Iterable, Iterator

from . import records as R
from . import taxonomy as T
from . import textnorm as tn

# ── Overture places ──────────────────────────────────────────────────────────

_OV_DATASET = {"meta": R.SRC_META, "Microsoft": R.SRC_MS, "Foursquare": R.SRC_FSQ,
               "AllThePlaces": R.SRC_ATP}


def _ov_src(sources) -> tuple[str, list[str]]:
    datasets = []
    for s in sources or []:
        d = s.get("dataset")
        if d and d not in datasets:
            datasets.append(d)
    main = None
    for s in sources or []:
        if not s.get("property"):
            main = s.get("dataset")
            break
    main = main or (datasets[0] if datasets else "meta")
    return _OV_DATASET.get(main, R.SRC_OVT_OTHER), datasets


def _point(geom_wkb: bytes) -> tuple[float, float] | None:
    import shapely
    g = shapely.from_wkb(geom_wkb)
    if g is None or g.is_empty:
        return None
    if g.geom_type != "Point":
        g = g.representative_point()
    return g.y, g.x


def overture_places(parquet_path: str, inside) -> Iterator[R.Record]:
    """`inside(lat, lng) -> bool` = the Egypt polygon test (build.py passes it)."""
    import pyarrow.parquet as pq
    cols = ["id", "geometry", "confidence", "websites", "socials", "phones", "brand", "addresses",
            "names", "sources", "operating_status", "taxonomy"]
    pf = pq.ParquetFile(parquet_path)
    for batch in pf.iter_batches(batch_size=20000, columns=cols):
        for row in batch.to_pylist():
            if row.get("operating_status") == "permanently_closed":
                continue
            addrs = row.get("addresses") or []
            country = next((a.get("country") for a in addrs if a and a.get("country")), None)
            pt = _point(row["geometry"])
            if pt is None:
                continue
            lat, lng = pt
            if country and country != "EG":
                continue
            if not country and not inside(lat, lng):
                continue
            names = row.get("names") or {}
            primary = names.get("primary")
            if not primary:
                continue
            nm: list[tuple[str, str]] = [(primary, "primary")]
            for lang, val in (names.get("common") or []) if isinstance(names.get("common"), list) else (names.get("common") or {}).items():
                if val and lang in ("ar", "en", "arz"):
                    nm.append((val, "ar" if lang in ("ar", "arz") else "en"))
            ar, la = R.split_scripts(primary)
            if ar and la:
                nm.append((ar, "ar"))
                nm.append((la, "en"))
            brand = row.get("brand") or {}
            bnames = (brand.get("names") or {}) if brand else {}
            bprim = bnames.get("primary") if bnames else None
            if bprim:
                nm.append((bprim, "brand"))
            tax = row.get("taxonomy") or {}
            cat = T.overture_cat(tax.get("primary"), tax.get("hierarchy"))
            src, datasets = _ov_src(row.get("sources"))
            a0 = addrs[0] if addrs else {}
            socials = row.get("socials") or []
            yield R.Record(
                src=src, sid=row["id"], kind="poi", cat=cat, lat=lat, lng=lng, names=nm,
                brand=bprim, brand_wd=(brand.get("wikidata") if brand else None),
                conf=float(row.get("confidence") or 0.3),
                phone=R.clean_phone((row.get("phones") or [None])[0]),
                website=R.clean_url((row.get("websites") or [None])[0]),
                social=socials[0] if socials else None,
                addr=(a0 or {}).get("freeform"),
                closed=row.get("operating_status") == "temporarily_closed",
                extra={"ovt_id": row["id"], "datasets": datasets,
                       "locality": (a0 or {}).get("locality")},
            )


# ── Overture divisions (areas) ───────────────────────────────────────────────

_DIV_CAT = {"region": "governorate", "county": "markaz", "locality": "city", "macrohood": "district",
            "neighborhood": "neighbourhood", "microhood": "neighbourhood"}


def overture_areas(division_path: str, area_path: str) -> Iterator[R.Record]:
    import pyarrow.parquet as pq
    import shapely
    # extents from the polygons, keyed by division id
    extent: dict[str, float] = {}
    at = pq.read_table(area_path, columns=["division_id", "geometry", "country", "class"]).to_pylist()
    for a in at:
        if a["country"] != "EG" or a["class"] != "land":
            continue
        g = shapely.from_wkb(a["geometry"])
        if g is None or g.is_empty:
            continue
        minx, miny, maxx, maxy = g.bounds
        r = 0.5 * R.haversine(miny, minx, maxy, maxx)
        extent[a["division_id"]] = max(extent.get(a["division_id"], 0.0), r)
    rows = pq.read_table(division_path, columns=["id", "geometry", "country", "subtype", "class", "names",
                                                 "population", "wikidata", "local_type"]).to_pylist()
    for d in rows:
        if d["country"] != "EG" or d["subtype"] not in _DIV_CAT:
            continue
        pt = _point(d["geometry"])
        if not pt:
            continue
        names = d.get("names") or {}
        prim = names.get("primary")
        if not prim:
            continue
        nm = [(prim, "primary")]
        common = names.get("common") or {}
        items = common if isinstance(common, list) else common.items()
        for lang, val in items:
            if val and lang in ("ar", "en"):
                nm.append((val, lang))
        cat = _DIV_CAT[d["subtype"]]
        if cat == "city" and (d.get("population") or 0) and (d.get("population") or 0) < 15000:
            cat = "village"
        lt = (d.get("local_type") or {})
        lt_items = dict(lt if not isinstance(lt, list) else lt)
        if cat == "city" and any("قرية" in (v or "") or "village" in (v or "").lower() for v in lt_items.values()):
            cat = "village"
        yield R.Record(src=R.SRC_DIV, sid=d["id"], kind="area", cat=cat, lat=pt[0], lng=pt[1], names=nm,
                       conf=0.9, wd=d.get("wikidata"), population=int(d.get("population") or 0),
                       extent_m=extent.get(d["id"], 0.0), extra={"subtype": d["subtype"]})


# ── OSM: shared tag handling ─────────────────────────────────────────────────

OSM_NAME_KEYS = ("name", "name:ar", "name:en", "name:arz", "alt_name", "alt_name:ar", "alt_name:en",
                 "official_name", "official_name:ar", "official_name:en", "old_name", "short_name",
                 "int_name", "loc_name", "brand", "brand:ar", "brand:en", "operator")
_ROLE = {"name": "primary", "name:ar": "ar", "name:arz": "ar", "name:en": "en", "int_name": "en",
         "brand": "brand", "brand:ar": "brand", "brand:en": "brand", "operator": "operator",
         "old_name": "old"}

PLACE_AREA = {"city": "city", "town": "town", "suburb": "district", "quarter": "neighbourhood",
              "neighbourhood": "neighbourhood", "village": "village", "hamlet": "hamlet",
              "isolated_dwelling": "hamlet", "locality": "hamlet", "borough": "district"}
STREET_HIGHWAY = {"motorway": "highway", "trunk": "highway", "primary": "road", "secondary": "road",
                  "tertiary": "street", "unclassified": "street", "residential": "street",
                  "living_street": "street", "service": "street", "pedestrian": "street",
                  "motorway_link": None, "trunk_link": None, "primary_link": None,
                  "secondary_link": None, "tertiary_link": None, "road": "street"}


def osm_names(tags: dict) -> list[tuple[str, str]]:
    out = []
    for k in OSM_NAME_KEYS:
        v = tags.get(k)
        if not v:
            continue
        for part in v.split(";"):
            part = part.strip()
            if part:
                out.append((part, _ROLE.get(k, "alt")))
    return out


def osm_record(tags: dict, osm_id: str, lat: float, lng: float, extent_m: float = 0.0,
               area_m2: float = 0.0) -> R.Record | None:
    """One OSM element → a POI or area Record, or None when it is neither."""
    place = tags.get("place")
    if place in PLACE_AREA and (tags.get("name") or tags.get("name:ar") or tags.get("name:en")):
        try:
            pop = int(re.sub(r"[^0-9]", "", tags.get("population", "") or "0") or 0)
        except ValueError:
            pop = 0
        return R.Record(src=R.SRC_OSM, sid=osm_id, kind="area", cat=PLACE_AREA[place], lat=lat, lng=lng,
                        names=osm_names(tags), conf=0.9, wd=tags.get("wikidata"), population=pop,
                        extent_m=extent_m, extra={"commons": _commons_file(tags)})
    cat = T.osm_cat(tags)
    if cat is None:
        # a named building / landuse / natural feature is still something people search for
        if not (tags.get("name") or tags.get("name:ar") or tags.get("name:en")):
            return None
        if tags.get("building"):
            cat = "tower" if tags.get("building") in ("tower", "office") and area_m2 > 400 else "building"
        elif tags.get("landuse") == "residential":
            cat = "compound"
        elif tags.get("natural"):
            cat = "natural"
        elif tags.get("bridge") == "yes" or tags.get("man_made") == "bridge":
            cat = "bridge"
        else:
            return None
    names = osm_names(tags)
    if not names and cat in ("place", "shop", "service", "building", "office"):
        return None  # an unnamed generic thing is noise; an unnamed fuel station is not
    conf = 0.85 if names else 0.75
    if tags.get("disused") or tags.get("abandoned") or tags.get("disused:amenity") or tags.get("was:amenity"):
        return None
    addr = None
    if tags.get("addr:street"):
        addr = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    elif tags.get("addr:full"):
        addr = tags["addr:full"]
    return R.Record(
        src=R.SRC_OSM, sid=osm_id, kind="poi", cat=cat, lat=lat, lng=lng, names=names,
        brand=tags.get("brand") or tags.get("brand:en"), brand_wd=tags.get("brand:wikidata"),
        conf=conf, phone=R.clean_phone(tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
                                       or tags.get("contact:mobile")),
        website=R.clean_url(tags.get("website") or tags.get("contact:website") or tags.get("url")),
        social=tags.get("contact:facebook") or tags.get("facebook"),
        hours=tags.get("opening_hours"), addr=addr, street=tags.get("addr:street"),
        wd=tags.get("wikidata"), extent_m=extent_m,
        extra={"area_m2": area_m2, "wikipedia": bool(tags.get("wikipedia")),
               "commons": _commons_file(tags)},
    )


def _commons_file(tags: dict) -> str | None:
    """A photo of the place on Wikimedia Commons named by OSM (`wikimedia_commons=File:…`, or an `image=`
    pointing at a Commons file) — media.py credits it from Commons' own metadata."""
    from .media import file_name
    return file_name(tags.get("wikimedia_commons")) or file_name(tags.get("image"))


# ── OSM via the HOT export (desk) ────────────────────────────────────────────

_HOT_POI_LAYERS = ("points_of_interest", "health_facilities", "education_facilities", "financial_services",
                   "cultural_places", "airports", "railways", "sea_ports")
_HOT_TAG_COLS = ("amenity", "shop", "tourism", "man_made", "healthcare", "historic", "aeroway", "railway",
                 "building", "office", "opening_hours", "website", "operator", "network", "emergency")


def _hot_osm_id(raw: str) -> str:
    t, _, n = raw.partition("/")
    return (t[:1] if t else "x") + n


def _geom_point_extent(wkb):
    import shapely
    g = shapely.from_wkb(wkb)
    if g is None or g.is_empty:
        return None
    if g.geom_type in ("Point", "MultiPoint"):
        p = g.centroid if g.geom_type == "MultiPoint" else g
        return p.y, p.x, 0.0, 0.0
    c = g.representative_point() if g.geom_type in ("Polygon", "MultiPolygon") else g.interpolate(0.5, normalized=True)
    minx, miny, maxx, maxy = g.bounds
    ext = 0.5 * R.haversine(miny, minx, maxy, maxx)
    area = 0.0
    if g.geom_type in ("Polygon", "MultiPolygon"):
        lat0 = math.radians(c.y)
        area = g.area * (111320.0 ** 2) * math.cos(lat0)
    return c.y, c.x, ext, area


def osm_hot(hot_dir: str) -> Iterator[R.Record]:
    import pyarrow.parquet as pq
    seen: set[str] = set()
    for layer in _HOT_POI_LAYERS:
        path = f"{hot_dir}/{layer}.parquet"
        try:
            t = pq.read_table(path)
        except FileNotFoundError:
            continue
        cols = set(t.column_names)
        for row in t.to_pylist():
            oid = _hot_osm_id(row["id"])
            if oid in seen:
                continue
            g = _geom_point_extent(row["geom"])
            if not g:
                continue
            lat, lng, ext, area = g
            tags = {}
            for k in _HOT_TAG_COLS:
                if k in cols and row.get(k):
                    tags[k] = row[k]
            for k, tk in (("name", "name"), ("name_ar", "name:ar"), ("name_en", "name:en")):
                if row.get(k):
                    tags[tk] = row[k]
            if row.get("addr_street"):
                tags["addr:street"] = row["addr_street"]
                if row.get("addr_housenumber"):
                    tags["addr:housenumber"] = row["addr_housenumber"]
            if layer == "railways" and not (tags.get("railway") in ("station", "halt")):
                continue
            if layer == "airports" and tags.get("aeroway") not in ("aerodrome", "terminal"):
                continue
            rec = osm_record(tags, oid, lat, lng, ext, area)
            if rec:
                seen.add(oid)
                yield rec
    # named buildings (malls, towers, hospitals mapped only as a building)
    try:
        t = pq.read_table(f"{hot_dir}/buildings.parquet", filters=[("name", "!=", "")])
    except Exception:
        t = None
    if t is not None:
        for row in t.to_pylist():
            if not (row.get("name") or row.get("name_ar") or row.get("name_en")):
                continue
            oid = _hot_osm_id(row["id"])
            if oid in seen:
                continue
            g = _geom_point_extent(row["geom"])
            if not g:
                continue
            tags = {"building": row.get("building") or "yes"}
            if row.get("office"):
                tags["office"] = row["office"]
            for k, tk in (("name", "name"), ("name_ar", "name:ar"), ("name_en", "name:en")):
                if row.get(k):
                    tags[tk] = row[k]
            rec = osm_record(tags, oid, g[0], g[1], g[2], g[3])
            if rec:
                seen.add(oid)
                yield rec
    # settlements
    t = pq.read_table(f"{hot_dir}/populated_places.parquet")
    for row in t.to_pylist():
        if not row.get("place"):
            continue
        g = _geom_point_extent(row["geom"])
        if not g:
            continue
        tags = {"place": row["place"], "population": str(row.get("population") or "")}
        for k, tk in (("name", "name"), ("name_ar", "name:ar"), ("name_en", "name:en")):
            if row.get(k):
                tags[tk] = row[k]
        rec = osm_record(tags, _hot_osm_id(row["id"]), g[0], g[1], g[2], g[3])
        if rec:
            yield rec


def osm_hot_streets(hot_dir: str) -> Iterator[tuple[str, dict, list[tuple[float, float]]]]:
    """(osm id, tags, polyline [(lat, lng)…]) for every named road segment."""
    import pyarrow.parquet as pq
    import shapely
    t = pq.read_table(f"{hot_dir}/roads_named.parquet")
    for row in t.to_pylist():
        g = shapely.from_wkb(row["geom"])
        if g is None or g.is_empty:
            continue
        if g.geom_type == "MultiLineString":
            lines = list(g.geoms)
        elif g.geom_type == "LineString":
            lines = [g]
        elif g.geom_type in ("Polygon", "MultiPolygon"):
            polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
            lines = [pg.exterior for pg in polys]  # a pedestrian square / roundabout area
        else:
            continue
        tags = {"highway": row.get("highway") or "road"}
        for k, tk in (("name", "name"), ("name_ar", "name:ar"), ("name_en", "name:en")):
            if row.get(k):
                tags[tk] = row[k]
        for ln in lines:
            pts = [(y, x) for x, y in ln.coords]
            if len(pts) >= 2:
                yield _hot_osm_id(row["id"]), tags, pts


# ── OSM via pyosmium (refresh pipeline) ──────────────────────────────────────

_POI_KEYS = ("amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "historic", "aeroway",
             "railway", "public_transport", "emergency", "diplomatic", "military", "place", "man_made",
             "station", "natural", "landuse", "building", "industrial", "highway", "barrier")


def osm_pbf(pbf_path: str):
    """Returns (records, street segments) from a .osm.pbf (or .osm XML in tests)."""
    import osmium

    recs: list[R.Record] = []
    segs: list[tuple[str, dict, list[tuple[float, float]]]] = []

    def interesting(tags) -> bool:
        return any(k in tags for k in _POI_KEYS)

    class H(osmium.SimpleHandler):
        def node(self, n):
            if not n.tags or not interesting(n.tags):
                return
            tags = {t.k: t.v for t in n.tags}
            if tags.get("highway") and tags.get("highway") not in ("bus_stop", "rest_area", "services"):
                return
            if not n.location.valid():
                return
            rec = osm_record(tags, f"n{n.id}", n.location.lat, n.location.lon)
            if rec:
                recs.append(rec)

        def way(self, w):
            tags = {t.k: t.v for t in w.tags}
            hw = tags.get("highway")
            if hw and (tags.get("name") or tags.get("name:ar") or tags.get("name:en")) and hw in STREET_HIGHWAY:
                pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
                if len(pts) >= 2:
                    segs.append((f"w{w.id}", tags, pts))
            if w.is_closed() and len(w.nodes) >= 4 and interesting(tags) and not hw:
                pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
                if len(pts) < 3:
                    return
                lat = sum(p[0] for p in pts) / len(pts)
                lng = sum(p[1] for p in pts) / len(pts)
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                ext = 0.5 * R.haversine(min(ys), min(xs), max(ys), max(xs))
                area = _ring_area_m2(pts)
                rec = osm_record(tags, f"w{w.id}", lat, lng, ext, area)
                if rec:
                    recs.append(rec)

        def relation(self, r):
            tags = {t.k: t.v for t in r.tags}
            if tags.get("type") != "multipolygon" or not interesting(tags):
                return
            # position resolved after the pass from member ways' first nodes (cheap, good enough
            # for a search pin; the extent comes from the same coordinates)
            rel_pending.append((r.id, tags, [m.ref for m in r.members if m.type == "w"]))

    rel_pending: list[tuple[int, dict, list[int]]] = []
    h = H()
    h.apply_file(pbf_path, locations=True)
    if rel_pending:
        want = {wid for _, _, ws in rel_pending for wid in ws}
        coords: dict[int, tuple[float, float]] = {}

        class W(osmium.SimpleHandler):
            def way(self, w):
                if w.id in want:
                    pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
                    if pts:
                        coords[w.id] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

        W().apply_file(pbf_path, locations=True)
        for rid, tags, ws in rel_pending:
            pts = [coords[w] for w in ws if w in coords]
            if not pts:
                continue
            lat = sum(p[0] for p in pts) / len(pts)
            lng = sum(p[1] for p in pts) / len(pts)
            ys = [p[0] for p in pts]
            xs = [p[1] for p in pts]
            ext = 0.5 * R.haversine(min(ys), min(xs), max(ys), max(xs))
            rec = osm_record(tags, f"r{rid}", lat, lng, ext, math.pi * ext * ext * 0.5)
            if rec:
                recs.append(rec)
    return recs, segs


def _ring_area_m2(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    lat0 = math.radians(sum(p[0] for p in pts) / len(pts))
    kx = 111320.0 * math.cos(lat0)
    ky = 110540.0
    s = 0.0
    for i in range(len(pts)):
        y1, x1 = pts[i]
        y2, x2 = pts[(i + 1) % len(pts)]
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2.0


# ── Foursquare OS Places (Iceberg, token-gated) ──────────────────────────────

FSQ_LEAF = {
    "Pharmacy": "pharmacy", "Hospital": "hospital", "Gas Station": "gas_station", "Fuel Station": "gas_station",
    "Café": "cafe", "Coffee Shop": "coffee_shop", "Restaurant": "restaurant", "Fast Food Restaurant": "fast_food",
    "Bank": "bank", "ATM": "atm", "Supermarket": "supermarket", "Grocery Store": "grocery",
    "Shopping Mall": "mall", "Mosque": "mosque", "Church": "church", "School": "school",
    "University": "university", "College and University": "university", "Hotel": "hotel",
    "Dentist": "dental_clinic", "Doctor's Office": "doctor", "Medical Center": "medical_center",
    "Bakery": "bakery", "Dessert Shop": "sweets", "Ice Cream Parlor": "ice_cream", "Juice Bar": "juice_bar",
    "Pizzeria": "pizza", "Burger Joint": "burger", "Seafood Restaurant": "seafood", "Gym": "gym",
    "Gym and Studio": "gym", "Park": "park", "Museum": "museum", "Historic and Protected Site": "historic_site",
    "Beach": "beach", "Movie Theater": "cinema", "Train Station": "train_station", "Metro Station": "metro_station",
    "Bus Station": "bus_station", "Airport": "airport", "Police Station": "police", "Post Office": "post_office",
    "Clothing Store": "clothes", "Shoe Store": "shoes", "Mobile Phone Store": "mobile_shop",
    "Electronics Store": "electronics", "Furniture and Home Store": "furniture", "Hardware Store": "hardware",
    "Jewelry Store": "jewelry", "Optometrist": "optician", "Car Dealership": "car_dealer",
    "Automotive Repair Shop": "car_repair", "Car Wash": "car_wash", "Parking": "parking",
    "Laundry Service": "laundry", "Barbershop": "barber", "Salon": "beauty_salon", "Spa": "spa",
    "Bookstore": "bookshop", "Butcher": "butcher", "Market": "market", "Convenience Store": "convenience",
    "Real Estate Agency": "real_estate", "Travel Agency": "travel_agency", "Lawyer": "lawyer",
    "Government Building": "government", "Embassy or Consulate": "embassy", "Courthouse": "courthouse",
    "Stadium": "stadium", "Sports Club": "sports_club", "Night Club": "nightclub", "Bar": "bar",
    "Lounge": "lounge", "Hookah Bar": "ahwa", "Veterinarian": "veterinary", "Medical Lab": "medical_lab",
    "Event Space": "event_venue", "Wedding Hall": "event_venue", "Tea Room": "ahwa",
}


def fsq_places(parquet_path: str, inside) -> Iterator[R.Record]:
    """Rows fetch.fetch_fsq wrote (already cut to the Egypt box)."""
    import pyarrow.parquet as pq
    t = pq.read_table(parquet_path)
    for row in t.to_pylist():
        if row.get("date_closed"):
            continue
        lat, lng = row.get("latitude"), row.get("longitude")
        if lat is None or lng is None or not inside(lat, lng):
            continue
        if not row.get("name"):
            continue
        labels = row.get("fsq_category_labels") or []
        cat = "place"
        for lab in labels:
            leaf = lab.split(">")[-1].strip()
            if leaf in FSQ_LEAF:
                cat = FSQ_LEAF[leaf]
                break
        nm = [(row["name"], "primary")]
        ar, la = R.split_scripts(row["name"])
        if ar and la:
            nm += [(ar, "ar"), (la, "en")]
        refreshed = str(row.get("date_refreshed") or "")
        conf = 0.55
        if refreshed[:4].isdigit():
            age = 2026 - int(refreshed[:4])
            conf = max(0.25, 0.75 - 0.1 * age)
        yield R.Record(src=R.SRC_FSQ, sid=row["fsq_place_id"], kind="poi", cat=cat, lat=lat, lng=lng, names=nm,
                       conf=conf, phone=R.clean_phone(row.get("tel")), website=R.clean_url(row.get("website")),
                       social=("https://facebook.com/" + row["facebook_id"]) if row.get("facebook_id") else None,
                       addr=row.get("address"), extra={"refreshed": refreshed})


# ── Wikidata ─────────────────────────────────────────────────────────────────

def wikidata_places(json_path: str, inside) -> Iterator[R.Record]:
    """Rows fetch.fetch_wikidata wrote: {qid, lat, lng, ar, en, alt_ar, alt_en, sitelinks, cls}."""
    with open(json_path, encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        if not inside(r["lat"], r["lng"]):
            continue
        nm = []
        if r.get("ar"):
            nm.append((r["ar"], "ar"))
        if r.get("en"):
            nm.append((r["en"], "en"))
        for a in (r.get("alt_ar") or [])[:4]:
            nm.append((a, "alt"))
        for a in (r.get("alt_en") or [])[:4]:
            nm.append((a, "alt"))
        if not nm:
            continue
        cat = r.get("cat") or "landmark"
        yield R.Record(src=R.SRC_WD, sid=r["qid"], kind="area" if cat in T.AREA_CATS else "poi", cat=cat,
                       lat=r["lat"], lng=r["lng"], names=nm, conf=0.9, wd=r["qid"],
                       population=int(r.get("population") or 0),
                       extra={"sitelinks": int(r.get("sitelinks") or 0)})


# ── GeoNames ─────────────────────────────────────────────────────────────────

_GN_CAT = {"PPLA": "city", "PPLA2": "city", "PPLA3": "town", "PPLC": "city", "PPL": "village",
           "PPLX": "neighbourhood", "PPLL": "hamlet", "PPLF": "hamlet", "PPLQ": None, "PPLH": None}


def geonames_places(txt_path: str, inside) -> Iterator[R.Record]:
    """EG.txt (tab separated, the GeoNames dump schema)."""
    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 19 or p[6] != "P":
                continue
            cat = _GN_CAT.get(p[7], "village" if p[7].startswith("PPL") else None)
            if not cat:
                continue
            lat, lng = float(p[4]), float(p[5])
            if not inside(lat, lng):
                continue
            nm = [(p[1], "en")]
            for alt in p[3].split(","):
                alt = alt.strip()
                if alt and tn.script_of(tn.normalize(alt)) == "ar":
                    nm.append((alt, "ar"))
            pop = int(p[14] or 0)
            if cat == "village" and pop >= 50000:
                cat = "town"
            yield R.Record(src=R.SRC_GN, sid=p[0], kind="area", cat=cat, lat=lat, lng=lng, names=nm[:6],
                           conf=0.7, population=pop)
