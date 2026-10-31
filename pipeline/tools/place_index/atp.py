"""AllThePlaces (CC0) — Egyptian chain branches, fetched directly (docs/place-search-2026-10.md).

    fetch_atp(data)          the latest run's Egyptian features → <data>/atp_eg.ndjson
    atp_places(path, inside) that file → Records (src = SRC_ATP)
    atp_key_of_overture(id)  the key an Overture row sourced from AllThePlaces shares with its ATP feature

Why a direct source at all: the index already receives AllThePlaces rows through Overture (≈ 1,500 in Egypt).
Measured 2026-10-31 against the 2026-10-24 run (7,321 Egyptian features, 82 spiders): ~96 % of Overture's
Egyptian AllThePlaces rows are still in the run, and apart from Banque Misr / NBK ATMs only ~40-120 branches
are missing from Overture — so this adapter is mainly the fresh copy (opening_hours, phones, websites) and
the ATMs. Both copies of one ATP place carry the SAME key (`extra["atp_key"]`), so build.py can fold them into
ONE record instead of two same-source claims.

The key: an ATP feature's `id` is urlsafe-base64(sha1(ref + spider)) (verified: sha1("Chillout-Elobour" +
"mcdonalds_eg") = the feature id of that McDonald's); Overture's sources[].record_id of an AllThePlaces row is
exactly that id. The key is the id normalised to urlsafe base64 without padding.

Network: the run's output.zip (≈ 2.9 GB) is never downloaded — its central directory and the entries of the
Egyptian spiders (≈ 100 spiders listed in stats/_insights.json, atp_splits.EG) are read with HTTP Range requests.

    python -m tools.place_index.atp --data <dir>          # fetch
    python -m tools.place_index.atp --selftest
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from typing import Callable, Iterator

from . import records as R
from . import taxonomy as T

BASE = "https://alltheplaces-data.openaddresses.io"
UA = "RouteMind-place-index/1.0 (+https://github.com/ibrahim212-wq/routemind-places)"
X0, X1, Y0, Y1 = 24.7, 36.9, 22.0, 31.7  # Egypt's box (lng, lat) for features without addr:country
OUT_NAME = "atp_eg.ndjson"
TRIES = 3
TIMEOUT = 180
_TAIL = 70000          # the zip's end-of-central-directory lives in the last 64 KiB + comment
_ENTRY_SLACK = 4096    # a local header's name + extra field, read together with the entry's data


def log(*a):
    print("[atp]", *a, flush=True)


# ── keys ─────────────────────────────────────────────────────────────────────

def atp_key(feature_id: str) -> str:
    """The shared key: urlsafe base64, no padding (Overture keeps the padding, the dumps vary)."""
    s = (feature_id or "").strip().replace("+", "-").replace("/", "_")
    return s.rstrip("=")


def atp_key_of_overture(record_id: str) -> str:
    """Key of an Overture row whose sources[].dataset == 'AllThePlaces' (record_id = the feature id)."""
    return atp_key(record_id)


def feature_id(props: dict, fid: str | None = None) -> str:
    """The feature's id; rebuilt from ref + spider (ATP's own rule) when a dump lacks it."""
    if fid:
        return fid
    d = hashlib.sha1(f"{props.get('ref', '')}{props.get('@spider', '')}".encode("utf8")).digest()
    return base64.urlsafe_b64encode(d).decode("ascii")


# ── HTTP with retries ────────────────────────────────────────────────────────

class _Net:
    """GET (optionally Range) with 3 tries and backoff; counts the bytes it received."""

    def __init__(self):
        self.bytes = 0

    def get(self, url: str, rng: str | None = None) -> bytes:
        last = None
        for k in range(TRIES):
            try:
                h = {"User-Agent": UA}
                if rng:
                    h["Range"] = rng
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=TIMEOUT) as r:
                    if rng and r.status != 206:
                        raise RuntimeError(f"Range ignored (HTTP {r.status})")
                    body = r.read()
                self.bytes += len(body)
                return body
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
                last = e
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404):
                    break  # no point repeating a refusal / a missing file
                if k + 1 < TRIES:
                    pause = 2 * (k + 1) ** 2
                    log(f"retry {k + 1}/{TRIES - 1} in {pause}s after {type(e).__name__}: {str(e)[:120]}")
                    time.sleep(pause)
        raise RuntimeError(f"AllThePlaces request failed: {url} {rng or ''}: {last}")


# ── a zip read through a range function ──────────────────────────────────────

def _central_directory(tail: bytes, rng: Callable[[int, int], bytes]) -> dict[str, tuple[int, int, int, int]]:
    """{name: (method, compressed size, size, local header offset)} from the file's tail (+ ranges)."""
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise RuntimeError("zip: no end-of-central-directory record")
    _, _, _, nent, _, cdsize, cdoff, _ = struct.unpack_from("<IHHHHIIH", tail, i)
    if cdoff == 0xFFFFFFFF or nent == 0xFFFF or cdsize == 0xFFFFFFFF:
        j = tail.rfind(b"PK\x06\x07", 0, i)
        if j < 0:
            raise RuntimeError("zip64: no locator")
        z64off = struct.unpack_from("<IIQI", tail, j)[2]
        rec = rng(z64off, 56)
        _, _, _, _, _, _, _, nent, cdsize, cdoff = struct.unpack_from("<IQHHIIQQQQ", rec, 0)
    cd = rng(cdoff, cdsize)
    ents: dict[str, tuple[int, int, int, int]] = {}
    p = 0
    while p + 46 <= len(cd) and struct.unpack_from("<I", cd, p)[0] == 0x02014B50:
        (_, _, _, _, comp, _, _, _, csz, usz, nl, el, cl, _, _, _, lho) = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, p)
        name = cd[p + 46:p + 46 + nl].decode("utf8", "replace")
        extra = cd[p + 46 + nl:p + 46 + nl + el]
        q = 0
        while q + 4 <= len(extra):
            tid, sz = struct.unpack_from("<HH", extra, q)
            if tid == 1:  # zip64 extended information, in the order the 32-bit fields overflowed
                r = q + 4
                if usz == 0xFFFFFFFF:
                    usz, = struct.unpack_from("<Q", extra, r)
                    r += 8
                if csz == 0xFFFFFFFF:
                    csz, = struct.unpack_from("<Q", extra, r)
                    r += 8
                if lho == 0xFFFFFFFF:
                    lho, = struct.unpack_from("<Q", extra, r)
            q += 4 + sz
        ents[name] = (comp, csz, usz, lho)
        p += 46 + nl + el + cl
    return ents


def _read_entry(ent: tuple[int, int, int, int], rng: Callable[[int, int], bytes]) -> bytes:
    comp, csz, usz, lho = ent
    blob = rng(lho, 30 + _ENTRY_SLACK + csz)  # may run past the end of the file: servers clip the range
    if blob[:4] != b"PK\x03\x04":
        raise RuntimeError("zip: bad local header")
    nl, el = struct.unpack_from("<HH", blob, 26)
    start = 30 + nl + el
    if start + csz > len(blob):
        blob = rng(lho, start + csz)
    data = blob[start:start + csz]
    if comp == 0:
        return data
    if comp != 8:
        raise RuntimeError(f"zip: unsupported method {comp}")
    d = zlib.decompressobj(-15)
    out = d.decompress(data) + d.flush()
    if usz and len(out) != usz:
        raise RuntimeError(f"zip: entry size {len(out)} != {usz}")
    return out


def _egyptian(f: dict) -> bool:
    p = f.get("properties") or {}
    g = f.get("geometry") or {}
    c = p.get("addr:country")
    if c:
        return str(c).upper() == "EG"
    co = g.get("coordinates")
    return bool(g.get("type") == "Point" and co and len(co) >= 2 and X0 <= co[0] <= X1 and Y0 <= co[1] <= Y1)


