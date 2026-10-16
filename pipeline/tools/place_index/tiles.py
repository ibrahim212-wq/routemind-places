"""The static files the phone downloads: SQLite tiles + one national file + a manifest.

PARTITION — an adaptive quadtree over Egypt: a square is split until it holds at most
TILE_CAPACITY places (POIs + street pieces) or reaches MIN_TILE_DEG. Dense Cairo gets small
tiles, the Western Desert one big one, so every tile costs about the same to download.

NATIONAL — `national.sqlite`: every area (governorate → hamlet), every place prominent enough to
be searched from anywhere (popularity ≥ NATIONAL_POP or a class like airport / hospital /
university / mall / museum / ministry), and every branch of a chain (brand key) so «العزبي» finds
the nearest branch from Aswan. Same schema as a tile.

SCHEMA (version SCHEMA_VERSION) — one file layout for both:

  meta(k, v)                       schema, tile, bbox, built, norm, license, sources
  place(id, pid, kind, cat, scat, lat, lng, name_ar, name_en, alt, addr, area, gov,
        phone, website, social, hours, brand, conf, pop, srcs, ext, grp)
  area(id, ar, en)                 the neighbourhood / city names `place.area` points at (subtitles)
  tok(t, id, f)  WITHOUT ROWID     the inverted index, PRIMARY KEY (t, id); f = flags below
  vocab(t, n)    WITHOUT ROWID     every distinct token (skeletons too) + its document frequency:
                                   IDF, the selectivity that picks the driving word, prefix and typo search
  category(id, ar, en, scat)       national only: display labels

TOKEN FORMS (what `tok.t` holds; engine.py builds the same forms from the query)
  word          normalized word                                   form 0
  stem          the word without article / attached preposition   form 1
  "~" + skel    consonant skeleton (cross-script, Franco)          form 3
  joined pair   two adjacent short words written together         form 4  («بي تك» → «بيتك»)
FLAGS f = field | form << 2 | first << 5
  field 0 = a name, 1 = an alternative name / brand, 2 = the address line
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import sqlite3
from collections import defaultdict

from . import merge as M
from . import records as R
from . import taxonomy as T
from . import textnorm as tn

SCHEMA_VERSION = 1
TILE_CAPACITY = 7000
MIN_TILE_DEG = 0.01
ROOT = (24.0, 21.0, 13.0)  # min lng, min lat, size (deg) — covers Egypt's box

F_NAME, F_ALT, F_ADDR = 0, 1, 2
FORM_WORD, FORM_STEM, FORM_LOOSE, FORM_SKEL, FORM_JOIN = 0, 1, 2, 3, 4
FIRST = 1 << 5
KIND = {"poi": 0, "area": 1, "street": 2}

NATIONAL_POP = 0.66
NATIONAL_CAT_POP = 0.5
NATIONAL_CATS = {"airport", "hospital", "university", "college", "mall", "hypermarket", "museum", "historic_site",
                 "attraction", "stadium", "ministry", "embassy", "train_station", "metro_station", "lrt_station",
                 "monorail_station", "bus_station", "port", "zoo", "amusement_park", "resort", "beach", "courthouse",
                 "traffic_department", "civil_registry", "townhall", "monastery", "sports_club", "theater",
                 "cultural_center", "square", "compound", "industrial_zone", "island", "mountain", "lake", "toll_gate"}


def flags(field: int, form: int, first: bool) -> int:
    return field | (form << 2) | (FIRST if first else 0)


def _add(out: dict, t: str, f: int) -> None:
    if not t:
        return
    old = out.get(t)
    # keep the best evidence: lower field, then lower form, then first-word
    if old is None or (old & 3, (old >> 2) & 7, -(old & FIRST)) > (f & 3, (f >> 2) & 7, -(f & FIRST)):
        out[t] = f


def text_tokens(text: str, field: int, out: dict, variants: bool = True) -> None:
    toks = [t for t in tn.tokens(text) if not tn.is_stopword(t)]
    for i, t in enumerate(toks):
        first = i == 0
        _add(out, t, flags(field, FORM_WORD, first))
        if not variants:
            continue
        st = tn.stems(t)
        for s in st[1:]:
            _add(out, s, flags(field, FORM_STEM, first))
        for sk in tn.skeletons(t)[:2]:
            if len(sk) >= 2 and not sk.isdigit():
                _add(out, "~" + sk, flags(field, FORM_SKEL, first))
    if variants:
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            if len(a) + len(b) <= 12 and tn.is_arabic_token(a) == tn.is_arabic_token(b):
                j = a + b
                _add(out, j, flags(field, FORM_JOIN, i == 0))
                for s in tn.stems(j)[1:]:
                    _add(out, s, flags(field, FORM_JOIN, i == 0))


def place_tokens(p: M.Place) -> dict[str, int]:
    out: dict[str, int] = {}
    for n in (p.name_ar, p.name_en):
        if n:
            text_tokens(n, F_NAME, out)
    for n in p.alt:
        text_tokens(n, F_ALT, out)
    # the address line is NOT indexed (it was a third of every tile's index): a query that names a
    # street finds the street itself, and a category / name candidate is scored on its address
    # in memory (engine.word_match, field 2)
    return out


# ── partition ────────────────────────────────────────────────────────────────

def partition(places: list[M.Place]) -> dict[str, tuple[tuple[float, float, float, float], list[M.Place]]]:
    """tile id → (bbox (minLng, minLat, maxLng, maxLat), places)."""
    out = {}

    def rec(tid, x0, y0, size, items):
        if len(items) <= TILE_CAPACITY or size / 2 < MIN_TILE_DEG:
            if items:
                out[tid] = ((x0, y0, x0 + size, y0 + size), items)
            return
        h = size / 2
        quads = {0: [], 1: [], 2: [], 3: []}
        for p in items:
            q = (1 if p.lng >= x0 + h else 0) + (2 if p.lat >= y0 + h else 0)
            quads[q].append(p)
        for q, sub in quads.items():
            rec(tid + str(q), x0 + (h if q & 1 else 0), y0 + (h if q & 2 else 0), h, sub)

    rec("t", ROOT[0], ROOT[1], ROOT[2], places)
    return out


def is_national(p: M.Place) -> bool:
    if p.kind == "area":
        return True
    if p.kind == "street":
        return p.cat in ("highway", "axis") or (p.cat == "bridge" and p.pop >= 0.55)
    if p.brand_key and not p.brand_key.startswith("auto:"):
        return True  # every branch of a lexicon chain: «العزبي» from Aswan finds the nearest one
    if p.cat in NATIONAL_CATS:
        return p.pop >= NATIONAL_CAT_POP and p.conf >= 0.6
    return p.pop >= NATIONAL_POP


# ── writer ───────────────────────────────────────────────────────────────────

DDL = """
PRAGMA page_size = 4096;
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;
CREATE TABLE place(
  id INTEGER PRIMARY KEY, pid TEXT NOT NULL, kind INTEGER NOT NULL, cat TEXT NOT NULL, scat TEXT,
  lat REAL NOT NULL, lng REAL NOT NULL, name_ar TEXT, name_en TEXT, alt TEXT, addr TEXT,
  area INTEGER, gov TEXT, phone TEXT, website TEXT, social TEXT, hours TEXT,
  brand TEXT, conf REAL NOT NULL, pop REAL NOT NULL, srcs INTEGER NOT NULL, ext INTEGER NOT NULL, grp TEXT);
