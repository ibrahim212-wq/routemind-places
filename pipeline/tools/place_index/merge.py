"""Cross-source merge: which claims are the same place, and which claim wins each field.

DEDUPE — greedy, never transitive (union-find chains «Banque Misr» ATMs across a whole street):
records are visited in TRUST order (OSM → AllThePlaces → Foursquare → Microsoft → Meta → other;
inside a source by its own confidence) and each joins the best existing cluster that
  * is within the category's merge radius (RADIUS_M — 120 m for a shop, 400 m for a mall or a
    hospital campus, 2.5 km for an airport), and
  * shares a core name token (exact, one typo, or the cross-script consonant skeleton — «العزبي» ⇄
    «El Ezaby»), or the same phone number, and
  * passes `match_score` (name containment + category agreement + distance),
or else founds a new cluster. Core tokens drop the generic words (صيدلية, pharmacy, فرع, branch, …)
so «صيدلية العزبي» and «El Ezaby Pharmacy» compare on «عزبي» ⇄ «ezaby».

FIELD PRECEDENCE (per merged place; the first member that has the field wins)
  location   OSM → ATP → FSQ → MS → META    (OSM is placed on imagery; Meta pins are often the
                                             page's geocoded address)
  category   OSM → ATP → FSQ → MS → META    (a generic OSM tag yields to a specific one elsewhere)
  name (ar)  OSM name:ar / Arabic name → Wikidata → the cleanest Arabic name of the rest
  name (en)  OSM name:en / Latin name → Wikidata → ATP → MS → the cleanest Latin name of the rest
  phone      META → ATP → OSM → FSQ → MS    (a business's own page is the freshest number)
  website    ATP → OSM → META → FSQ → MS
  social     META → OSM → FSQ
  hours      OSM → FSQ                      (no other source carries hours)
  address    OSM → META → FSQ → MS

CONFIDENCE — the probability the place exists: 1 − Π(1 − cᵢ) over members, each source's
own claim calibrated (OSM 0.85 named, AllThePlaces 0.9, Foursquare by refresh date, Overture's
confidence for its rows). Two independent sources agreeing is the strongest evidence we have.

POPULARITY — 0..1, the stand-in for review counts we do not have: class importance (an
airport 1.0 … a kiosk 0.3), independent sources, Wikidata presence and sitelinks, contact
completeness, a chain brand, and the footprint of a mapped polygon.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from . import records as R
from . import taxonomy as T
from . import textnorm as tn

TRUST = {R.SRC_OSM: 0, R.SRC_WD: 1, R.SRC_ATP: 2, R.SRC_FSQ: 3, R.SRC_MS: 4, R.SRC_META: 5,
         R.SRC_OVT_OTHER: 6, R.SRC_DIV: 1, R.SRC_GN: 7}

BIG = {"mall": 450, "hypermarket": 300, "hospital": 400, "university": 900, "college": 500, "airport": 2500,
       "stadium": 500, "park": 500, "zoo": 600, "historic_site": 500, "attraction": 500, "museum": 300,
       "hotel": 300, "resort": 700, "train_station": 400, "port": 1500, "beach": 800, "compound": 900,
       "cemetery": 600, "sports_club": 450, "amusement_park": 600, "industrial_zone": 2000, "monastery": 400,
       "school": 220, "government": 250, "ministry": 300, "market": 300, "camp_site": 500, "military": 1500,
       "mountain": 3000, "island": 2000, "lake": 3000, "natural": 2000, "bridge": 600, "square": 300,
       "medical_center": 200, "factory": 400, "embassy": 200, "courthouse": 200}
DEFAULT_RADIUS = 120.0

# Category groups that may describe the same place (Meta files a clinic as a hospital, a café as
# a coffee shop, a mall's food court as a restaurant …).
GROUPS = [
    {"hospital", "emergency_room", "clinic", "medical_center", "doctor", "dental_clinic", "medical_lab", "radiology",
     "physiotherapy", "eye_clinic", "health_unit"},
    {"cafe", "coffee_shop", "ahwa", "lounge", "juice_bar", "ice_cream", "sweets", "bakery"},
    {"restaurant", "fast_food", "koshary", "grill", "seafood", "pizza", "burger", "chicken", "foul_taameya",
     "shawarma", "food_court"},
    {"supermarket", "hypermarket", "grocery", "convenience", "kiosk", "market", "department_store", "mall"},
    {"clothes", "womens_clothes", "mens_clothes", "kids_clothes", "bridal", "shoes", "bags", "sportswear",
     "jewelry", "watches", "perfume", "cosmetics", "optician"},
    {"electronics", "computer_store", "appliances", "mobile_shop", "telecom", "phone_repair", "appliance_repair"},
    {"furniture", "home_goods", "hardware", "paint", "building_materials", "sanitary", "lighting", "carpet", "fabric"},
    {"car_repair", "car_wash", "tyre_shop", "oil_change", "car_battery", "auto_parts", "car_dealer", "gas_station",
     "motorcycle_shop", "car_rental"},
    {"school", "kindergarten", "university", "college", "institute", "language_school", "training_center", "tutoring"},
    {"bank", "atm", "exchange", "financial_service", "insurance", "money_transfer"},
    {"hotel", "resort", "hostel", "apartment_hotel", "camp_site"},
    {"park", "garden", "playground", "zoo", "amusement_park"},
    {"historic_site", "monument", "attraction", "museum", "viewpoint", "landmark", "mosque", "church",
     "monastery", "place_of_worship"},
    {"government", "townhall", "ministry", "police", "traffic_department", "civil_registry", "notary",
     "courthouse", "post_office", "telecom_exchange", "electricity_office", "water_office"},
    {"sports_club", "stadium", "gym", "swimming_pool", "sports_field"},
    {"barber", "hair_salon", "beauty_salon", "spa"},
    {"bus_station", "bus_stop", "microbus_stand", "train_station", "metro_station", "lrt_station",
     "monorail_station"},
]
# Families: a fine category in one family never describes a place filed in another, except
# through the family's own generic category (a Meta "shop" can be a pharmacy; it is never a hotel).
FAMILY_OF_GROUP = {0: "health", 1: "food", 2: "food", 3: "retail", 4: "retail", 5: "retail", 6: "retail",
                   7: "auto", 8: "edu", 9: "money", 10: "lodging", 11: "leisure", 12: "culture", 13: "gov",
                   14: "leisure", 15: "services", 16: "transport"}
FAMILY_GENERIC = {"shop": {"retail", "food", "health", "auto", "services"}, "service": {"services", "auto", "retail"},
                  "office": {"business", "services", "money", "gov"}, "company": {"business", "services", "money"},
                  "tech_company": {"business", "services"}}
UNIVERSAL_CATS = {"place", "building", "tower", "natural"}
GENERIC_CATS = UNIVERSAL_CATS | set(FAMILY_GENERIC)
_GROUP_OF: dict[str, int] = {}
for gi, g in enumerate(GROUPS):
    for c in g:
        _GROUP_OF.setdefault(c, gi)


def family(cat: str) -> str:
    g = _GROUP_OF.get(cat)
    if g is not None:
        return FAMILY_OF_GROUP[g]
    if cat in ("office", "company", "tech_company", "coworking", "factory", "warehouse", "shipping", "advertising",
               "lawyer", "accountant", "real_estate", "developer", "travel_agency", "ngo", "construction"):
        return "business"
    return "other:" + cat


def cats_compatible(a: str, b: str) -> bool:
    if a == b or a in UNIVERSAL_CATS or b in UNIVERSAL_CATS:
        return True
    ga, gb = _GROUP_OF.get(a), _GROUP_OF.get(b)
    if ga is not None and ga == gb:
        return True
    if a in FAMILY_GENERIC and family(b) in FAMILY_GENERIC[a]:
        return True
    if b in FAMILY_GENERIC and family(a) in FAMILY_GENERIC[b]:
        return True
    return False


# Words that say WHAT a place is, not WHICH one — they do not identify a place.
GENERIC_WORDS_RAW = """
صيدلية صيدليات صيدليه اجزخانة pharmacy pharmacies pharma مستشفى مستشفي مستشفيات hospital hospitals
عيادة عيادات عياده clinic clinics مركز center centre طبي طبية medical مجمع complex مطعم مطاعم restaurant
restaurants كافيه كافية كافي قهوة قهوه cafe coffee café shop store stores محل محلات معرض معارض showroom
فرع branch branches شركة شركه company co ltd llc inc group جروب مجموعة مؤسسة foundation est بنك bank
سوبر ماركت ماركت supermarket market هايبر hyper mart مول mall محطة محطه station بنزين بنزينة وقود fuel gas
petrol فندق hotel مدرسة مدرسه school جامعة جامعه university كلية كليه college معهد institute جيم gym
نادي club مسجد جامع mosque كنيسة church شارع street st طريق road ميدان square the and el al of فى في
suites suite apartments apartment hotel resort بيوتي beauty salon صالون center مراكز
faculty كليه كلية department قسم ادارة إدارة administration unit وحدة univ dr د دكتور doctor
optics optical store trading services service express
""".split()
GENERIC_WORDS = set()
for _w in GENERIC_WORDS_RAW + [x for c in T.CATS if c.id not in T.AREA_CATS for x in (c.en, c.ar)]:
    for _t in tn.tokens(_w):
        GENERIC_WORDS.update(tn.stems(_t))
# a few labels are also real name words people search for — keep them identifying
GENERIC_WORDS -= {"مصر", "misr", "egypt", "cairo", "قاهره", "القاهره", "city", "مدينه"}

# Tokens that name an AREA («المعادي», «السيوف», «maadi») identify a place only weakly: two
# businesses in one neighbourhood share them. merge.set_area_tokens fills this from the areas.
AREA_TOKENS: set[str] = set()
AREA_SKELS: set[str] = set()
AREA_WEIGHT = 0.35


def set_area_tokens(area_names: list[str]) -> None:
    for name in area_names:
        for t in tn.tokens(name):
            if tn.is_stopword(t):
                continue
            st = tn.stems(t)
            if any(x in GENERIC_WORDS for x in st):
                continue
            AREA_TOKENS.update(st)
            for sk in tn.skeletons(t):
                if len(sk) >= 3:
                    AREA_SKELS.add(sk)


@dataclass
class Prep:
    rec: R.Record
    forms: tuple            # per name: (core stems, skeletons ≥ 3 symbols), identical pairs dropped
    core: frozenset         # union of every name's core stems (candidate filter, emptiness test)
    skel: frozenset
    phone: str | None
    lat: float
    lng: float


def name_forms(text: str) -> tuple[frozenset, frozenset]:
    core: set[str] = set()
    skel: set[str] = set()
    for t in tn.tokens(text):
        if tn.is_stopword(t) or (t.isdigit() and len(t) < 2):
            continue
        st = tn.stems(t)
        if any(x in GENERIC_WORDS for x in st):
            continue
        core.update(st)
        for sk in tn.skeletons(t):
            if len(sk) >= 3:
                skel.add(sk)
    return frozenset(core), frozenset(skel)


def prep(rec: R.Record) -> Prep:
    forms = []
    for text, role in rec.names:
        if role == "operator":
            continue
        f = name_forms(text)
        if (f[0] or f[1]) and f not in forms:
            forms.append(f)
    core = frozenset().union(*[f[0] for f in forms]) if forms else frozenset()
    skel = frozenset().union(*[f[1] for f in forms]) if forms else frozenset()
    return Prep(rec, tuple(forms), core, skel, R.phone_key(rec.phone), rec.lat, rec.lng)


def _containment(a: frozenset, b: frozenset, fuzzy: bool, weak: set) -> float:
    """Weighted containment of the smaller token set in the larger. Tokens that name an AREA
    count AREA_WEIGHT; when the only agreement is an area word while the other name carries
    words of its own («قهوة السيوف» vs «محمد علي كافيه السيوف») the evidence is halved."""
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    w = lambda t: AREA_WEIGHT if t in weak else 1.0
    hit = 0.0
    strong = False
    matched_big: set = set()
    for t in small:
        u_hit = t if t in big else None
        if u_hit is None and fuzzy:
            lt = tn.loose(t)
            if len(lt) >= 2:
                u_hit = next((u for u in big if tn.loose(u) == lt), None)
        if u_hit is None and fuzzy and len(t) >= 5:
            u_hit = next((u for u in big if abs(len(t) - len(u)) <= 1 and tn.damerau(t, u, 1) <= 1), None)
        if u_hit is not None:
            hit += w(t)
            matched_big.add(u_hit)
            strong = strong or t not in weak
    ts = sum(w(t) for t in small)
    tb = sum(w(t) for t in big)
    if ts == 0 or hit == 0:
        return 0.0
    c = (hit / ts) * (0.6 + 0.4 * min(1.0, hit / tb))
    if not strong and any(u not in weak and u not in matched_big for u in big):
        c *= 0.5
    return c


def name_similarity(a: Prep, b: Prep) -> float:
    best = 0.0
    for ca, sa in a.forms:
        for cb, sb in b.forms:
            s1 = _containment(ca, cb, True, AREA_TOKENS)
            s2 = _containment(sa, sb, False, AREA_SKELS) * 0.92
            if s1 > best:
                best = s1
            if s2 > best:
                best = s2
            if best >= 0.999:
                return best
    return best


def radius_for(cat_a: str, cat_b: str) -> float:
    return max(BIG.get(cat_a, DEFAULT_RADIUS), BIG.get(cat_b, DEFAULT_RADIUS))


def match_score(a: Prep, b: Prep, dist: float) -> float:
    """0 = different places; ≥ MATCH = the same place."""
    ra, rb = a.rec, b.rec
    r = radius_for(ra.cat, rb.cat)
    if dist > r:
        return 0.0
    near = 1.0 - dist / r
    compatible = cats_compatible(ra.cat, rb.cat)
    same_source = ra.src == rb.src
    if a.phone and a.phone == b.phone and compatible and not same_source:
        # a shared number alone is a mall's or a chain's switchboard; it needs a name that agrees
        # (or a nameless side) to say "same place"
        if not a.core or not b.core or name_similarity(a, b) >= 0.3:
            return 0.9 + 0.1 * near
    if not a.core and not b.core:
        # both nameless or generic-only («صيدلية», an unnamed fuel station): same category, very close
        if ra.cat == rb.cat and dist < 35 and not same_source:
            return 0.8
        return 0.0
    sim = name_similarity(a, b)
    if sim == 0:
        return 0.0
    if not compatible:
        # the very same name, a few metres apart, across a category disagreement (Meta files a
        # kite school as a shop) — but a hospital and the pharmacy inside it stay two places
        if sim >= 0.95 and dist < 60 and not same_source and (ra.cat in GENERIC_CATS or rb.cat in GENERIC_CATS):
            return 0.75
        return 0.0
    if same_source:
        # a source rarely lists one place twice; OSM's node + way duplicates have the same name
        return 0.8 if sim >= 0.95 and dist < r / 2 else 0.0
    same_cat = 1.0 if ra.cat == rb.cat else 0.6
    return sim * (0.75 + 0.15 * near + 0.10 * same_cat)


MATCH = 0.72


@dataclass
class Cluster:
    members: list[Prep] = field(default_factory=list)

    @property
    def head(self) -> Prep:
        return self.members[0]


def _trust_key(p: Prep):
    return (TRUST.get(p.rec.src, 9), -p.rec.conf)


CELL = 0.0025  # ≈ 250 m


def dedupe(recs: list[R.Record], cell: float = CELL) -> list[Cluster]:
    preps = sorted((prep(r) for r in recs), key=_trust_key)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    clusters: list[Cluster] = []
    # per cluster, the union of member keys (for the cheap candidate filter)
    ckeys: list[set] = []
    for p in preps:
        cx, cy = int(math.floor(p.lng / cell)), int(math.floor(p.lat / cell))
        reach = max(1, int(math.ceil(radius_for(p.rec.cat, p.rec.cat) / (cell * 111000))))
        keys = set(p.core) | set("~" + s for s in p.skel)
        if p.phone:
            keys.add("☎" + p.phone)
        best, best_s = None, 0.0
        seen = set()
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for ci in grid.get((cx + dx, cy + dy), ()):
                    if ci in seen:
                        continue
                    seen.add(ci)
                    if keys and not (keys & ckeys[ci]) and (p.core or clusters[ci].head.core):
                        continue
                    s_best = 0.0
                    for mi, m in enumerate(clusters[ci].members):
                        d = R.haversine(p.lat, p.lng, m.lat, m.lng)
                        s = match_score(p, m, d) * (1.0 if mi == 0 else 0.92)
                        if s > s_best:
                            s_best = s
                    if s_best > best_s:
                        best, best_s = ci, s_best
        if best is not None and best_s >= MATCH:
            clusters[best].members.append(p)
            ckeys[best] |= keys
        else:
            clusters.append(Cluster([p]))
            ckeys.append(set(keys))
            grid[(cx, cy)].append(len(clusters) - 1)
    return clusters


# ── the merged place ─────────────────────────────────────────────────────────

@dataclass
class Place:
    pid: str
    kind: str
    cat: str
    lat: float
    lng: float
    name_ar: str | None
    name_en: str | None
    alt: list[str]
    brand: str | None
    phone: str | None
    website: str | None
    social: str | None
    hours: str | None
    addr: str | None
    wd: str | None
    srcs: int
    conf: float
    pop: float
    extent_m: float
    population: int
    members: list[str]
    closed: bool = False
    gov: str | None = None
    area_ar: str | None = None
    area_en: str | None = None
    brand_key: str | None = None
    grp: str | None = None


ORDER_LOC = [R.SRC_OSM, R.SRC_WD, R.SRC_ATP, R.SRC_FSQ, R.SRC_MS, R.SRC_META, R.SRC_OVT_OTHER, R.SRC_DIV, R.SRC_GN]
ORDER_PHONE = [R.SRC_META, R.SRC_ATP, R.SRC_OSM, R.SRC_FSQ, R.SRC_MS, R.SRC_OVT_OTHER]
ORDER_WEB = [R.SRC_ATP, R.SRC_OSM, R.SRC_META, R.SRC_FSQ, R.SRC_MS, R.SRC_OVT_OTHER, R.SRC_WD]
ORDER_SOCIAL = [R.SRC_META, R.SRC_OSM, R.SRC_FSQ]
ORDER_ADDR = [R.SRC_OSM, R.SRC_META, R.SRC_FSQ, R.SRC_MS, R.SRC_ATP, R.SRC_OVT_OTHER]


def _by(order, members, getter):
    rank = {s: i for i, s in enumerate(order)}
    best = None
    for m in sorted(members, key=lambda p: (rank.get(p.rec.src, 99), -p.rec.conf)):
        v = getter(m.rec)
        if v:
            return v
    return best


def _clean_score(name: str) -> float:
    """Lower is cleaner: short, few separators, no 'branch' / phone-number noise."""
    n = len(name)
    seps = sum(name.count(c) for c in "-|/()•،,")
    digits = sum(c.isdigit() for c in name)
    noise = sum(1 for w in ("فرع", "branch", "official", "الرسمية", "page", "صفحة") if w in name.lower())
    return n + 12 * seps + 2 * digits + 25 * noise


def _pick_name(members: list[Prep], script: str) -> str | None:
    want_roles_first = ("ar",) if script == "ar" else ("en",)
    rank = {s: i for i, s in enumerate(ORDER_LOC)}
    # 1. OSM / Wikidata: language-tagged name, else the primary in that script
    for src in (R.SRC_OSM, R.SRC_DIV, R.SRC_WD):
        for m in members:
            if m.rec.src != src:
                continue
            for text, role in m.rec.names:
                if role in want_roles_first:
                    return R.tidy_name(text)
            for text, role in m.rec.names:
                if role == "primary" and tn.script_of(tn.normalize(text)) == script:
                    return R.tidy_name(text)
    # 2. the cleanest name in that script among the rest
    cands = []
    for m in members:
        for text, role in m.rec.names:
            if role in ("operator", "old"):
                continue
            if tn.script_of(tn.normalize(text)) == script:
                cands.append((_clean_score(text), rank.get(m.rec.src, 9), text))
    if not cands:
        return None
    cands.sort()
    return R.tidy_name(cands[0][2])


SOURCE_CONF = {R.SRC_OSM: None, R.SRC_ATP: 0.9, R.SRC_WD: 0.9, R.SRC_DIV: 0.9}


def place_conf(members: list[Prep]) -> float:
    miss = 1.0
    seen_src = set()
    for m in members:
        c = m.rec.conf
        if m.rec.src in seen_src:
            c *= 0.35  # a second row from the SAME source is weak evidence
        seen_src.add(m.rec.src)
        miss *= (1.0 - max(0.0, min(0.98, c)))
    return round(1.0 - miss, 3)


def popularity(cat: str, members: list[Prep], p: "Place") -> float:
    c = T.BY_ID.get(cat)
    base = (c.prom if c else 0.4) * 0.40
    srcs = {m.rec.src for m in members} - {R.SRC_DIV}
    s = base + min(0.2, 0.08 * (len(srcs) - 1))
    sitelinks = max((m.rec.extra.get("sitelinks", 0) for m in members), default=0)
    if p.wd:
        s += 0.10
    if sitelinks:
        s += 0.15 * min(1.0, math.log1p(sitelinks) / math.log(60))
    if any(m.rec.extra.get("wikipedia") for m in members):
        s += 0.05
    s += 0.03 * bool(p.phone) + 0.03 * bool(p.website) + 0.02 * bool(p.social) + 0.03 * bool(p.hours)
    ovc = max((m.rec.conf for m in members if m.rec.src in (R.SRC_META, R.SRC_MS, R.SRC_FSQ)), default=0)
    s += 0.08 * ovc
    area = max((m.rec.extra.get("area_m2", 0.0) for m in members), default=0.0)
    if area > 300:
        s += 0.10 * min(1.0, math.log10(area / 300) / 3.0)
    if p.kind == "area" and p.population:
        s += 0.15 * min(1.0, math.log10(max(1, p.population)) / 6.5)
    return round(max(0.0, min(1.0, s)), 3)


def compact_uuid(hexid: str, prefix: str) -> str:
    """A GERS / Foursquare hex id → prefix + 12 url-safe characters (72 bits: no collision in a
    country's million rows, a third of the bytes)."""
    import base64
    h = "".join(c for c in hexid.lower() if c in "0123456789abcdef")
    raw = bytes.fromhex(h[:18].ljust(18, "0"))
    return prefix + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def anchor_id(members: list[Prep]) -> str:
    """The merged place's stable id: its most durable member's id. OSM ids stay readable
    (n123 / w123 / r123); Overture / Foursquare / divisions are compacted."""
    rank = {R.SRC_OSM: 0, R.SRC_DIV: 1, R.SRC_WD: 2, R.SRC_ATP: 3, R.SRC_META: 4, R.SRC_MS: 4, R.SRC_FSQ: 4,
            R.SRC_OVT_OTHER: 4, R.SRC_GN: 5}
    m = min(members, key=lambda p: (rank.get(p.rec.src, 9), -p.rec.conf))
    r = m.rec
    if r.src == R.SRC_OSM:
        return r.sid
    if r.src in (R.SRC_META, R.SRC_MS, R.SRC_ATP, R.SRC_OVT_OTHER) or (r.src == R.SRC_FSQ and r.extra.get("ovt_id")):
        return compact_uuid(r.extra.get("ovt_id") or r.sid, "v")
    if r.src == R.SRC_FSQ:
        return compact_uuid(r.sid, "f")
    if r.src == R.SRC_DIV:
        return compact_uuid(r.sid, "d")
    if r.src == R.SRC_WD:
        return "q" + r.sid.lstrip("Q")
    return "g" + r.sid


def build_place(cl: Cluster) -> Place:
    ms = cl.members
    loc = _by(ORDER_LOC, ms, lambda r: (r.lat, r.lng))
    cat = None
    for src in ORDER_LOC:
        for m in ms:
            if m.rec.src == src and m.rec.cat not in GENERIC_CATS:
                cat = cat or m.rec.cat
    cat = cat or ms[0].rec.cat
    name_ar = _pick_name(ms, "ar")
    name_en = _pick_name(ms, "latin")
    seen = {tn.normalize(x) for x in (name_ar, name_en) if x}
    covered = {s for x in (name_ar, name_en) if x for t in tn.tokens(x) for s in tn.stems(t)}
    alt = []
    for m in ms:
        for text, role in m.rec.names:
            if role == "operator":
                continue
            k = tn.normalize(text)
            if not k or k in seen:
                continue
            seen.add(k)
            words = {tn.stems(t)[-1] for t in tn.tokens(text) if not tn.is_stopword(t)}
            if words and words <= covered:
                continue  # says nothing the two display names do not already say
            covered |= {s for t in tn.tokens(text) for s in tn.stems(t)}
            alt.append(text)
    srcs = 0
    for m in ms:
        srcs |= R.SOURCE_BITS.get(m.rec.src, 0)
    p = Place(
        pid=anchor_id(ms), kind=ms[0].rec.kind, cat=cat, lat=round(loc[0], 6), lng=round(loc[1], 6),
        name_ar=name_ar, name_en=name_en, alt=alt[:6],
        brand=_by(ORDER_WEB, ms, lambda r: r.brand),
        phone=_by(ORDER_PHONE, ms, lambda r: r.phone),
        website=_by(ORDER_WEB, ms, lambda r: r.website),
        social=_by(ORDER_SOCIAL, ms, lambda r: r.social),
        hours=_by([R.SRC_OSM, R.SRC_FSQ], ms, lambda r: r.hours),
        addr=_by(ORDER_ADDR, ms, lambda r: r.addr),
        wd=_by(ORDER_LOC, ms, lambda r: r.wd),
        srcs=srcs, conf=place_conf(ms), pop=0.0,
        extent_m=max(m.rec.extent_m for m in ms), population=max(m.rec.population for m in ms),
        members=[m.rec.key for m in ms], closed=all(m.rec.closed for m in ms),
    )
    p.pop = popularity(cat, ms, p)
    return p


def merge(recs: list[R.Record]) -> list[Place]:
    pois = [r for r in recs if r.kind == "poi"]
    areas = [r for r in recs if r.kind == "area"]
    out = [build_place(c) for c in dedupe(pois)]
    out += merge_areas(areas)
    return out


# ── areas ────────────────────────────────────────────────────────────────────

AREA_RADIUS = {"governorate": 60000, "city": 9000, "town": 6000, "district": 4000, "markaz": 12000,
               "neighbourhood": 1500, "village": 2500, "hamlet": 1200}


def merge_areas(recs: list[R.Record]) -> list[Place]:
    preps = sorted((prep(r) for r in recs), key=_trust_key)
    clusters: list[Cluster] = []
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = 0.05
    for p in preps:
        cx, cy = int(p.lng // cell), int(p.lat // cell)
        r = AREA_RADIUS.get(p.rec.cat, 2000)
        reach = max(1, int(math.ceil(r / (cell * 111000))))
        best, best_s = None, 0.0
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for ci in grid.get((cx + dx, cy + dy), ()):
                    h = clusters[ci].head
                    rr = max(r, AREA_RADIUS.get(h.rec.cat, 2000))
                    d = R.haversine(p.lat, p.lng, h.lat, h.lng)
                    if d > rr:
                        continue
                    # a governorate never merges with its capital city, a markaz with its town
                    lvl = {"governorate": 0, "markaz": 1}
                    if lvl.get(p.rec.cat, 2) != lvl.get(h.rec.cat, 2):
                        continue
                    sim = max(name_similarity(p, m) for m in clusters[ci].members)
                    if not p.core and not h.core:
                        continue
                    s = sim * (0.8 + 0.2 * (1 - d / rr))
                    if s > best_s:
                        best, best_s = ci, s
        if best is not None and best_s >= 0.8:
            clusters[best].members.append(p)
        else:
            clusters.append(Cluster([p]))
            grid[(cx, cy)].append(len(clusters) - 1)
    out = []
    for c in clusters:
        pl = build_place(c)
        pl.kind = "area"
        # the most specific settlement class any source gives, preferring OSM's
        pl.cat = c.head.rec.cat
        out.append(pl)
    return out