def _features(text: str) -> Iterator[dict]:
    """ATP's geojson is one Feature per line; a FeatureCollection file is read whole."""
    n = 0
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{") or '"Feature"' not in line:
            continue
        try:
            f = json.loads(line)
        except ValueError:
            continue
        if f.get("type") == "Feature":
            n += 1
            yield f
    if n == 0 and text.lstrip().startswith("{"):
        try:
            for f in json.loads(text).get("features") or []:
                yield f
        except ValueError:
            return


def egypt_spiders(insights: dict) -> dict[str, int]:
    """{spider: features in Egypt} from stats/_insights.json (data[].atp_splits.EG)."""
    out: dict[str, int] = {}
    for b in insights.get("data") or []:
        for s, c in ((b.get("atp_splits") or {}).get("EG") or {}).items():
            out[s] = out.get(s, 0) + int(c)
    return out


def _extract(spiders: list[str], ents: dict, rng: Callable[[int, int], bytes]) -> tuple[list[dict], dict[str, int], list[str]]:
    feats: list[dict] = []
    per: dict[str, int] = {}
    missing: list[str] = []
    seen: set[str] = set()
    for s in sorted(spiders):
        e = ents.get(f"output/{s}.geojson")
        if e is None:
            missing.append(s)
            continue
        text = _read_entry(e, rng).decode("utf8")
        n = 0
        for f in _features(text):
            if not _egyptian(f):
                continue
            p = f.setdefault("properties", {})
            p.setdefault("@spider", s)
            f["id"] = feature_id(p, f.get("id"))
            if f["id"] in seen:
                continue
            seen.add(f["id"])
            feats.append(f)
            n += 1
        if n:
            per[s] = n
        log(f"{s}: {n} Egyptian of {len(text.splitlines())} features")
    return feats, per, missing


def fetch_atp(data: str) -> dict:
    """Latest run → the Egyptian spiders' features → <data>/atp_eg.ndjson."""
    t0 = time.time()
    net = _Net()
    latest = json.loads(net.get(f"{BASE}/runs/latest.json"))
    run = latest["run_id"]
    url = latest.get("output_url") or f"{BASE}/runs/{run}/output.zip"
    spiders = egypt_spiders(json.loads(net.get(f"{BASE}/runs/{run}/stats/_insights.json")))
    if not spiders:
        raise RuntimeError("AllThePlaces: no Egyptian spider in stats/_insights.json")

    def rng(start: int, length: int) -> bytes:
        return net.get(url, f"bytes={start}-{start + length - 1}")

    tail = net.get(url, f"bytes=-{_TAIL}")
    ents = _central_directory(tail, rng)
    feats, per, missing = _extract(list(spiders), ents, rng)
    if not feats:
        raise RuntimeError("AllThePlaces: no Egyptian feature in the run")
    if missing:
        log("spiders listed for Egypt but absent from the zip:", ",".join(missing))
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, OUT_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        for f in feats:
            fh.write(json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    log(f"run {run}: {len(feats)} features, {len(per)} spiders, {net.bytes / 1e6:.1f} MB read in {time.time() - t0:.0f}s")
    return {"run": run, "spiders": len(per), "features": len(feats), "bytes": net.bytes, "missing": missing}


# ── adapter ──────────────────────────────────────────────────────────────────

def _txt(v) -> str | None:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v).strip()
    return s or None


def atp_places(path: str, inside) -> Iterator[R.Record]:
    """`inside(lat, lng) -> bool` = the Egypt polygon test (build.py passes it)."""
    with open(path, encoding="utf8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                f = json.loads(line)
            except ValueError:
                continue
            rec = _record(f, inside)
            if rec is not None:
                yield rec


def _record(f: dict, inside) -> R.Record | None:
    g = f.get("geometry") or {}
    co = g.get("coordinates")
    if g.get("type") != "Point" or not co or len(co) < 2:
        return None
    lng, lat = float(co[0]), float(co[1])
    p = f.get("properties") or {}
    country = _txt(p.get("addr:country"))
    if country and country.upper() != "EG":
        return None
    if not inside(lat, lng):
        return None
    name = _txt(p.get("name"))
    brand = _txt(p.get("brand")) or _txt(p.get("brand:en"))
    if not name and not brand:
        return None
    tags = {k: ("yes" if v is True else str(v)) for k, v in p.items()
            if isinstance(v, (str, int, float, bool)) and not k.startswith("@")}
    cat = T.osm_cat(tags) or "place"
    nm: list[tuple[str, str]] = [(name or brand, "primary")]
    if name:
        ar, la = R.split_scripts(name)
        if ar and la:
            nm += [(ar, "ar"), (la, "en")]
    for key, role in (("name:ar", "ar"), ("name:en", "en")):
        v = _txt(p.get(key))
        if v and (v, role) not in nm:
            nm.append((v, role))
    if brand and name and brand.casefold() != name.casefold():
        nm.append((brand, "brand"))
    addr = _txt(p.get("addr:street_address")) or _txt(p.get("addr:full"))
    street = _txt(p.get("addr:street"))
    if not addr and street:
        addr = " ".join(x for x in (_txt(p.get("addr:housenumber")), street) if x)
    sid = feature_id(p, f.get("id"))
    return R.Record(
        src=R.SRC_ATP, sid=sid, kind="poi", cat=cat, lat=lat, lng=lng, names=nm,
        brand=brand, brand_wd=_txt(p.get("brand:wikidata")), conf=0.9,
        phone=R.clean_phone(_txt(p.get("phone"))), website=R.clean_url(_txt(p.get("website"))),
        social=_txt(p.get("contact:facebook")) or _txt(p.get("facebook")),
        hours=_txt(p.get("opening_hours")), addr=addr, street=street, wd=_txt(p.get("wikidata")),
        extra={"atp_ref": _txt(p.get("ref")), "spider": _txt(p.get("@spider")), "atp_key": atp_key(sid)},
    )


# ── self-test (no network) ───────────────────────────────────────────────────

def _selftest() -> None:
    import io
    import zipfile

    feats = [
        {"type": "Feature", "id": "tzpO-NbX40EW7nk6FIGjAsOGvOk=",
         "properties": {"ref": "Chillout-Elobour", "@spider": "mcdonalds_eg", "addr:country": "EG", "addr:city": "Obour City",
                        "addr:street_address": "ChillOut Gas Station, Obour City Entrance", "brand": "McDonald's",
                        "brand:wikidata": "Q38076", "amenity": "fast_food", "name": "McDonald's | ماكدونالدز",
                        "phone": "+20 2 1234 5678", "website": "mcdonalds.eg", "opening_hours": "24/7"},
         "geometry": {"type": "Point", "coordinates": [31.4727153, 30.1760969]}},
        {"type": "Feature", "id": "AAAAAAAAAAAAAAAAAAAAAAAAAAA=",
         "properties": {"ref": "a1", "@spider": "banque_misr_eg", "addr:country": "EG", "brand": "Banque Misr", "amenity": "atm"},
         "geometry": {"type": "Point", "coordinates": [31.2, 30.0]}},
    ]
    other = {"type": "Feature", "properties": {"ref": "x", "@spider": "mcdonalds_eg", "addr:country": "IL", "name": "McD"},
             "geometry": {"type": "Point", "coordinates": [34.8, 32.0]}}
    nameless = {"type": "Feature", "properties": {"ref": "y", "@spider": "mcdonalds_eg", "amenity": "atm"},
                "geometry": {"type": "Point", "coordinates": [31.3, 30.1]}}
    # the key rule: id = urlsafe-b64(sha1(ref + spider))
    assert feature_id({"ref": "Chillout-Elobour", "@spider": "mcdonalds_eg"}) == feats[0]["id"]
    assert atp_key_of_overture("tzpO+NbX40EW7nk6FIGjAsOGvOk=") == atp_key("tzpO-NbX40EW7nk6FIGjAsOGvOk=") == "tzpO-NbX40EW7nk6FIGjAsOGvOk"
    # the zip path: a deflated + a stored entry read back through an in-memory range function
    body = "\n".join(json.dumps(x) for x in feats + [other, nameless]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("output/", b"")
        z.writestr("output/mcdonalds_eg.geojson", body, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("output/other.geojson", "{}\n", compress_type=zipfile.ZIP_STORED)
    blob = buf.getvalue()
    rng = lambda s, n: blob[s:s + n]
    ents = _central_directory(blob[-_TAIL:], rng)
    got, per, missing = _extract(["mcdonalds_eg", "other", "nope"], ents, rng)
    assert per == {"mcdonalds_eg": 3} and missing == ["nope"], (per, missing)  # IL dropped, the nameless ATM kept for the adapter
    assert egypt_spiders({"data": [{"atp_splits": {"EG": {"a": 2}, "US": {"b": 9}}}, {"atp_splits": {"EG": {"a": 1, "c": 5}}}]}) == {"a": 3, "c": 5}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, OUT_NAME)
        with open(path, "w", encoding="utf8") as fh:
            for x in got:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            fh.write(json.dumps(other) + "\n")
        recs = list(atp_places(path, lambda la, ln: True))
    assert len(recs) == 2, recs  # the nameless-brandless ATM and the Israeli row are skipped
    a, b = recs
    assert a.src == "atp" and a.sid == feats[0]["id"] and a.cat == T.osm_cat({"amenity": "fast_food"}), a.cat
    assert a.brand == "McDonald's" and a.brand_wd == "Q38076" and a.conf == 0.9 and a.hours == "24/7"
    assert a.phone == "+20212345678" and a.website == "https://mcdonalds.eg", (a.phone, a.website)
    roles = {r for _, r in a.names}
    assert {"primary", "ar", "en"} <= roles, a.names
    assert a.extra == {"atp_ref": "Chillout-Elobour", "spider": "mcdonalds_eg", "atp_key": "tzpO-NbX40EW7nk6FIGjAsOGvOk"}, a.extra
    assert a.addr.startswith("ChillOut")
    assert b.names == [("Banque Misr", "primary")] and b.cat == T.osm_cat({"amenity": "atm"}), (b.names, b.cat)
    print("atp selftest OK")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", help="data directory (writes atp_eg.ndjson)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        _selftest()
        return 0
    if not a.data:
        ap.error("--data or --selftest")
    print(json.dumps(fetch_atp(a.data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
