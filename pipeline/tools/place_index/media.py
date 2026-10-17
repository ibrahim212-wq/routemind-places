"""Freely licensed photos for places (docs/place-photos-2026-10.md; first version docs/place-ugc-2026-10.md §4).

A place gets up to MAX_PHOTOS photos, best first, each with the credit its licence asks for:
  1. osm   — OSM's `wikimedia_commons=File:…` / an `image=` naming a Commons file on a merged member;
  2. p18   — Wikidata's P18 (image) of the place's item (OSM `wikidata=` or the Wikidata source);
  3. wiki  — the lead image of the item's Wikipedia article (PageImages) — MEASURED AND OFF: 0.68 precision on
             the 2026-10-17 sample even after the filters (logos, portraits, finds); WIKI_LEAD_IMAGES = the switch;
  4. name  — a geotagged Commons file whose title names the place, taken beside it (photos.match_commons_geo);
  5. cat   — files of the item's Commons category (P373): the gallery of a landmark;
  6. street — a Panoramax street-level picture looking at the place (photos.match_street).
A chain branch also gets its brand's LOGO (P154 of the brand's item: Overture's `brand.wikidata`, OSM's
`brand:wikidata`) when Commons states it is public domain / CC0 — an identity mark, never shown as a photo.

Every Commons file is looked up for what its licence requires us to show — the author (`Artist`) and the
licence (`LicenseShortName`, `LicenseUrl`). A file whose licence or author Commons does not state is
dropped: no photo without its credit. Nothing is downloaded: the phone shows Commons' own thumbnails at
its standard widths, and Panoramax's own derivates.

    collect(places, osm_commons, brand_wd=…, deadline=…) → {pid: Media}

Network: SPARQL (POSTed — a GET of 400 ids was a 431 on every batch of the 2026-10-16 build, two hours of
retries and no P18 at all), the Commons API (50 titles a call), PageImages (50 titles a call), Panoramax's
open search. Any failure leaves those photos out — never the build; a time budget bounds the whole stage.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

from . import fetch as F
from . import photos as PH
from . import records as R

FREE = re.compile(r"^(cc[ -]?by|cc0|cc[ -]?zero|public domain|pd|gfdl|attribution|copyrighted free use|fal|ogl)", re.I)
NO_CREDIT = re.compile(r"^(cc0|cc[ -]?zero|public domain|pd)", re.I)   # a logo is shown only when nobody must be credited
MAX_PHOTOS = 8
CATEGORY_FILES = 6
STAGE_BUDGET_S = 3000
WIKI_LEAD_IMAGES = False   # measured 0.68 precision (doc §5) — a wrong photo is worse than none
UA = PH.UA


@dataclass
class Photo:
    src: str                    # commons | panoramax
    ref: str                    # Commons file name (no «File:») | panoramax host/uuid
    how: str                    # osm | p18 | wiki | name | cat | street
    by: str | None = None
    lic: str | None = None
    lic_url: str | None = None
    at: str | None = None       # capture date (street level)
    fx: float | None = None     # where the place is across the frame, 0..1 (street level)


@dataclass
class Media:
    wd: str | None
    img: str | None = None      # legacy columns: the first Commons photo (app builds before 2026-10-17 read these)
    by: str | None = None
    lic: str | None = None
    lic_url: str | None = None
    logo: str | None = None     # the brand's Commons logo (public domain / CC0 only)
    photos: list[Photo] = field(default_factory=list)


def log(*a):
    print("[media]", *a, flush=True)


def _get_json(url: str, accept: str = "application/json") -> dict:
    def once():
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    return F._retry(url[:60], once, tries=3)


def _post_sparql(query: str) -> dict:
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()

    def once():
        req = urllib.request.Request("https://query.wikidata.org/sparql", data=body, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    return F._retry("sparql", once, tries=3)


def file_name(v: str | None) -> str | None:
    """«File:Al-Azhar 2.jpg», a Commons URL or Special:FilePath URL → «Al-Azhar 2.jpg»."""
    if not v:
        return None
    v = v.strip()
    m = re.search(r"(?:commons\.wikimedia\.org/wiki/(?:Special:FilePath/|File:)|^File:)(.+)$", v, re.I)
    if not m:
        return None
    name = urllib.parse.unquote(m.group(1)).replace("_", " ").split("?")[0].strip()
    return name if re.search(r"\.(jpe?g|png|webp|tiff?|gif)$", name, re.I) else None


def _logo_name(v: str | None) -> str | None:
    """A logo may be an SVG (the phone gets a PNG rendering at a standard width)."""
    if not v:
        return None
    m = re.search(r"(?:Special:FilePath/|File:)(.+)$", v.strip(), re.I)
    if not m:
        return None
    name = urllib.parse.unquote(m.group(1)).replace("_", " ").split("?")[0].strip()
    return name if re.search(r"\.(svg|png|jpe?g|webp)$", name, re.I) else None


# ── Wikidata ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    p18: list[str] = field(default_factory=list)
    cat: str | None = None
    logo: str | None = None
    ar: str | None = None
    en: str | None = None


_Q = """SELECT ?item ?img ?cat ?logo ?ar ?en WHERE { VALUES ?item { %s }
 OPTIONAL { ?item wdt:P18 ?img } OPTIONAL { ?item wdt:P373 ?cat } OPTIONAL { ?item wdt:P154 ?logo }
 OPTIONAL { ?ar schema:about ?item ; schema:isPartOf <https://ar.wikipedia.org/> }
 OPTIONAL { ?en schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> } }"""


def items(qids: list[str], deadline: float, batch: int = 250, workers: int = 3) -> dict[str, Item]:
    """P18 / P373 / P154 / the ar + en articles of every item, `workers` queries at a time (the query
    service allows a few per client; one at a time took ~10 s a batch on 2026-10-17)."""
    from concurrent.futures import ThreadPoolExecutor
    out: dict[str, Item] = {}
    chunks = []
    for i in range(0, len(qids), batch):
        chunk = [q for q in qids[i:i + batch] if re.fullmatch(r"Q\d+", q)]
        if chunk:
            chunks.append(chunk)

    def one(chunk):
        if time.time() > deadline:
            return None
        try:
            return _post_sparql(_Q % " ".join("wd:" + q for q in chunk))
        except (OSError, ValueError) as e:
            log("wikidata batch skipped:", str(e)[:120])
            return None

    skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(one, chunks):
            if res is None:
                skipped += 1
                continue
            for b in res["results"]["bindings"]:
                q = b["item"]["value"].rsplit("/", 1)[-1]
                it = out.setdefault(q, Item())
                if "img" in b:
                    f = file_name(b["img"]["value"])
                    if f and f not in it.p18:
                        it.p18.append(f)
                if "cat" in b and not it.cat:
                    it.cat = b["cat"]["value"]
                if "logo" in b and not it.logo:
                    it.logo = _logo_name(b["logo"]["value"])
                for k in ("ar", "en"):
                    if k in b and not getattr(it, k):
                        setattr(it, k, urllib.parse.unquote(b[k]["value"].rsplit("/wiki/", 1)[-1]).replace("_", " "))
    if skipped:
        log(f"wikidata: {skipped} of {len(chunks)} batches skipped (time budget or errors)")
    return out


def page_images(titles: list[str], wiki: str, deadline: float) -> dict[str, str]:
    """Article title → its lead image file, FREE images only (`pilicense=free`)."""
    out = {}
    for i in range(0, len(titles), 50):
        if time.time() > deadline:
            break
        chunk = titles[i:i + 50]
        url = (f"https://{wiki}.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages&piprop=name"
               "&pilicense=free&redirects=1&maxlag=5&titles=" + urllib.parse.quote("|".join(chunk)))
        try:
            res = _get_json(url)
        except (OSError, ValueError) as e:
            log("pageimages batch skipped:", str(e)[:120])
            continue
        q = res.get("query", {})
        back = {}
        for n in q.get("normalized", []) + q.get("redirects", []):
            back[n["to"]] = back.get(n["from"], n["from"])
        for page in q.get("pages", {}).values():
            img = page.get("pageimage")
            if not img:
                continue
            name = file_name("File:" + img.replace("_", " "))
            if name:
                out[back.get(page.get("title", ""), page.get("title", ""))] = name
        time.sleep(0.2)
    return out


def category_files(cats: list[str], deadline: float, per: int = CATEGORY_FILES) -> dict[str, list[str]]:
    """Commons category → its first photo files (no subcategories)."""
    out = {}
    for c in cats:
        if time.time() > deadline:
            log("categories: time budget spent")
            break
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&list=categorymembers&cmtype=file"
               "&cmlimit=30&maxlag=5&cmtitle=" + urllib.parse.quote("Category:" + c))
        try:
            res = _get_json(url)
        except (OSError, ValueError):
            continue
        fs = []
        for m in res.get("query", {}).get("categorymembers", []):
            t = m.get("title", "")
            name = t[5:] if t.startswith("File:") else t
            if PH.PHOTO_EXT.search(name) and not PH.NOT_A_PHOTO.search(name):
                fs.append(name)
            if len(fs) >= per:
                break
        if fs:
            out[c] = fs
        time.sleep(0.1)
    return out


# ── Commons credits ──────────────────────────────────────────────────────────────────────────────

def _plain(v: str | None) -> str | None:
    if not v:
        return None
    t = re.sub(r"<[^>]+>", "", html.unescape(v))
    t = re.sub(r"\s+", " ", t).strip()
    m = re.fullmatch(r"(.+?)\s*\1", t)          # «Unknown authorUnknown author» (Commons' HTML says it twice)
    if m:
        t = m.group(1).strip()
    return t[:120] or None


# a file Commons files under plans, maps, drawings, museum objects, scans, logos, portraits… is not a photo of the
# place, whatever links to it (a tomb's P18 is often its floor plan; a category holds its finds and its book plates —
# the 2026-10-17 samples, docs/place-photos-2026-10.md §5: no photo judged right was lost to it)
NOT_A_PHOTO_CAT = re.compile(r"(^|\|)[^|]*\b(plans?|floor plans?|maps?|diagrams?|drawings?|line drawings|coats? of arms|"
                             r"flags?|coins?|stamps?|banknotes?|charts?|postcards?|engravings?|lithographs?|"
                             r"skeletons?|fossils?|manuscripts?|documents?|antiquities|accession numbers?|museum objects?|"
                             r"logos?|textlogo|portraits? of|men of|women of|recipients of|egyptology texts|denkm[aä]ler|"
                             r"lepsius|derivative works|scanned with|pd-scan|scans? from|scans|illustrations of|"
                             r"images from (the )?(metropolitan|new york public|internet archive|travelers|rawpixel)|"
                             r"uncategorized media|reliefs? (of|from|in)|papyr[iu]|3d|computer[- ]generated|"
                             r"renders?|renderings?|reconstructions?)\b", re.I)


def credits(files: list[str], deadline: float | None = None, photos_only: bool = True
            ) -> dict[str, tuple[str | None, str, str | None]]:
    """file → (author, licence, licence URL) for files Commons states a free licence for (author may be None
    only for a public-domain / CC0 file — a photo still needs one, see `collect`). With `photos_only`, a
    file in a plan / map / drawing category is left out."""
    out = {}
    for i in range(0, len(files), 50):
        if deadline and time.time() > deadline:
            log("credits: time budget spent at", i, "of", len(files))
            break
        chunk = files[i:i + 50]
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=extmetadata"
               "&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|Credit|Categories&maxlag=5&titles="
               + urllib.parse.quote("|".join("File:" + f for f in chunk)))
        try:
            res = _get_json(url)
        except (OSError, ValueError) as e:
            log("Commons batch skipped:", str(e)[:120])
            continue
        norm = {n["to"]: n["from"] for n in res.get("query", {}).get("normalized", [])}
        for page in res.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
            lic = _plain(info.get("LicenseShortName", {}).get("value"))
            who = _plain(info.get("Artist", {}).get("value")) or _plain(info.get("Credit", {}).get("value"))
            if not lic or not FREE.match(lic):
                continue
            if photos_only and NOT_A_PHOTO_CAT.search(info.get("Categories", {}).get("value") or ""):
                continue
            title = norm.get(page.get("title", ""), page.get("title", ""))
            name = title[5:] if title.startswith("File:") else title
            lurl = info.get("LicenseUrl", {}).get("value")
            out[name] = (who, lic, lurl if lurl and lurl.startswith("http") else None)
        time.sleep(0.3)
    return out


# ── the stage ────────────────────────────────────────────────────────────────────────────────────

def _cells(places, deg: float, min_n: int) -> list[tuple[float, float, float, float]]:
    n = defaultdict(int)
    for p in places:
        n[(int(p.lat // deg), int(p.lng // deg))] += 1
    return [(i * deg, j * deg, (i + 1) * deg, (j + 1) * deg) for (i, j), k in sorted(n.items()) if k >= min_n]


def collect(places, osm_commons: dict[str, str], brand_wd: dict[str, str] | None = None, others=(),
            budget_s: float = STAGE_BUDGET_S, geo: bool = True, street: bool = True) -> dict[str, Media]:
    """`osm_commons`: pid → a Commons file named by OSM on one of its members; `brand_wd`: pid → the
    brand's Wikidata item. `places` are POIs and areas (pid, kind, cat, lat, lng, names, extent_m, wd);
    `others` (the street pieces) only compete for Commons titles (photos.match_commons_geo)."""
    t0 = time.time()
    deadline = t0 + budget_s
    brand_wd = brand_wd or {}
    by_pid = {p.pid: p for p in places}
    found: dict[str, list[Photo]] = defaultdict(list)
    stats = defaultdict(int)

    def add(pid: str, ph: Photo):
        if ph.src == "commons" and PH.NOT_A_PHOTO.search(ph.ref):
            return
        lst = found[pid]
        if len(lst) < MAX_PHOTOS and all(x.ref != ph.ref for x in lst):
            lst.append(ph)
            stats[ph.how] += 1

    for pid, f in sorted(osm_commons.items()):
        if pid in by_pid:
            add(pid, Photo("commons", f, "osm"))

    qids = sorted({p.wd for p in places if p.wd} | set(brand_wd.values()))
    it = items(qids, t0 + budget_s * 0.25)
    log(f"wikidata: {len(it)} of {len(qids)} items answered ({time.time() - t0:.0f}s)")

    for p in places:
        x = it.get(p.wd) if p.wd else None
        if x:
            for f in x.p18:
                add(p.pid, Photo("commons", f, "p18"))
    # the lead image of the article, for an item without P18
    want = defaultdict(list)
    for p in places:
        x = it.get(p.wd) if p.wd else None
        if x and not found.get(p.pid):
            for wiki in ("en", "ar"):
                if getattr(x, wiki):
                    want[wiki].append((getattr(x, wiki), p.pid))
    for wiki, pairs in (want.items() if WIKI_LEAD_IMAGES else ()):
        got = page_images(sorted({t for t, _ in pairs}), wiki, t0 + budget_s * 0.35)
        for t, pid in pairs:
            if t in got:
                add(pid, Photo("commons", got[t], "wiki"))
    log(f"p18 + wiki: {stats['p18']} + {stats['wiki']} ({time.time() - t0:.0f}s)")

    pois = [p for p in places if p.kind == "poi"]
    if geo:
        cells = _cells(pois, 0.08, 5)
        files = PH.commons_geo(cells, t0 + budget_s * 0.6)
        areas = [p for p in places if p.kind == "area"]
        for pid, fs in PH.match_commons_geo(pois, files, others=list(others) + areas).items():
            for f, _d, _n in fs:
                add(pid, Photo("commons", f, "name"))
        log(f"commons by name: {stats['name']} photos ({time.time() - t0:.0f}s)")

    # a landmark's gallery: its Commons category (POIs only — a city's category is everything in it)
    cats = defaultdict(list)
    pop = defaultdict(float)
    for p in pois:
        x = it.get(p.wd) if p.wd else None
        if x and x.cat and len(found.get(p.pid, ())) < MAX_PHOTOS:
            cats[x.cat].append(p.pid)
            pop[x.cat] = max(pop[x.cat], p.pop or 0.0)
    # the most searched landmarks first: the budget may end the list
    got = category_files(sorted(cats, key=lambda c: (-pop[c], c)), t0 + budget_s * 0.75)
    for c, fs in got.items():
        for pid in cats[c]:
            for f in fs:
                add(pid, Photo("commons", f, "cat"))
    log(f"categories: {stats['cat']} photos from {len(got)} of {len(cats)} ({time.time() - t0:.0f}s)")

    if street:
        imgs = PH.panoramax((R.EG_BBOX[0], R.EG_BBOX[1], R.EG_BBOX[2], R.EG_BBOX[3]), t0 + budget_s * 0.8)
        for pid, ms in PH.match_street(pois, imgs).items():
            for im, _d, fx in ms:
                add(pid, Photo(im.src, im.ref, "street", by=im.by, lic=im.lic, at=im.at, fx=round(fx, 3)))
        log(f"street level: {stats['street']} photos ({time.time() - t0:.0f}s)")

    logos = {q: it[q].logo for q in set(brand_wd.values()) if q in it and it[q].logo}
    files = sorted({ph.ref for lst in found.values() for ph in lst if ph.src == "commons"} | set(logos.values()))
    end = max(deadline, time.time() + 600)                  # the credits always run: a photo needs one
    cr = credits(sorted({ph.ref for lst in found.values() for ph in lst if ph.src == "commons"}), end)
    cr.update({k: v for k, v in credits(sorted(set(logos.values())), end, photos_only=False).items() if k not in cr})
    media: dict[str, Media] = {}
    kept = defaultdict(int)
    for p in places:
        lst = []
        for ph in found.get(p.pid, ()):
            if ph.src == "commons":
                c = cr.get(ph.ref)
                if not c or not c[0]:
                    continue  # no stated licence / author → no photo
                ph.by, ph.lic, ph.lic_url = c
            elif not ph.lic:
                continue
            lst.append(ph)
            kept[ph.how] += 1
        logo = None
        q = brand_wd.get(p.pid)
        if q and q in logos:
            c = cr.get(logos[q])
            if c and NO_CREDIT.match(c[1]):
                logo = logos[q]
        if not (p.wd or lst or logo):
            continue
        m = Media(wd=p.wd, logo=logo, photos=lst)
        first = next((x for x in lst if x.src == "commons"), None)
        if first:
            m.img, m.by, m.lic, m.lic_url = first.ref, first.by, first.lic, first.lic_url
        media[p.pid] = m
    with_photo = sum(1 for m in media.values() if m.photos)
    log(f"{len(media)} places with media: {with_photo} with a photo ({dict(kept)}), "
        f"{sum(1 for m in media.values() if m.logo)} with a brand logo; {len(files)} Commons files, "
        f"{len(cr)} credited ({time.time() - t0:.0f}s)")
    return media