CREATE TABLE tok(t TEXT NOT NULL, id INTEGER NOT NULL, f INTEGER NOT NULL, PRIMARY KEY (t, id)) WITHOUT ROWID;
CREATE TABLE vocab(t TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID;
CREATE TABLE category(id TEXT PRIMARY KEY, ar TEXT NOT NULL, en TEXT NOT NULL, scat TEXT) WITHOUT ROWID;
CREATE TABLE area(id INTEGER PRIMARY KEY, ar TEXT, en TEXT);
CREATE TABLE media(id INTEGER PRIMARY KEY, wd TEXT, img TEXT, img_by TEXT, img_lic TEXT, img_lic_url TEXT);
"""
POST = """
CREATE INDEX place_scat ON place(scat, lat, lng) WHERE scat IS NOT NULL;
CREATE INDEX place_brand ON place(brand) WHERE brand IS NOT NULL;
"""


def compact_web(url: str | None) -> str | None:
    """Websites without scheme / www (the app adds https://)."""
    if not url:
        return None
    u = url.strip()
    for pre in ("https://", "http://"):
        if u.lower().startswith(pre):
            u = u[len(pre):]
    if u.lower().startswith("www."):
        u = u[4:]
    return u.rstrip("/") or None


SOCIAL_PREFIX = (("facebook.com/", "fb:"), ("fb.com/", "fb:"), ("m.facebook.com/", "fb:"), ("instagram.com/", "ig:"))


def compact_social(url: str | None) -> str | None:
    """fb:<page> / ig:<account>, anything else as a bare host/path."""
    u = compact_web(url)
    if not u:
        return None
    low = u.lower()
    for host, pre in SOCIAL_PREFIX:
        if low.startswith(host):
            rest = u[len(host):].split("?")[0].strip("/")
            return pre + rest if rest else None
    return u


# pid → media.Media (the place's Wikidata item and a credited Commons photo); set by build.py before the tiles.
# The engine never reads `media`: the phone reads it for the sheet (PlaceStore.byPid).
_MEDIA: dict = {}


def set_media(media: dict) -> None:
    _MEDIA.clear()
    _MEDIA.update(media)


def write_db(path: str, tile_id: str, bbox, places: list[M.Place], meta: dict, with_categories: bool) -> int:
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(DDL)
    rows, toks, media = [], [], []
    df: dict[str, int] = defaultdict(int)
    areas: dict[tuple, int] = {}
    for i, p in enumerate(sorted(places, key=lambda q: (round(q.lat, 2), q.lng)), start=1):
        c = T.BY_ID.get(p.cat)
        scat = c.scat if c else None
        area = None
        if p.area_ar or p.area_en:
            area = areas.setdefault((p.area_ar, p.area_en), len(areas) + 1)
        rows.append((i, p.pid, KIND[p.kind], p.cat, scat, p.lat, p.lng, p.name_ar, p.name_en,
                     "\x1f".join(p.alt) if p.alt else None, p.addr, area, p.gov, p.phone,
                     compact_web(p.website), compact_social(p.social), p.hours, p.brand_key, round(p.conf, 3),
                     round(p.pop, 3), p.srcs, int(min(p.extent_m, 2_000_000)), p.grp))
        for t, f in place_tokens(p).items():
            toks.append((t, i, f))
            df[t] += 1
        md = _MEDIA.get(p.pid)
        if md is not None:
            media.append((i, md.wd, md.img, md.by, md.lic, md.lic_url))
    con.executemany("INSERT INTO place VALUES (" + ",".join("?" * 23) + ")", rows)
    con.executemany("INSERT INTO area VALUES (?,?,?)", [(i, ar, en) for (ar, en), i in areas.items()])
    con.executemany("INSERT INTO media VALUES (?,?,?,?,?,?)", media)
    toks.sort()
    con.executemany("INSERT INTO tok VALUES (?,?,?)", toks)
    con.executemany("INSERT INTO vocab VALUES (?,?)", sorted(df.items()))
    if with_categories:
        con.executemany("INSERT INTO category VALUES (?,?,?,?)", [(c.id, c.ar, c.en, c.scat) for c in T.CATS])
    m = dict(meta)
    m.update({"schema": str(SCHEMA_VERSION), "tile": tile_id, "bbox": json.dumps([round(x, 5) for x in bbox]),
              "places": str(len(rows)), "norm": str(tn.NORM_VERSION)})
    con.executemany("INSERT INTO meta VALUES (?,?)", sorted(m.items()))
    con.executescript(POST)
    con.commit()
    con.execute("VACUUM")
    con.close()
    return len(rows)


def gzip_file(src: str, dst: str) -> tuple[int, str]:
    with open(src, "rb") as f:
        data = f.read()
    gz = gzip.compress(data, compresslevel=9, mtime=0)
    with open(dst, "wb") as f:
        f.write(gz)
    return len(gz), hashlib.sha256(gz).hexdigest()


def build_tiles(places: list[M.Place], out_dir: str, meta: dict, keep_raw: bool = True) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    national = [p for p in places if is_national(p)]
    local = [p for p in places if p.kind != "area"]
    parts = partition(local)
    manifest = {"schema": SCHEMA_VERSION, "norm": tn.NORM_VERSION, "version": meta.get("version"),
                "built": meta.get("built"), "license": "ODbL-1.0", "tiles": []}
    raw_total = gz_total = 0

    def emit(tid, bbox, items, with_cats):
        nonlocal raw_total, gz_total
        raw = os.path.join(out_dir, f"{tid}.sqlite")
        n = write_db(raw, tid, bbox, items, meta, with_cats)
        size = os.path.getsize(raw)
        gz, sha = gzip_file(raw, raw + ".gz")
        raw_total += size
        gz_total += gz
        if not keep_raw:
            os.remove(raw)
        return {"id": tid, "bbox": [round(x, 5) for x in bbox], "file": f"{tid}.sqlite.gz", "bytes": gz,
                "raw_bytes": size, "sha256": sha, "places": n}

    nat_bbox = (R.EG_BBOX[0], R.EG_BBOX[1], R.EG_BBOX[2], R.EG_BBOX[3])
    manifest["national"] = emit("national", nat_bbox, national, True)
    for tid, (bbox, items) in sorted(parts.items()):
        manifest["tiles"].append(emit(tid, bbox, items, False))
    manifest["totals"] = {"files": 1 + len(manifest["tiles"]), "bytes": gz_total, "raw_bytes": raw_total,
                          "places": len(places)}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest
