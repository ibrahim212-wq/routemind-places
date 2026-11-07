"""After the merge: what makes a place readable and findable beyond its own name.

  * governorate — the polygon the place sits in (Overture divisions, ODbL);
  * area_ar / area_en — the neighbourhood / village / city it belongs to, for the result subtitle
    («صيدلية · المعادي، القاهرة») and for «صيدلية في المعادي»;
  * brand key — the lexicon brand a place is a branch of (assets/search/egypt_lexicon.json aliases),
    or `auto:<core name>` when the same name runs ≥ AUTO_BRAND_MIN places of one category across
    the country (the Dart BrandDetector's rule, applied to the whole index once);
  * keep() — the noise filter: Meta pages with no physical place behind them.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict

from . import merge as M
from . import records as R
from . import taxonomy as T
from . import textnorm as tn

ONLINE_HOSTS = ("instagram.com", "tiktok.com", "amazon.", "t.me", "wordpress.com", "youtube.com", "linktr.ee",
                "wa.me", "whatsapp", "jumia.com", "noon.com", "blogspot.", "facebook.com/share")
ALWAYS_KEEP = {"hospital", "emergency_room", "pharmacy", "clinic", "medical_center", "police", "gas_station",
               "government", "school", "university", "mosque", "church", "bank", "atm", "post_office"}


# Kinds an online seller's or a person's page is filed under far more often than a shop's (the
# 2026-10-31 audit of the 22,389 rows the confidence floor dropped: Instagram boutiques, agencies,
# event planners, personal pages): a low-confidence page of one of these stays dropped.
ONLINE_PRONE = {"place", "shop", "store", "service", "company", "office", "tech_company", "advertising",
                "event_service", "real_estate", "travel_agency", "tutoring", "training_center", "ngo", "clothes",
                "womens_clothes", "mens_clothes", "kids_clothes", "shoes", "cosmetics", "gifts", "jewelry",
                "accessories", "home_goods", "art_gallery", "photographer", "lawyer", "consultant", "media",
                # the rescued sample's own noise: holiday-rental pages filed as hotels, property developers,
                # couriers and «factories» selling online, «spiritual healers» filed as cultural centres
                "hotel", "developer", "shipping", "factory", "cultural_center"}


def _storefront(rec: R.Record) -> bool:
    """A searchable kind of place people walk into (a restaurant, a grocery, a salon, a doctor, a mobile
    shop, a car repair …) with a phone number: the same audit found «مطبخ عبود», Muy Frito, a hair salon, a
    swimming academy and mobile shops among the dropped pages — real storefronts behind thin pages."""
    c = T.BY_ID.get(rec.cat)
    return bool(rec.phone) and c is not None and c.scat is not None and rec.cat not in ONLINE_PRONE


def keep_reason(rec: R.Record) -> str | None:
    """None = kept; else why the row is dropped (build_report `dropped`): a Meta row that is almost certainly an
    online-only shop or a personal page, or a Foursquare row nobody refreshed in years. rescue() may still bring
    a dropped row back on independent evidence."""
    if rec.extra.get("history"):  # gone from the current release: the long tail, whatever else it has (history.py)
        return "history"
    if rec.src == R.SRC_FSQ and rec.extra.get("stale"):
        return "fsq_stale"
    if rec.src not in (R.SRC_META, R.SRC_OVT_OTHER):
        return None
    if rec.cat in ALWAYS_KEEP:
        return None if rec.conf >= 0.12 else "vital_conf_below_0.12"
    web = (rec.website or "").lower()
    online = any(h in web for h in ONLINE_HOSTS)
    store = _storefront(rec)
    if online and rec.conf < 0.45 and not (store and rec.conf >= 0.2):
        return "online_seller_link"
    if rec.conf < 0.2 and not (store and not online and rec.conf >= 0.08):
        if store:
            return "storefront_conf_below_0.08"
        if not rec.phone:
            return "low_conf_no_phone"
        if rec.cat in ONLINE_PRONE:
            return "low_conf_online_prone_kind"
        return "low_conf_unsearchable_kind"
    return None


def keep(rec: R.Record) -> bool:
    return keep_reason(rec) is None


# ── rescue: a dropped row with independent evidence that the place is there ──

_JUNK_PHONE = re.compile(r"(\d)\1{6,}|0123456789|1234567")


def eg_phone(phone: str | None) -> bool:
    """A dialable Egyptian number (records.clean_phone's +20 form): a mobile +20 1[0125] + 8 digits, Cairo / Giza
    +20 2 + 8, Alexandria +20 3 + 7, another governorate's 2-digit code + 7, or a 5-digit hotline (19xxx / 16xxx);
    never a run of one digit or a counting sequence."""
    if not phone:
        return False
    d = phone.replace("+", "")
    if _JUNK_PHONE.search(d):
        return False
    if re.fullmatch(r"1[0-9]{4}", d):
        return d[:2] in ("19", "16", "15")
    if not d.startswith("20"):
        return False
    n = d[2:]
    return bool(re.fullmatch(r"1[0125][0-9]{8}", n) or re.fullmatch(r"2[0-9]{8}", n) or re.fullmatch(r"3[0-9]{7}", n)
                or re.fullmatch(r"(4[0-8]|5[0-7]|6[2-9]|8[2-8]|9[2-7])[0-9]{7}", n))


# a name that sells or works online, or is a person's page, whatever its category says
_ONLINE_NAME = re.compile(r"(?i)online|اون ?لاين|أون ?لاين|delivery|توصيل|artist|makeup|ميكب|ميك اب|photograph|تصوير|"
                          r"courses?\b|كورسات|jobs?\b|وظائف|\.com\b|\.eg\b|\.net\b|page\b|صفحه|صفحة|official|"
                          r"store online|brand\b|collection|for sale|للبيع")
CONFIRM_SIM = 0.9    # a dropped row is confirmed only by a row of another source with (nearly) the same name
RESCUE_NEAR_M = 30.0  # a mapped building / OSM place this close counts as "something is there"


def rescue(dropped: list[tuple[R.Record, str]], kept: list[R.Record], bcells: set[int] | None,
           report: dict) -> list[R.Record]:
    """Bring back a dropped row when independent evidence says the place exists:

      * CONFIRMED — a kept row of ANOTHER source is the same place (merge.match_score ≥ MATCH: the name agrees within
        the category's radius, or the same number with an agreeing name); it would merge into that place anyway, so
        it adds a name, a number, a confirmation — never a second pin;
      * a stale Foursquare venue (it was a real venue people checked in at; the doubt is whether it is still open)
        otherwise needs ALL of, never with a link to an online shop or a name that says it sells online, never on a
        pin many pages share (a district's centre, unstack):
          PHONE    a dialable Egyptian number (eg_phone),
          KIND     a kind people walk into that search can ask for (a display category, not an online-prone kind),
          THERE    a mapped building or an OSM place within RESCUE_NEAR_M of the pin.
        Measured on Overture 2026-10 + OSM, that is NOT evidence for a low-confidence Facebook page: two of the three
        brought back 3,390 rows, nearly all Instagram boutiques, makeup artists, photographers and job pages (every
        online seller has a mobile number, and in a city every pin has a building beside it), and all three still
        brought back 174, half of them on district-centre pins or filed under the wrong kind. A page comes back only
        when another source confirms it.

    The rescued row keeps its own low confidence (it ranks below a confirmed place) and is marked `rescued`."""
    from . import sources as S
    osm_cells = set()
    for r in kept:
        if r.src == R.SRC_OSM and r.kind == "poi":
            osm_cells.add(S.building_cell(r.lat, r.lng))
    bc = bcells or set()

    def there(r: R.Record) -> bool:
        c0 = S.building_cell(r.lat, r.lng)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                c = c0 + di * 1000000 + dj
                if c in bc or c in osm_cells:
                    return True
        return False

    # the CONFIRMED test: the merge's own matcher against kept rows of other sources nearby
    cell = M.CELL
    grid: dict[tuple[int, int], list[M.Prep]] = defaultdict(list)
    need = {(int(math.floor(r.lng / cell)), int(math.floor(r.lat / cell))) for r, _ in dropped}
    for r in kept:
        if r.kind != "poi":
            continue
        k = (int(math.floor(r.lng / cell)), int(math.floor(r.lat / cell)))
        if any((k[0] + dx, k[1] + dy) in need for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            grid[k].append(M.prep(r))

    def confirmed(r: R.Record) -> bool:
        p = M.prep(r)
        if not p.core and not p.phone:
            return False
        cx, cy = int(math.floor(r.lng / cell)), int(math.floor(r.lat / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in grid.get((cx + dx, cy + dy), ()):
                    if m.rec.src == r.src or (r.src == R.SRC_FSQ and m.rec.extra.get("fsq_id")):
                        continue
                    if M.match_score(p, m, R.haversine(r.lat, r.lng, m.lat, m.lng)) < M.MATCH:
                        continue
                    # the SAME name, or the same number — never one shared word: places-2026-10-31.4 let a stale
                    # «مول مصر» be "confirmed" by a cafe "Al Alam El Masry" (مصر ⇄ masry) and lent it its name
                    if (p.phone and p.phone == m.phone) or M.name_similarity(p, m) >= CONFIRM_SIM:
                        return True
        return False

    pins = Counter((round(r.lat, 5), round(r.lng, 5)) for r in kept if r.kind == "poi")
    pins.update((round(r.lat, 5), round(r.lng, 5)) for r, _ in dropped)
    out = []
    stats: dict = {}
    for r, why in dropped:
        web = (r.website or "").lower()
        online = any(h in web for h in ONLINE_HOSTS)
        how = None
        if why != "history" and confirmed(r):
            how = "confirmed_by_another_source"
        elif (why == "fsq_stale" and not online and not any(_ONLINE_NAME.search(n) for n, _ in r.names)
              and pins[(round(r.lat, 5), round(r.lng, 5))] < STACK_MIN):
            c = T.BY_ID.get(r.cat)
            if (eg_phone(r.phone) and c is not None and c.scat is not None and r.cat not in ONLINE_PRONE
                    and r.cat not in M.GENERIC_CATS and there(r)):
                how = "phone+kind+there"
        key = f"{r.src}:{why}"
        st = stats.setdefault(key, {"dropped": 0, "rescued": 0, "by": {}})
        st["dropped"] += 1
        if how:
            st["rescued"] += 1
            st["by"][how] = st["by"].get(how, 0) + 1
            r.extra["rescued"] = how
            out.append(r)
    report["rescue"] = stats
    return out


# ── governorates ─────────────────────────────────────────────────────────────

GOV_IDS = {
    "القاهرة": "cairo", "الجيزة": "giza", "الإسكندرية": "alexandria", "القليوبية": "qalyubia",
    "الدقهلية": "dakahlia", "الشرقية": "sharqia", "الغربية": "gharbia", "المنوفية": "monufia",
    "البحيرة": "beheira", "كفر الشيخ": "kafr_el_sheikh", "دمياط": "damietta", "بورسعيد": "port_said",
    "الإسماعيلية": "ismailia", "السويس": "suez", "الفيوم": "faiyum", "بني سويف": "beni_suef",
    "المنيا": "minya", "أسيوط": "asyut", "سوهاج": "sohag", "قنا": "qena", "الأقصر": "luxor",
    "أسوان": "aswan", "البحر الأحمر": "red_sea", "الوادي الجديد": "new_valley", "مطروح": "matrouh",
    "شمال سيناء": "north_sinai", "جنوب سيناء": "south_sinai", "مثلث حلايب": "halaib",
}


# Gharbia and Monufia never matched GOV_IDS by name in places-2026-11-02: 16,856 POIs had no governorate.
GOV_CAPITAL = {
    "cairo": (30.0444, 31.2357), "giza": (30.0131, 31.2089), "alexandria": (31.2001, 29.9187), "qalyubia": (30.4597, 31.1842),
    "dakahlia": (31.0409, 31.3785), "sharqia": (30.5877, 31.5020), "gharbia": (30.7865, 31.0004), "monufia": (30.5586, 31.0100),
    "beheira": (31.0342, 30.4682), "kafr_el_sheikh": (31.1107, 30.9388), "damietta": (31.4165, 31.8133),
    "port_said": (31.2653, 32.3019), "ismailia": (30.5965, 32.2715), "suez": (29.9668, 32.5498), "faiyum": (29.3084, 30.8428),
    "beni_suef": (29.0661, 31.0994), "minya": (28.1099, 30.7503), "asyut": (27.1783, 31.1859), "sohag": (26.5591, 31.6957),
    "qena": (26.1551, 32.7160), "luxor": (25.6872, 32.6396), "aswan": (24.0889, 32.8998), "red_sea": (27.2579, 33.8116),
    "new_valley": (25.4390, 30.5586), "matrouh": (31.3543, 27.2373), "north_sinai": (31.1316, 33.7984), "south_sinai": (28.2400, 33.6200),
}


class GovLocator:
    def __init__(self, division_area_parquet: str):
        import pyarrow.parquet as pq
        import shapely
        from shapely.strtree import STRtree
        rows = pq.read_table(division_area_parquet, columns=["subtype", "country", "class", "names", "geometry"]).to_pylist()
        self.polys, self.ids, self.names = [], [], {}
        for r in rows:
            if r["subtype"] != "region" or r["country"] != "EG" or r["class"] != "land":
                continue
            nm = (r["names"] or {}).get("primary")
            gid = GOV_IDS.get(nm)
            if not gid:
                for k, v in GOV_IDS.items():
                    if tn.normalize(k) == tn.normalize(nm or ""):
                        gid = v
            poly = shapely.from_wkb(r["geometry"])
            if not gid:  # another spelling of the name («محافظة الغربية», "Al Gharbiyah"): the polygon holding the capital
                gid = next((g for g, (lat, lng) in GOV_CAPITAL.items() if poly.contains(shapely.Point(lng, lat))), None)
            if not gid:
                continue
            common = (r["names"] or {}).get("common") or {}
            common = dict(common) if not isinstance(common, dict) else common
            self.names[gid] = (nm, common.get("en") or gid.replace("_", " ").title())
            self.polys.append(poly)
            self.ids.append(gid)
        self.tree = STRtree(self.polys)

    def locate(self, lat: float, lng: float) -> str | None:
        import shapely
        p = shapely.Point(lng, lat)
        for i in self.tree.query(p):
            if self.polys[i].contains(p):
                return self.ids[i]
        # coast / river-bank points just outside every polygon: the nearest one
        i = self.tree.nearest(p)
        return self.ids[i] if i is not None and self.polys[i].distance(p) < 0.05 else None


# ── containing area (subtitle) ───────────────────────────────────────────────

AREA_REACH = {"neighbourhood": 1800, "district": 4500, "village": 2500, "hamlet": 1200, "town": 6000,
              "city": 12000, "markaz": 0, "governorate": 0}
AREA_PREF = {"neighbourhood": 0, "district": 1, "village": 1, "hamlet": 2, "town": 2, "city": 3}


class AreaLocator:
    def __init__(self, areas: list[M.Place]):
        self.cell = 0.05
        self.grid: dict[tuple[int, int], list[M.Place]] = defaultdict(list)
        for a in areas:
            if AREA_REACH.get(a.cat, 0) == 0 or not (a.name_ar or a.name_en):
                continue
            self.grid[(int(a.lat // self.cell), int(a.lng // self.cell))].append(a)

    def locate(self, lat: float, lng: float) -> M.Place | None:
        ci, cj = int(lat // self.cell), int(lng // self.cell)
        best, best_k = None, None
        for di in (-2, -1, 0, 1, 2):
            for dj in (-2, -1, 0, 1, 2):
                for a in self.grid.get((ci + di, cj + dj), ()):
                    reach = max(AREA_REACH[a.cat], min(a.extent_m, 3 * AREA_REACH[a.cat]))
                    d = R.haversine(lat, lng, a.lat, a.lng)
                    if d > reach:
                        continue
                    k = (AREA_PREF.get(a.cat, 3), d / reach)
                    if best_k is None or k < best_k:
                        best, best_k = a, k
        return best


# ── stacked pins: many pages geocoded to one district centre ───────────────

STACK_MIN = 5          # this many places of the page sources on one exact point = a geocoded centre, not a building
STACK_SNAP_M = 3000.0  # a stacked page moves to the OSM place of the same name within this distance
_PAGE_SRCS = {R.SRC_META, R.SRC_FSQ, R.SRC_MS, R.SRC_OVT_OTHER}


def unstack(recs: list[R.Record], report: dict) -> None:
    """A Facebook page with no street address is pinned at its district's centre: places-2026-10-31.3 has 1,207
    places on one point of Downtown Cairo, 624 on one point of Alexandria — 1,973 points carry ≥ 5 places, 28k
    places in all. Such a pin is not where the place is. Each stacked row moves to the OSM place that is the same
    place (merge.name_similarity ≥ 0.9, a compatible kind, the only such place within STACK_SNAP_M); the rest are
    marked `approx` (merge sets records.APPROX_BIT when no member knows better), so the engine never ranks them as
    if they stood exactly there."""
    groups: dict[tuple[float, float], list[R.Record]] = defaultdict(list)
    for r in recs:
        if r.kind == "poi" and r.src in _PAGE_SRCS:
            groups[(round(r.lat, 5), round(r.lng, 5))].append(r)
    stacked = [r for g in groups.values() if len(g) >= STACK_MIN for r in g]
    if not stacked:
        report["stacked"] = {"points": 0, "places": 0, "snapped": 0, "approximate": 0}
        return
    cell = 0.03
    grid: dict[tuple[int, int], list[M.Prep]] = defaultdict(list)
    for r in recs:
        if r.src == R.SRC_OSM and r.kind == "poi":
            grid[(int(math.floor(r.lat / cell)), int(math.floor(r.lng / cell)))].append(M.prep(r))
    snapped = 0
    for r in stacked:
        p = M.prep(r)
        best, best_s, second = None, 0.0, 0.0
        if p.core:
            ci, cj = int(math.floor(r.lat / cell)), int(math.floor(r.lng / cell))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for m in grid.get((ci + di, cj + dj), ()):
                        if not M.cats_compatible(r.cat, m.rec.cat):
                            continue
                        if R.haversine(r.lat, r.lng, m.lat, m.lng) > STACK_SNAP_M:
                            continue
                        s = M.name_similarity(p, m)
                        if s > best_s:
                            best, best_s, second = m, s, best_s
                        elif s > second:
                            second = s
        if best is not None and best_s >= 0.9 and second < 0.9:
            r.lat, r.lng = best.lat, best.lng
            r.extra["snapped"] = best.rec.sid
            snapped += 1
        else:
            r.extra["approx"] = True
    report["stacked"] = {"points": sum(1 for g in groups.values() if len(g) >= STACK_MIN), "places": len(stacked),
                         "snapped": snapped, "approximate": len(stacked) - snapped}


# ── kind from the name (a Facebook page filed under a generic class) ─────────

INFER_FROM = frozenset({"place", "shop", "store", "service", "company", "office", "food", "convenience_store",
                        "tech_company"})
# words a category's search terms carry that do not name a kind of place when they head a name («دواء», "tea")
_NOT_A_KIND_WORD = {"قريب", "قريبه", "near", "nearby", "دواء", "medicine", "شاي", "tea", "er", "اقرب", "محل",
                    "shop", "store", "مكان", "place", "center", "مركز", "سنتر",
                    # measured on places-2026-10-31.3: "… Office For Law Services" → rest area, "Toll Station" → police,
                    # "The Temple Flower Essence" → a temple, «رنين لاند» → radiology
                    "services", "service", "station", "محطه", "temple", "معبد", "رنين"}


class KindInferer:
    """A place whose source filed it under a generic class (place / shop / service / company …) takes the kind its
    NAME says, when the name says exactly one: the HEAD word (Arabic «بقالة الأمل», «كشري التحرير») or the LAST word
    (English "Nile Pharmacy") is one search category's own word — its label or a single-word term from the shared
    lexicon — and no word of the name names another category. Every other case keeps the source's class."""

    def __init__(self, lexicon: dict):
        by_word: dict[str, set[str]] = defaultdict(set)
        for c in lexicon.get("categories", []):
            words = [c.get("label_ar"), c.get("label_en")] + list(c.get("terms_ar") or []) + list(c.get("terms_en") or [])
            for w in words:
                toks = tn.tokens(w or "")
                if len(toks) != 1:
                    continue
                k = tn.stems(toks[0])[-1]
                if len(k) >= 3 and k not in _NOT_A_KIND_WORD and toks[0] not in _NOT_A_KIND_WORD:
                    by_word[k].add(c["id"])
        self.word = {k: next(iter(v)) for k, v in by_word.items() if len(v) == 1}
        self.cat_of: dict[str, str] = {}
        for c in T.CATS:
            if c.scat and (c.scat not in self.cat_of or c.id == c.scat):
                self.cat_of[c.scat] = c.id

    def infer(self, cat: str, names: list[str]) -> str | None:
        if cat not in INFER_FROM:
            return None
        found: set[str] = set()
        edge: set[str] = set()
        for nm in names:
            toks = [t for t in tn.tokens(nm) if not tn.is_stopword(t)]
            for i, t in enumerate(toks):
                sc = self.word.get(tn.stems(t)[-1])
                if sc:
                    found.add(sc)
                    if i == 0 or i == len(toks) - 1:
                        edge.add(sc)
        if len(found) != 1 or not edge:
            return None
        new = self.cat_of.get(next(iter(found)))
        return new if new != cat else None


# ── brands ───────────────────────────────────────────────────────────────────

AUTO_BRAND_MIN = 5
AUTO_BRAND_COMMON = 600  # a word in more names than this (محمد, احمد, دكتور) cannot be a chain by itself
AUTO_BRAND_OWN = 0.5    # …and a chain's branches hold at least this share of the names carrying its rarest word
AUTO_BRAND_FAMILY = 0.5  # …and at least this share of them are one family of places (merge.family)
NO_CHAIN_FAMILIES = {"culture", "edu", "gov"}  # «مسجد التوحيد», «مدرسة النصر», «مأمورية الضرائب»: shared names, no chain


def load_lexicon(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class BrandMatcher:
    """Lexicon brands by alias, longest alias first, whole-token match on the place's names.
    Aliases are indexed by their last stem, so a place costs one dict lookup per word.

    A token matches an alias token only as THAT word: «بالعبد» / «والعبد» are «العبد», but «عبد»
    (in every «عبد الرحيم», «عبد الله») is not — an alias written with its article needs the article.
    And a name is the brand's only when it says so:
      * the category agrees (a "Total" lift company, a "Mac" advertising agency are not the chain), and
      * a one-word alias («مصر», «البرج», «الوطنية», «اتصالات», «ماك», «شل») is the whole name — what is
        left is only generic, branch or area words («صيدلية العزبي», "Vodafone - Abbas El Akkad",
        «فودافون مدينة نصر») — or, in an agreeing category, the name's FIRST word ("B.TECH Nasr City").
        «صيدلية د حنان العزبي», «الهدي فون للإتصالات», «تحيا مصر» are other places.
    The source's own brand field (Overture `brand`) is trusted: there only the category is checked."""

    BRANCH_MARKS = {"فرع", "branch", "-", "–", "|", "(", "/"}

    def __init__(self, lexicon: dict):
        self.by_last: dict[str, list[tuple[tuple[str, ...], str, str]]] = defaultdict(list)
        self.brand_cat = {b["id"]: b.get("category_id") or "" for b in lexicon.get("brands", [])}
        for b in lexicon.get("brands", []):
            aliases = set(b.get("aliases") or []) | {b.get("display_ar") or "", b.get("display_en") or ""}
            for a in aliases:
                # stopwords stay: "el abd" is two words, and "Abd" alone is half the names in Egypt
                toks = tuple(tn.tokens(a))
                if toks and toks[0] in NICKNAMES_ONLY and len(toks) == 1:
                    continue
                if toks and (len(toks) > 1 or len(tn.stems(toks[0])[-1]) >= 3):
                    self.by_last[tn.stems(toks[-1])[-1]].append((toks, b["id"], b.get("category_id") or ""))
        for v in self.by_last.values():
            v.sort(key=lambda e: (-len(e[0]), e[1]))
        # words that describe a place, not name it: never "the rest of the name"; and which kinds of
        # place each such word describes («صيدلية» → pharmacy, "shopping" → mall)
        self.descriptive: set[str] = set(M.GENERIC_WORDS)
        self.word_cats: dict[str, set[str]] = defaultdict(set)
        for c in lexicon.get("categories", []):
            for term in [c.get("label_ar"), c.get("label_en")] + list(c.get("terms_ar") or []) + list(c.get("terms_en") or []):
                for t in tn.tokens(term or ""):
                    for w in (t, tn.stems(t)[-1]):
                        self.descriptive.add(w)
                        self.word_cats[w].add(c["id"])

    @staticmethod
    def _same(t: str, a: str) -> bool:
        if t == a:
            return True
        st = tn.stems(t)
        if a.startswith("ال"):
            return len(t) > len(a) and t.endswith(a) and st[-1] == tn.stems(a)[-1]
        return a in st

    def _ignorable(self, t: str) -> bool:
        return (tn.is_stopword(t) or t.isdigit() or t in self.descriptive or tn.stems(t)[-1] in self.descriptive
                or t in M.AREA_TOKENS or tn.stems(t)[-1] in M.AREA_TOKENS)

    def kind_of_branch(self, brand: str | None, scat: str | None) -> str | None:
        """The taxonomy category a branch of this lexicon chain should carry when its own disagrees; None when it agrees."""
        bcat = self.brand_cat.get(brand or "")
        if not bcat or (scat and _brand_cat_ok(bcat, scat)):
            return None
        return next((c.id for c in T.CATS if bcat in (c.id, c.scat)), None)

    def _says_other_kind(self, words: list[str], bcat: str) -> bool:
        """A word of the name describes only kinds of place the brand is not ("Cleopatra Shopping
        Center" is not Cleopatra Hospital; «مدرسة» is no sweet shop)."""
        if not bcat:
            return False
        for w in words:
            cats = self.word_cats.get(w) or self.word_cats.get(tn.stems(w)[-1])
            if cats and not any(_brand_cat_ok(bcat, c) or (M.cats_compatible(bcat, c) and c not in M.UNIVERSAL_CATS)
                                for c in cats):
                return True
        return False

    def _spans(self, name: str):
        """(alias, brand id, brand category, rest-is-empty, alias-is-first, says-other-kind) for every
        alias in the name."""
        raw = name.replace(" - ", " | ").replace("–", " | ")
        cut = len(raw)
        for mark in (" | ", "(", " فرع ", " branch "):
            i = raw.lower().find(mark)
            if 0 < i < cut:
                cut = i
        head = tn.tokens(raw[:cut]) or tn.tokens(raw)
        for i, t in enumerate(head):
            for alias, bid, bcat in self.by_last.get(tn.stems(t)[-1], ()):
                n = len(alias)
                j = i - n + 1
                if j < 0:
                    continue
                win = head[j:i + 1]
                if len(win) == n and all(self._same(x, y) for x, y in zip(win, alias)):
                    rest = [x for k, x in enumerate(head) if not (j <= k <= i) and not self._ignorable(x)]
                    first = next((k for k, x in enumerate(head) if not self._ignorable(x)), j) == j
                    other = self._says_other_kind([x for k, x in enumerate(head) if not (j <= k <= i)], bcat)
                    yield alias, bid, bcat, not rest, first, other

    def match(self, names: list[str], cat: str | None, scat: str | None, source_brand: str | None = None) -> str | None:
        known = bool(cat) and cat not in M.GENERIC_CATS

        def agrees(bcat: str) -> bool:
            return bool(bcat) and ((scat is not None and _brand_cat_ok(bcat, scat))
                                   or (known and M.cats_compatible(bcat, cat) and cat not in M.UNIVERSAL_CATS))

        # a chain the row's own name ties it to, by the same test a name passes alone
        in_names = {bid for n in names for alias, bid, bcat, alone, first, other in self._spans(n)
                    if not other and (len(alias) > 1 or alone or (first and agrees(bcat)))}
        # «مصر» under a source's "مصر للبترول": the name is the chain's name cut short
        src_words = set(tn.tokens(source_brand or ""))
        cut_short = bool(src_words) and any(set(tn.tokens(n)) < src_words for n in names)
        best = None
        for name, trusted in [(n, False) for n in names] + ([(source_brand, True)] if source_brand else []):
            for alias, bid, bcat, alone, first, other in self._spans(name):
                if known and bcat and not agrees(bcat) and not (alone and bcat in OWN_NAME_KINDS):
                    continue  # another kind of place under the same word; a place called ONLY a bank's name is that bank («CIB» filed as a cultural centre)
                if trusted and bid not in in_names and not cut_short:
                    continue  # a source's brand the name never ties to the chain: «داندى مول» Carrefour, «كلية حقوق جامعة شبين» a bank
                if len(alias) == 1 and not (alone or (first and agrees(bcat))):
                    continue  # one word inside a longer name: a person, a family, a street («رشدي شحاته», even when a source says brand)
                if not trusted:
                    if other:
                        continue
                    if len(alias) > 1 and not (alone or first or agrees(bcat)):
                        continue
                key = (len(alias), trusted, bid)
                if best is None or key > best[0]:
                    best = (key, bid)
        return best[1] if best else None


# what people call a chain, never what a place of that name is: «برجر ماك», "Mac Cosmetics" (the parser still reads them)
NICKNAMES_ONLY = {"ماك", "mac"}
# a name in these trades belongs to one licensed company, whatever a source filed the row under
OWN_NAME_KINDS = {"bank", "atm", "pharmacy", "gas_station", "medical_lab", "radiology"}


def _brand_cat_ok(brand_cat: str, scat: str) -> bool:
    if brand_cat == scat:
        return True
    related = [{"bank", "atm", "exchange"}, {"pharmacy", "clinic", "medical_lab"}, {"restaurant", "fast_food", "cafe",
               "pizza", "burger", "sweets", "bakery", "juice_bar"}, {"supermarket", "mall", "market"},
               {"mobile_shop", "electronics_store", "appliance_store"}, {"gas_station", "car_repair", "oil_change"},
               {"clothing_store", "shoe_store", "sports_store"}, {"home_goods_store", "furniture_store", "hardware_store"},
               {"sweets", "ice_cream"}]
    return any(brand_cat in g and scat in g for g in related)


def auto_brands(places: list[M.Place], descriptive: set[str] | None = None) -> dict[str, str]:
    """pid → auto brand key, for a core name shared by ≥ AUTO_BRAND_MIN places of one category
    spread over at least two governorates (or 20 km apart)."""
    by_key: dict[tuple[str, str], list[M.Place]] = defaultdict(list)
    word_df: Counter = Counter()
    for p in places:
        if p.kind == "poi":
            for t in {tn.stems(t)[-1] for t in tn.tokens((p.name_ar or "") + " " + (p.name_en or ""))}:
                word_df[t] += 1
    for p in places:
        if p.kind != "poi" or p.brand_key:
            continue
        nm = p.name_en or p.name_ar
        if not nm:
            continue
        core = [tn.stems(t)[-1] for t in tn.tokens(nm) if not tn.is_stopword(t)]
        core = [t for t in core if t not in M.GENERIC_WORDS and t not in M.AREA_TOKENS and not t.isdigit()]
        if not core or (len(core) == 1 and (len(core[0]) < 3 or word_df[core[0]] > AUTO_BRAND_COMMON)):
            continue
        key = " ".join(core[:3])
        scat = (T.BY_ID.get(p.cat).scat if T.BY_ID.get(p.cat) else None) or p.cat
        by_key[(key, scat)].append(p)
    out = {}
    members: dict[str, list[M.Place]] = defaultdict(list)
    for (key, _), ps in sorted(by_key.items()):
        members[key].extend(ps)
    for key, ps in sorted(members.items()):
        toks = key.split(" ")
        if descriptive and all(t in descriptive for t in toks):
            continue  # «كبابجي», «بصريات», «اعداديه»: what the place is, not whose
        # a chain OWNS its word: most names that carry it are its branches ("Abu Auf" 100 of ~100,
        # "GLC Paints" 155 of ~160); a descriptor is shared with thousands of other names
        # («اعداديه» 229 of ~3,000 schools, "burger" 128 of ~1,000)
        if len(ps) < AUTO_BRAND_OWN * min(word_df[t] for t in toks):
            continue
        # …and sells one kind of thing: "sky" is hotels, bars and cafés (34 % in its largest family),
        # "VIP" anything (24 %); Abu Auf, the most mixed real chain measured, is 57 % retail
        fam = Counter(M.family(q.cat) for q in ps)
        dom, n_dom = sorted(fam.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if n_dom < AUTO_BRAND_FAMILY * len(ps) or dom in NO_CHAIN_FAMILIES:
            continue
        ps = [q for q in ps if M.family(q.cat) == dom]
        if len(ps) >= AUTO_BRAND_MIN:
            # spread out: real chains have branches in different places, not one building's units
            govs = {q.gov for q in ps if q.gov}
            far = len(govs) >= 2 or any(R.haversine(ps[0].lat, ps[0].lng, q.lat, q.lng) > 20000 for q in ps[1:])
            if far:
                for q in ps:
                    out[q.pid] = "auto:" + key
    return out


# ── mentions: the fame signal we can measure ────────────────────────────────
# There are no review counts in open data. What there is: Egyptian businesses name themselves after
# the mall, the hospital, the street they are in or on — «سينابون سيتي ستارز», «صيدلية عباس العقاد»,
# "EGBANK - City Stars Branch". The number of OTHER places near a place that carry its distinctive
# name is how much of the city orients itself by it. A mall's shops, a hospital's pharmacies, a
# commercial street's storefronts (their address lines count) all raise it; a namesake café does not.

MENTION_R_POI = 600.0
MENTION_R_STREET = 1500.0
MENTION_SAT = 25
COMMON_NAME_WORDS = 400  # the most frequent name words nationally cannot carry a mention alone


def mentions(places: list[M.Place]) -> dict[str, int]:
    cell = 0.01  # ≈ 1.1 km
    # per cell: word → the places whose name / address carries it (the claim's rarest word drives)
    grid: dict[tuple[int, int], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    toks_of: list[frozenset] = []
    word_df: Counter = Counter()
    for i, p in enumerate(places):
        words = set()
        for txt in (p.name_ar, p.name_en, p.addr):
            if txt:
                words.update(tn.stems(t)[-1] for t in tn.tokens(txt) if not tn.is_stopword(t))
        toks_of.append(frozenset(words))
        word_df.update(words)
        g = grid[(int(p.lat // cell), int(p.lng // cell))]
        for w in words:
            g[w].append(i)
    common = {w for w, _ in word_df.most_common(COMMON_NAME_WORDS)}
    out: dict[str, int] = {}
    for i, p in enumerate(places):
        if p.kind == "area":
            continue
        core = set()
        for txt in (p.name_ar, p.name_en):
            if txt:
                core.update(tn.stems(t)[-1] for t in tn.tokens(txt) if not tn.is_stopword(t))
        core = {w for w in core if w not in M.GENERIC_WORDS and not w.isdigit() and len(w) >= 3}
        if not core:
            continue
        if len(core) == 1 and next(iter(core)) in common:
            continue
        r = MENTION_R_STREET if p.kind == "street" else max(MENTION_R_POI, min(p.extent_m, 1200.0))
        reach = int(r // (cell * 111000)) + 1
        ci, cj = int(p.lat // cell), int(p.lng // cell)
        # names in each script are separate claims: «سيتي ستارز» OR "city stars"
        claims = []
        for txt in (p.name_ar, p.name_en):
            if txt:
                c = {tn.stems(t)[-1] for t in tn.tokens(txt) if not tn.is_stopword(t)} & core
                if c:
                    claims.append((c, min(c, key=lambda w: (word_df[w], w))))
        hit: set[int] = set()
        for di in range(-reach, reach + 1):
            for dj in range(-reach, reach + 1):
                g = grid.get((ci + di, cj + dj))
                if not g:
                    continue
                for c, w in claims:
                    for k in g.get(w, ()):
                        if k == i or k in hit or not c <= toks_of[k]:
                            continue
                        q = places[k]
                        if R.haversine(p.lat, p.lng, q.lat, q.lng) <= r:
                            hit.add(k)
        if hit:
            out[p.pid] = len(hit)
    return out


def mention_boost(n: int) -> float:
    return 0.25 * min(1.0, math.log1p(n) / math.log1p(MENTION_SAT))
