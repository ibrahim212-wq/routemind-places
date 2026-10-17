"""Photos of places beyond Wikidata (docs/place-photos-2026-10.md §3–§4): Wikimedia Commons' geotagged files
matched BY NAME, and street-level imagery (Panoramax) matched BY GEOMETRY.

    commons_geo(cells, deadline)            → [GeoFile]   every geotagged Commons file in the cells
    match_commons_geo(places, files)        → {pid: [(file, metres, tokens)]}
    panoramax(bbox, deadline)               → [StreetImage]
    match_street(places, images)            → {pid: [(StreetImage, metres, fx)]}

NOT Mapillary: its Terms (§5, 2024-02-15) forbid using the service "for or in connection with real-time
navigation or route guidance" — RouteMind is a turn-by-turn navigator, so no Mapillary image, tile or
API call is used anywhere (the doc §2).

PRECISION FIRST — a wrong photo is worse than none (the rules and the measured table are in the doc):

  Commons by name: the file's CAMERA is within NAME_RADIUS_M (+ the place's footprint, ≤ 400 m) and its
  title carries EVERY word of one of the place's names (generic words — mosque / مسجد, school, hotel… —
  count through their synonym class; articles, city names and camera junk never count), with at least one
  distinctive word of ≥ 4 letters; a one-word name must be ≥ 6 letters. A file two places claim equally
  is nobody's. Maps, plans, logos, coins, stamps and diagrams are not photos.

  Street level: the camera is DIST_MIN_M–DIST_MAX_M from the place, looking at it — the bearing to the
  place within ±HALF_FOV_DEG of the compass for a flat frame (a 360° panorama sees every way, and is
  preferred), captured ≥ MIN_YEAR, and nothing else about it is guessed. `fx` = where the place falls
  across the frame (0..1), so the phone centres its crop on the shop instead of the road ahead.

Every network failure leaves photos out — never the build. Nothing is downloaded: the phone shows each
source's own thumbnails (Commons' standard widths, Panoramax's stable derivates).
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

from . import fetch as F
from . import records as R
from . import textnorm as tn

UA = "RouteMind-place-index/1.0 (https://github.com/ibrahim212-wq/routemind-places)"


def log(*a):
    print("[photos]", *a, flush=True)


def _get(url: str, accept: str = "application/json", tries: int = 3, timeout: int = 90) -> bytes:
    def once():
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    return F._retry(url[:60], once, tries=tries)


# ── Commons: geotagged files ─────────────────────────────────────────────────────────────────────

NAME_RADIUS_M = 120.0
NAME_EXTENT_CAP_M = 400.0
COMMONS_CELL_DEG = 0.08
COMMONS_MIN_CELL_DEG = 0.004
NOT_A_PHOTO = re.compile(r"\b(map|maps|plan|plans|logo|diagram|coat of arms|flag|coin|stamp|banknote|ticket|"
                         r"seal|emblem|chart|graph|scheme|layout|drawing|sketch|engraving|lithograph|postcard|sign|signs|"
                         r"signboard|location|locator|route|timetable|schedule|screenshot|page|plate|planche|illustration|"
                         r"vol|lepsius|wreszinski|timea|met dp|inauguration|portrait|خريطة|شعار|مخطط|لافتة)\b", re.I)
PHOTO_EXT = re.compile(r"\.(jpe?g|png|webp)$", re.I)


@dataclass
class GeoFile:
    title: str      # without «File:»
    lat: float
    lng: float


def commons_geo(cells: list[tuple[float, float, float, float]], deadline: float) -> list[GeoFile]:
    """Every geotagged file (namespace 6) in the cells (s, w, n, e); a cell that answers the API's 500
    cap is split in four until COMMONS_MIN_CELL_DEG."""
    out: dict[int, GeoFile] = {}
    stack = list(cells)
    calls = 0
    while stack:
        if time.time() > deadline:
            log("commons geo: time budget spent,", len(stack), "cells left")
            break
        s, w, n, e = stack.pop()
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&list=geosearch&gsnamespace=6"
               f"&gslimit=500&maxlag=5&gsbbox={n:.5f}|{w:.5f}|{s:.5f}|{e:.5f}")
        try:
            res = json.loads(_get(url))
        except (OSError, ValueError) as ex:
            log("commons geo cell skipped:", str(ex)[:100])
            continue
        calls += 1
        err = (res.get("error") or {}).get("code")
        g = (res.get("query") or {}).get("geosearch") or []
        if (err == "toobig" or len(g) >= 500) and (n - s) / 2 >= COMMONS_MIN_CELL_DEG:
            hs, hw = (n - s) / 2, (e - w) / 2
            stack += [(s, w, s + hs, w + hw), (s, w + hw, s + hs, e), (s + hs, w, n, w + hw), (s + hs, w + hw, n, e)]
            if err:
                continue
        for x in g:
            t = x.get("title", "")
            name = t[5:] if t.startswith("File:") else t
            if PHOTO_EXT.search(name) and not NOT_A_PHOTO.search(name):
                out[x["pageid"]] = GeoFile(name, float(x["lat"]), float(x["lon"]))
        time.sleep(0.05)
    log(f"commons geo: {len(out)} photo files in {len(cells)} cells, {calls} calls")
    return list(out.values())


# words that say WHAT a place is, folded into one class each (a title «Ibn Tulun Mosque» matches a
# place named «Masjid Ibn Tulun»); they never make a name distinctive on their own
GENERIC = {
    "mosque": ("mosque", "masjid", "masgid", "jami", "jamia", "gamaa", "gamea", "gami", "مسجد", "جامع", "زاويه", "زاوية"),
    "church": ("church", "كنيسه", "كنيسة", "cathedral", "كاتدرائيه", "كاتدرائية", "basilica", "chapel"),
    "monastery": ("monastery", "convent", "dayr", "deir", "دير"),
    "school": ("school", "مدرسه", "مدرسة", "madrasa", "madrasah", "college", "كليه", "كلية"),
    "university": ("university", "جامعه", "جامعة"),
    "hospital": ("hospital", "مستشفى", "مستشفي", "clinic", "عياده", "عيادة"),
    "hotel": ("hotel", "فندق", "hostel", "resort", "inn"),
    "museum": ("museum", "متحف"),
    "palace": ("palace", "قصر", "qasr", "kasr"),
    "gate": ("gate", "bab", "باب"),
    "tomb": ("tomb", "mausoleum", "ضريح", "مقام", "qubba", "قبه", "قبة"),
    "square": ("square", "midan", "maydan", "ميدان"),
    "bridge": ("bridge", "كوبري", "kobri", "جسر"),
    "station": ("station", "محطه", "محطة", "mahatta"),
    "park": ("park", "garden", "gardens", "حديقه", "حديقة", "منتزه"),
    "market": ("market", "souq", "souk", "سوق", "bazaar"),
    "tower": ("tower", "برج", "burg", "borg"),
    "mall": ("mall", "مول"),
    "club": ("club", "نادي", "نادى"),
    "restaurant": ("restaurant", "مطعم", "cafe", "café", "coffee", "مقهى", "قهوه", "كافيه", "pizza", "بيتزا", "patisserie",
                   "pastry", "حلواني", "koshary", "كشري"),
    "shop": ("shop", "store", "محل", "pharmacy", "صيدليه", "صيدلية", "bank", "بنك", "bakery", "مخبز", "فرن"),
    "fort": ("fort", "fortress", "citadel", "castle", "قلعه", "قلعة", "طابيه", "طابية"),
    "temple": ("temple", "معبد"),
    "house": ("house", "bayt", "beit", "بيت", "villa", "فيلا", "manzil", "منزل"),
    "building": ("building", "مبنى", "مبني", "عماره", "عمارة"),
    "sabil": ("sabil", "sabeel", "سبيل", "kuttab", "كتاب"),
    "street": ("street", "st", "road", "شارع", "طريق"),
}
GENERIC_OF = {tn.normalize(w): k for k, ws in GENERIC.items() for w in ws}
# never evidence: where the photo was taken, how, and article / number noise
NOISE = {tn.normalize(w) for w in (
    "cairo", "egypt", "egyptian", "giza", "alexandria", "alex", "luxor", "aswan", "mansoura", "mahalla", "tanta",
    "القاهره", "القاهرة", "مصر", "الجيزه", "الجيزة", "الاسكندريه", "الإسكندرية", "governorate", "panoramio",
    "flickr", "img", "dsc", "dscn", "dscf", "jpg", "jpeg", "png", "photo", "picture", "view", "views", "from", "inside",
    "outside", "interior", "exterior", "detail", "details", "near", "with", "and", "the", "of", "in", "at", "on", "to",
    "el", "al", "an", "as", "ad", "ar", "az", "ash", "a", "by", "ii", "iii", "old", "new", "city", "town", "district",
    "islamic", "coptic", "historic", "northern", "southern", "eastern", "western", "north", "south", "east", "west",
    "wikimedia", "commons", "file", "cropped", "edit", "edited", "pano", "panorama", "night", "day", "front", "side",
    "entrance", "facade", "façade", "minaret", "dome", "courtyard", "wall", "walls", "door", "window", "general",
    "شارع", "منطقه", "منطقة")}
NOISE |= {s for w in list(NOISE) for s in tn.stems(w)}
STREET_WORDS = {tn.normalize(w) for w in ("street", "st", "road", "rd", "avenue", "ave", "corniche", "شارع", "طريق", "كورنيش")}


# what a place IS, for the two business rules below (and the measurement's strata, bench/photo_eval.py)
GROUPS = {
    "landmark": {"historic_site", "attraction", "museum", "monument", "palace", "castle", "archaeological_site",
                 "square", "tower", "viewpoint", "statue", "memorial", "obelisk", "lake", "island", "beach", "natural",
                 "mountain", "bridge", "water"},
    "worship": {"mosque", "church", "place_of_worship", "monastery", "synagogue", "cathedral", "cemetery"},
    "hotel": {"hotel", "hostel", "resort", "guest_house"},
    "civic": {"university", "school", "college", "hospital", "library", "government_office", "ministry", "embassy",
              "courthouse", "cultural_center", "theater", "cinema", "stadium", "sports_club", "park", "zoo",
              "train_station", "metro_station", "airport", "office", "ngo", "institute", "townhall",
              "building", "event_venue"},
}


def group_of(cat: str | None) -> str:
    for g, cs in GROUPS.items():
        if cat in cs:
            return g
    return "shop"   # restaurants, cafés, shops, services: the small places


# a shop named after a landmark («مطعم قصر الطاهرة», «Fort Qaitbey» travel) is not the landmark's photos
LANDMARK_CLASSES = {"#palace", "#fort", "#mosque", "#church", "#monastery", "#tomb", "#gate", "#square", "#museum",
                    "#temple", "#sabil"}
# a shop's photo must say it is a shop, or carry two distinctive words of its name («Dahab Masr Almaza Branch»)
TRADE_CLASSES = {"#restaurant", "#shop", "#hotel", "#mall", "#market"}


def _title_words(title: str) -> list[str]:
    t = re.sub(r"\.[a-z]{3,4}$", "", title, flags=re.I)
    t = re.sub(r"\([^)]*\)", " ", t)           # «(55)», «(6542666559)», «(cropped)»
    t = re.sub(r"[_\-–—,.;:!?'\"“”/\\]+", " ", t)
    return tn.tokens(t)


def _fold(w: str) -> list[str]:
    """A word and its stems, generic words as their class («#mosque»)."""
    out = []
    for x in [w] + tn.stems(w)[1:]:
        g = GENERIC_OF.get(x)
        out.append("#" + g if g else x)
    return out


def _title_tokens(title: str) -> tuple[set[str], set[str]]:
    """(every token of the title, the tokens that only name a street: «Saad Zaghloul Street», «شارع الأقصر»)."""
    words = [w for w in _title_words(title) if len(w) >= 2 or w.isdigit()]
    out, bound, free = set(), set(), set()
    for k, w in enumerate(words):
        f = _fold(w)
        out.update(f)
        nxt = words[k + 1] if k + 1 < len(words) else ""
        prv = words[k - 1] if k else ""
        nx2 = words[k + 2] if k + 2 < len(words) else ""
        on_street = (nxt in STREET_WORDS or nx2 in STREET_WORDS or prv in STREET_WORDS or
                     (k >= 2 and words[k - 2] in STREET_WORDS))
        (bound if on_street and w not in STREET_WORDS else free).update(f)
    return out, bound - free


def name_variants(p) -> list[tuple[frozenset, int]]:
    """Each usable name → (its required tokens, number of distinctive words). Unusable names dropped."""
    out = []
    seen = set()
    for n in [x for x in (p.name_en, p.name_ar, *p.alt) if x]:
        toks = []
        for w in tn.tokens(n):
            if tn.is_stopword(w) or w in ("ال", "el", "al"):
                continue
            if w.isdigit():
                toks.append(w)        # «Terminal 2» is not «Terminal 3»
                continue
            st = tn.stems(w)
            base = st[1] if len(st) > 1 and len(st[1]) >= 3 else w     # «الأزهر» → «ازهر», «el-azhar» → «azhar»
            g = GENERIC_OF.get(w) or GENERIC_OF.get(base)
            toks.append("#" + g if g else base)
        req = frozenset(toks)
        if not req or req in seen:
            continue
        seen.add(req)
        distinct = [t for t in req if not t.startswith("#") and t not in NOISE and len(t) >= 4 and not t.isdigit()]
        if not distinct:
            continue
        if len(distinct) == 1 and len(req) == 1 and len(distinct[0]) < 6:
            continue
        out.append((req, len(distinct)))
    return out


class _Grid:
    def __init__(self, pts, cell_deg: float):
        self.c = cell_deg
        self.g: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (la, ln) in enumerate(pts):
            self.g[(int(la / cell_deg), int(ln / cell_deg))].append(i)

    def near(self, lat: float, lng: float, radius_m: float):
        r = int(math.ceil(radius_m / (111_000 * self.c))) + 1
        ci, cj = int(lat / self.c), int(lng / self.c)
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                yield from self.g.get((i, j), ())


def match_commons_geo(places, files: list[GeoFile], per_place: int = 4,
                      others=()) -> dict[str, list[tuple[str, float, int]]]:
    """pid → [(file, metres, matched tokens)] best first. `places` need pid, lat, lng, extent_m and names.
    `others` (streets, areas) claim files too and never receive one: a title that names the street or the
    district a shop is named after is the street's. Words first (an inverted index of the titles: a place
    only looks at files carrying its rarest word), then the distance."""
    if not files:
        return {}
    tt = [_title_tokens(f.title) for f in files]
    ftoks = [a for a, _ in tt]
    fbound = [b for _, b in tt]
    inv: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(ftoks):
        for t in ts:
            inv[t].append(i)
    claims: dict[int, list[tuple[int, int, float, str]]] = defaultdict(list)   # file → [(ntok, distinct, -d, pid)]
    takers = {p.pid for p in places}
    for p in list(places) + list(others):
        street_like = p.pid not in takers
        shop = not street_like and group_of(getattr(p, "cat", None)) == "shop"
        vs = name_variants(p)
        if shop:
            vs = [(req, nd) for req, nd in vs if not (req & LANDMARK_CLASSES)]
        if not vs:
            continue
        radius = NAME_RADIUS_M + min(NAME_EXTENT_CAP_M, p.extent_m or 0.0)
        best: dict[int, tuple[int, int, float]] = {}
        for req, nd in vs:
            rare = min(req, key=lambda t: len(inv.get(t, ())))
            for i in inv.get(rare, ()):
                if not req <= ftoks[i]:
                    continue
                if not street_like and all(t in fbound[i] for t in req if not t.startswith("#")):
                    continue  # the title only names a street called like the place
                if shop and nd < 2 and not (ftoks[i] & TRADE_CLASSES):
                    continue  # «Sphinx» the bus stop, «Al Tahrir» the sweet shop
                if NOT_A_PHOTO.search(files[i].title):
                    continue
                f = files[i]
                if abs(f.lat - p.lat) * 111_000 > radius:
                    continue
                d = R.haversine(p.lat, p.lng, f.lat, f.lng)
                if d > radius:
                    continue
                if i not in best or (len(req), nd) > best[i][:2]:
                    best[i] = (len(req), nd, d)
        for i, (nt, nd, d) in best.items():
            claims[i].append((nt, nd, -d, p.pid))
    out: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    for i, cl in claims.items():
        cl.sort(reverse=True)
        if len(cl) > 1 and cl[0][:2] == cl[1][:2] and cl[0][3] != cl[1][3]:
            continue  # two places claim it equally — nobody's
        ntok, _, negd, pid = cl[0]
        if pid in takers:
            out[pid].append((files[i].title, -negd, ntok))
    for pid in out:
        out[pid].sort(key=lambda x: (-x[2], x[1], x[0]))
        del out[pid][per_place:]
    return dict(out)


# ── Street level ─────────────────────────────────────────────────────────────────────────────────

DIST_MIN_M = 6.0
DIST_MAX_M = 40.0
PANO_DIST_MAX_M = 30.0
HALF_FOV_DEG = 28.0          # a phone / dashcam frame is ~60-75° wide: the place stays inside it with a margin
FLAT_HFOV_DEG = 68.0         # the frame width `fx` is computed against
MIN_YEAR = 2017
STREET_EXTENT_MAX_M = 60.0   # a campus / park / district is not "the thing in the frame"


@dataclass
class StreetImage:
    src: str            # panoramax (the matcher is source-neutral)
    ref: str            # host/uuid
    lat: float
    lng: float
    heading: float      # compass degrees, 0 = north
    pano: bool
    year: int
    at: str | None      # YYYY-MM-DD
    by: str | None = None
    lic: str | None = None


def bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _wrap(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def street_fit(p_lat: float, p_lng: float, im: StreetImage) -> tuple[float, float, float] | None:
    """(score, metres, fx) when the image can show the place, else None."""
    d = R.haversine(im.lat, im.lng, p_lat, p_lng)
    if d < DIST_MIN_M or d > (PANO_DIST_MAX_M if im.pano else DIST_MAX_M) or im.year < MIN_YEAR:
        return None
    off = _wrap(bearing(im.lat, im.lng, p_lat, p_lng) - im.heading)
    if im.pano:
        fx = 0.5 + off / 360.0
        score = 1.0 - abs(d - 14.0) / 30.0
    else:
        if abs(off) > HALF_FOV_DEG:
            return None
        fx = 0.5 + math.tan(math.radians(off)) / (2.0 * math.tan(math.radians(FLAT_HFOV_DEG / 2)))
        # nearer and nearer the centre line is a bigger, cleaner view of the front
        score = 0.6 - abs(d - 18.0) / 40.0 - abs(off) / 90.0
    score += 0.05 * (im.year - MIN_YEAR)
    return score, d, min(1.0, max(0.0, fx))


def match_street(places, images: list[StreetImage], per_place: int = 3) -> dict[str, list[tuple[StreetImage, float, float]]]:
    if not images:
        return {}
    grid = _Grid([(im.lat, im.lng) for im in images], 0.001)
    out = {}
    for p in places:
        if (p.extent_m or 0.0) > STREET_EXTENT_MAX_M:
            continue
        cands = []
        for i in grid.near(p.lat, p.lng, DIST_MAX_M + 5):
            fit = street_fit(p.lat, p.lng, images[i])
            if fit:
                cands.append((fit[0], fit[1], fit[2], images[i]))
        if not cands:
            continue
        cands.sort(key=lambda c: (-c[0], c[3].ref))
        seen_seq = set()
        best = []
        for sc, d, fx, im in cands:
            key = (im.src, round(im.lat, 4), round(im.lng, 4))   # not three frames from the same spot
            if key in seen_seq:
                continue
            seen_seq.add(key)
            best.append((im, d, fx))
            if len(best) >= per_place:
                break
        out[p.pid] = best
    return out


# ── Panoramax (open, federated; no key) ──────────────────────────────────────────────────────────

PANORAMAX_API = "https://api.panoramax.xyz/api"


def panoramax(bbox: tuple[float, float, float, float], deadline: float) -> list[StreetImage]:
    """Every picture the federation lists in (w, s, e, n), followed through its `next` links."""
    w, s, e, n = bbox
    url = f"{PANORAMAX_API}/search?bbox={w},{s},{e},{n}&limit=1000"
    out: dict[str, StreetImage] = {}
    pages = 0
    while url and time.time() < deadline and pages < 200:
        try:
            res = json.loads(_get(url, "application/geo+json"))
        except (OSError, ValueError) as ex:
            log("panoramax page skipped:", str(ex)[:100])
            break
        pages += 1
        for f in res.get("features") or []:
            pr = f.get("properties") or {}
            az = pr.get("view:azimuth")
            coords = (f.get("geometry") or {}).get("coordinates") or []
            dt = (pr.get("datetime") or "")[:10]
            lic = pr.get("license")
            if az is None or len(coords) < 2 or not dt or not lic:
                continue
            fov = ((pr.get("pers:interior_orientation") or {}).get("field_of_view"))
            thumb = ((f.get("assets") or {}).get("thumb") or {}).get("href") or ""
            host = urllib.parse.urlparse(thumb).netloc
            if not host:
                continue
            out[f["id"]] = StreetImage("panoramax", f"{host}/{f['id']}", float(coords[1]), float(coords[0]),
                                       float(az), fov == 360, int(dt[:4]), dt,
                                       by=pr.get("geovisio:producer"), lic=_spdx(lic))
        url = next((l.get("href") for l in res.get("links") or [] if l.get("rel") == "next"), None)
    log(f"panoramax: {len(out)} pictures, {pages} pages")
    return list(out.values())


def _spdx(lic: str) -> str:
    m = {"CC-BY-SA-4.0": "CC BY-SA 4.0", "CC-BY-4.0": "CC BY 4.0", "etalab-2.0": "Licence Ouverte 2.0", "CC0-1.0": "CC0"}
    return m.get(lic, lic)
