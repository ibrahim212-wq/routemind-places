"""How much of what our index misses does a live provider find? Tested on real misses, across governorates.

    python -m tools.place_index.bench.live_probe sample --rows <rows.jsonl> --out <sample.json> [--n 120]
    python -m tools.place_index.bench.live_probe run --sample <sample.json> --provider mapbox_box --keys <keys.env> --out <dir> [--max 60]

The sample (dev split only, nothing here reads the held split's failures):
  miss     red-team targets with NO right row in our index: the places a user could not find
  shop     small places known to one source only (Overture / Foursquare): a provider's recall on the long tail, by name, at the shop

Keys come from a `keys.env` outside the repo (NAME=value lines), never printed. Provider answers are judged in memory and DISCARDED:
only true / false and counts are written, so nothing from any provider is stored and nothing goes into the index or into tuning.

Google and Apple are not providers here, and never will be: the goal file forbids using their data to measure anything."""
from __future__ import annotations

import argparse
import json
import os
import random
import ssl
import sys
import time
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict

from .. import engine as E
from .. import textnorm as tn
from .redteam_fair import Rows, _items, _right_rows
from .run import names_match

GOVS = ["cairo", "alexandria", "dakahlia", "sohag", "aswan", "red_sea", "minya", "matrouh", "gharbia", "qena"]
SINGLE = {8: "ms", 16: "meta", 4: "fsq"}
WAIT_S = 0.34


def _dev(q: str) -> bool:
    return zlib.crc32(tn.normalize(q).encode("utf8")) % 10 < 7


def cmd_sample(a):
    rnd = random.Random(20261106)
    rows = Rows(a.rows)
    per_type: dict = defaultdict(list)
    for (gov, i), it in sorted(_items().items()):
        if gov not in GOVS or it["t"] not in ("place", "chain", "street") or not _dev(it["q"]):
            continue
        if _right_rows(it, rows, 1) == 0:
            lat, lng = it.get("near") or it.get("_anchor") or (None, None)
            if lat is None or not it.get("_anchor"):
                continue
            per_type[it["t"]].append({"set": "miss", "t": it["t"], "gov": gov, "q": it["q"], "lat": it["_anchor"][0], "lng": it["_anchor"][1],
                                      "names": it["names"], "at": [lat, lng], "km": it.get("r_km") or it.get("km")})
    sample = []
    for t, want in (("place", a.n // 3), ("chain", a.n // 3), ("street", a.n // 3)):
        rnd.shuffle(per_type[t])
        sample += per_type[t][:want]
    shops: dict = defaultdict(list)
    keep = {"restaurant", "cafe", "pharmacy", "clothing_store", "mobile_shop", "supermarket", "clinic", "bakery", "institute", "car_repair",
            "barber", "beauty_salon", "butcher", "tutoring", "hardware_store", "furniture_store", "fast_food", "dentist"}
    with open(a.rows, encoding="utf8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("kind") != 0 or r.get("scat") not in keep or r.get("gov") not in GOVS:
                continue
            s = r.get("srcs") or 0
            if (s & 0x7ff) not in SINGLE or r.get("brand"):
                continue
            nm = r.get("name_ar") or r.get("name_en")
            if nm and 2 <= len(tn.tokens(nm)) <= 5:
                shops[r["gov"]].append({"set": "shop", "t": r["scat"], "gov": r["gov"], "q": nm, "lat": r["lat"], "lng": r["lng"],
                                        "names": [nm], "at": [r["lat"], r["lng"]], "km": 1.5})
    per = max(1, a.n // len(GOVS))
    for g in GOVS:
        rnd.shuffle(shops[g])
        sample += shops[g][:per]
    json.dump(sample, open(a.out, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print(Counter((x["set"], x["t"] if x["set"] == "miss" else "") for x in sample), Counter(x["gov"] for x in sample))


def _get(url: str, headers: dict | None = None, body: bytes | None = None):
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "RouteMindSearchBench/1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:  # noqa: BLE001 (a provider's failure is a row in the report, not a crash)
        return 0, None


def p_mapbox_box(q, lat, lng, k):
    u = "https://api.mapbox.com/search/searchbox/v1/forward?" + urllib.parse.urlencode(
        {"q": q, "access_token": k["MAPBOX_ACCESS_TOKEN"], "language": "ar", "country": "EG", "proximity": f"{lng},{lat}", "limit": 5})
    st, j = _get(u)
    out = []
    for f in (j or {}).get("features", []):
        c = f["geometry"]["coordinates"]
        pr = f.get("properties", {})
        out.append({"name": pr.get("name"), "lat": c[1], "lng": c[0], "street": pr.get("feature_type") in ("street", "address")})
    return st, out


def p_mapbox_geo(q, lat, lng, k):
    u = "https://api.mapbox.com/search/geocode/v6/forward?" + urllib.parse.urlencode(
        {"q": q, "access_token": k["MAPBOX_ACCESS_TOKEN"], "language": "ar", "country": "EG", "proximity": f"{lng},{lat}", "limit": 5,
         "types": "street,address,place,locality,neighborhood"})
    st, j = _get(u)
    out = []
    for f in (j or {}).get("features", []):
        c = f["geometry"]["coordinates"]
        pr = f.get("properties", {})
        out.append({"name": pr.get("name"), "lat": c[1], "lng": c[0], "street": pr.get("feature_type") in ("street", "address")})
    return st, out


def p_tomtom(q, lat, lng, k):
    u = f"https://api.tomtom.com/search/2/search/{urllib.parse.quote(q)}.json?" + urllib.parse.urlencode(
        {"key": k["TOMTOM_API_KEY"], "limit": 5, "lat": lat, "lon": lng, "countrySet": "EG", "language": "ar", "idxSet": "POI,Str,Addr,Geo"})
    st, j = _get(u)
    out = []
    for r in (j or {}).get("results", []):
        p = r.get("position", {})
        nm = (r.get("poi") or {}).get("name") or (r.get("address") or {}).get("streetName") or (r.get("address") or {}).get("freeformAddress")
        out.append({"name": nm, "lat": p.get("lat"), "lng": p.get("lon"), "street": r.get("type") in ("Street", "Cross Street", "Point Address")})
    return st, out


def p_here(q, lat, lng, k):
    u = "https://discover.search.hereapi.com/v1/discover?" + urllib.parse.urlencode(
        {"q": q, "at": f"{lat},{lng}", "limit": 5, "lang": "ar", "in": "countryCode:EGY", "apiKey": k["HERE_API_KEY"]})
    st, j = _get(u)
    out = []
    for r in (j or {}).get("items", []):
        p = r.get("position", {})
        out.append({"name": r.get("title"), "lat": p.get("lat"), "lng": p.get("lng"), "street": r.get("resultType") in ("street", "houseNumber")})
    return st, out


def p_here_auto(q, lat, lng, k):
    """HERE Autosuggest: the endpoint a typing list would call. Query / chain suggestions carry no position and are no answer."""
    u = "https://autosuggest.search.hereapi.com/v1/autosuggest?" + urllib.parse.urlencode(
        {"q": q, "at": f"{lat},{lng}", "limit": 5, "lang": "ar", "in": "countryCode:EGY", "apiKey": k["HERE_API_KEY"]})
    st, j = _get(u)
    out = []
    for r in (j or {}).get("items", []):
        p = r.get("position") or {}
        if not p:
            continue
        out.append({"name": r.get("title"), "lat": p.get("lat"), "lng": p.get("lng"), "street": r.get("resultType") in ("street", "houseNumber")})
    return st, out


def p_huawei(q, lat, lng, k):
    u = "https://siteapi.cloud.huawei.com/mapApi/v1/siteService/searchByText?key=" + urllib.parse.quote(k["HUAWEI_API_KEY"], safe="")
    b = json.dumps({"query": q, "location": {"lat": lat, "lng": lng}, "radius": 50000, "language": "ar", "countryCode": "EG", "pageSize": 5}).encode()
    st, j = _get(u, {"Content-Type": "application/json"}, b)
    out = []
    for s in (j or {}).get("sites", []):
        p = s.get("location", {})
        out.append({"name": s.get("name"), "lat": p.get("lat"), "lng": p.get("lng"), "street": False})
    return st, out


def p_geoapify(q, lat, lng, k):
    u = "https://api.geoapify.com/v1/geocode/search?" + urllib.parse.urlencode(
        {"text": q, "lang": "ar", "filter": "countrycode:eg", "bias": f"proximity:{lng},{lat}", "limit": 5, "format": "json", "apiKey": k["GEOAPIFY_API_KEY"]})
    st, j = _get(u)
    out = []
    for r in (j or {}).get("results", []):
        out.append({"name": r.get("name") or r.get("street"), "lat": r.get("lat"), "lng": r.get("lon"), "street": r.get("result_type") in ("street", "building")})
    return st, out


def p_foursquare(q, lat, lng, k):
    u = "https://places-api.foursquare.com/places/search?" + urllib.parse.urlencode({"query": q, "ll": f"{lat},{lng}", "limit": 5})
    st, j = _get(u, {"Authorization": "Bearer " + k["FOURSQUARE_API_KEY"], "X-Places-Api-Version": "2025-06-17", "Accept": "application/json"})
    out = []
    for r in (j or {}).get("results", []):
        out.append({"name": r.get("name"), "lat": r.get("latitude"), "lng": r.get("longitude"), "street": False})
    return st, out


def p_wikimapia(q, lat, lng, k):
    u = "http://api.wikimapia.org/?" + urllib.parse.urlencode(
        {"function": "search", "key": k["WIKIMAPIA_API_KEY"], "q": q, "lat": lat, "lon": lng, "format": "json", "count": 5, "language": "ar"})
    st, j = _get(u)
    out = []
    for r in (j or {}).get("folder", []):
        p = r.get("location", {})
        out.append({"name": r.get("name"), "lat": p.get("lat"), "lng": p.get("lon"), "street": False})
    return st, out


PROVIDERS = {"mapbox_box": p_mapbox_box, "mapbox_geo": p_mapbox_geo, "tomtom": p_tomtom, "here": p_here, "here_auto": p_here_auto, "huawei": p_huawei,
             "geoapify": p_geoapify, "foursquare": p_foursquare, "wikimapia": p_wikimapia}


def _keys(path: str) -> dict:
    out = dict(os.environ)
    if path and os.path.exists(path):
        for line in open(path, encoding="utf8"):
            if "=" in line and not line.lstrip().startswith("#"):
                a, b = line.split("=", 1)
                out[a.strip()] = b.strip().strip('"')
    return out


def cmd_run(a):
    sample = json.load(open(a.sample, encoding="utf8"))
    rnd = random.Random(7)
    rnd.shuffle(sample)
    if a.max:
        sample = sample[:a.max]
    fn = PROVIDERS[a.provider]
    k = _keys(a.keys)
    S: dict = defaultdict(Counter)
    status = Counter()
    rows = []
    t0 = time.time()
    for it in sample:
        st, res = fn(it["q"], it["lat"], it["lng"], k)
        status[st] += 1
        if st == 401 or st == 403:
            print("refused", st, "stopping: the key does not reach this API")
            break
        hit = rank = None
        for i, r in enumerate(res or []):
            if r.get("lat") is None or not r.get("name"):
                continue
            near = E.haversine(it["at"][0], it["at"][1], float(r["lat"]), float(r["lng"])) <= max(it["km"], 3.0) * 1000
            if near and names_match(it["names"], {"name_ar": r["name"], "name_en": r["name"]}) and \
                    (it["t"] != "street" or r["street"]):
                hit, rank = True, i + 1
                break
        ar = sum(1 for r in (res or []) if r.get("name") and any("؀" <= c <= "ۿ" for c in r["name"]))
        key = it["t"] if it["set"] == "miss" else "shop"
        for g in (key, "ALL_" + it["set"], "gov:" + it["gov"]):
            S[g]["n"] += 1
            S[g]["answered"] += bool(res)
            S[g]["hit"] += bool(hit)
            S[g]["hit1"] += rank == 1
            S[g]["rows"] += len(res or [])
            S[g]["ar_rows"] += ar
        # only the verdict is kept: the provider's rows are dropped here
        rows.append({"set": it["set"], "t": it["t"], "gov": it["gov"], "hit": bool(hit), "rank": rank, "st": st})
        time.sleep(WAIT_S)
    os.makedirs(a.out, exist_ok=True)
    out = {"provider": a.provider, "calls": sum(status.values()), "status": dict(status), "seconds": round(time.time() - t0),
           "by": {g: {**c, "hit_rate": round(c["hit"] / c["n"], 3)} for g, c in sorted(S.items())}, "verdicts": rows}
    json.dump(out, open(os.path.join(a.out, a.provider + ".json"), "w", encoding="utf8"), indent=0)
    print(a.provider, "calls", out["calls"], "status", out["status"])
    for g, v in out["by"].items():
        print(" ", g, {x: v[x] for x in ("n", "answered", "hit", "hit1", "hit_rate", "ar_rows", "rows")})


def main():
    sys.stdout.reconfigure(encoding="utf8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--rows", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--n", type=int, default=120)
    r = sub.add_parser("run")
    r.add_argument("--sample", required=True)
    r.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    r.add_argument("--keys")
    r.add_argument("--out", required=True)
    r.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    (cmd_sample if a.cmd == "sample" else cmd_run)(a)


if __name__ == "__main__":
    main()
