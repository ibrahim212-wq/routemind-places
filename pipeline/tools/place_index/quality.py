"""Place quality passes over the merged places (docs/place-search-2026-10.md §13), run by build.py after the brands.

lend_names   a chain's branch that has a name in one script only takes the chain's name in the other: the lexicon's
             display name, or — for a chain the index found itself — the name most of its own branches carry. Reliable
             (the branch IS the chain), so it is a real, displayed name: an Arabic search lists «بازوكا», not
             "Bazooka Fried Chicken".
police       a place whose own name says it is a police station («قسم شرطة …», «قسم ثان المحلة», «مركز شرطة …»,
             «مديرية أمن …», "… police station") is filed as one, whatever civic office it was merged with.
contain      the mall / compound / campus a place stands in (`inside`, the subtitle «جوه Cloud 9»): the smallest mapped
             footprint holding it, or a mall its own address names nearby. A mall several shops' addresses name where
             no mall record exists becomes a place of its own, at their median point (DERIVED_BIT).
locate       positions the sources contradict: one distinctive name at points far apart, where exactly one is
             corroborated (two sources, or OSM) — the uncorroborated copies lose confidence; a single-source pin whose
             address names another governorate loses confidence. Nothing is moved: the pin we cannot check stays where
             its source put it, ranked below the one we can.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

from . import merge as M
from . import records as R
from . import taxonomy as T
from . import textnorm as tn

# not a source: a `srcs` flag on a place this build DERIVED from other places (a mall named by its shops' addresses)
DERIVED_BIT = 2048


def _scat(p: M.Place) -> str | None:
    c = T.BY_ID.get(p.cat)
    return c.scat if c else None


def _hav(a_lat, a_lng, b_lat, b_lng) -> float:
    r = math.pi / 180
    p1, p2 = a_lat * r, b_lat * r
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((b_lng - a_lng) * r / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(h)))


def _script(text: str) -> str:
    return "ar" if tn.is_arabic_token(tn.normalize(text).replace(" ", "")) else "la"


# ── names of a chain ───────────────────────────────────────────────────────────

def lend_names(places: list[M.Place], lexicon: dict, report: dict) -> None:
    lex = {b["id"]: (b.get("display_ar"), b.get("display_en")) for b in lexicon.get("brands", [])}
    branches: dict[str, list[M.Place]] = defaultdict(list)
    for p in places:
        if p.kind == "poi" and p.brand_key:
            branches[p.brand_key].append(p)
    lent = Counter()
    for key, ps in branches.items():
        ar, en = lex.get(key, (None, None))
        if not ar or not en:
            # a chain the index found itself: the name most of its branches carry, when most agree (≥ 3, ≥ 50 %)
            for script, have in (("ar", ar), ("en", en)):
                if have:
                    continue
                votes = Counter(n for n in ((q.name_ar if script == "ar" else q.name_en) for q in ps) if n)
                if votes:
                    name, k = votes.most_common(1)[0]
                    if k >= 3 and k >= 0.5 * sum(votes.values()):
                        if script == "ar":
                            ar = name
                        else:
                            en = name
        for p in ps:
            if not p.name_ar and ar:
                p.name_ar = ar
                lent["ar"] += 1
            if not p.name_en and en:
                p.name_en = en
                lent["en"] += 1
    report["chain_names_lent"] = dict(lent)


# ── police stations by their own name ───────────────────────────────────────────

_ORDINALS = {"اول", "ثان", "ثاني", "تاني", "ثالث", "تالت", "رابع", "خامس", "سادس", "سابع", "ثامن", "تاسع", "عاشر"}
_CIVIC = {"civil_registry", "post_office", "government", "townhall", "office", "place", "landmark", "company",
          "notary", "courthouse", "traffic_department", "ngo"}


def says_police(names: list[str]) -> bool:
    for nm in names:
        w = [tn.stems(t)[-1] for t in tn.tokens(nm) if not tn.is_stopword(t)]
        s = set(w)
        if {"قسم", "شرطه"} <= s or {"مركز", "شرطه"} <= s or {"نقطه", "شرطه"} <= s or {"مديريه", "امن"} <= s \
                or {"police", "station"} <= s or {"police", "department"} <= s:
            return True
        # «قسم ثان المحلة», «قسم أول طنطا»: a division by its ordinal is its police station's name
        if len(w) >= 2 and w[0] == "قسم" and (w[1] in _ORDINALS or tn.is_digits(w[1])):
            return True
    return False


def police(places: list[M.Place], report: dict) -> None:
    n = 0
    for p in places:
        if p.kind == "poi" and p.cat in _CIVIC and says_police([x for x in (p.name_ar, p.name_en) if x]):
            p.cat = "police"
            n += 1
    report["police_by_name"] = n


# ── containment ───────────────────────────────────────────────────────────────

# A footprint is kept as a circle (`ext`): around a hospital, an airport or a club that circle holds the streets beside it
# (measured on places-2026-10-31: GAFI "inside" Abbasseya hospital, a clinic "inside" Almaza airport), so only malls and
# compounds contain, and only within these radii.
CONTAINER_MAX_M = {"mall": 600.0, "compound": 1500.0}
DERIVE_FAR_M = 20000.0       # a mall of that name on record this near: shops naming it are just pinned off it
MALL_NAME_M = 1500.0         # a mall a shop's address names counts within this distance
DERIVE_MIN = 3               # this many places naming one mall nearby, and no such mall on record → a mall
_MALL_WORDS = {"mall", "مول", "mol", "plaza", "بلازا"}
_SEP = re.compile(r"[-,،|/()\[\];؛:\n]+")
_STOP_AFTER = {"مدخل", "الدور", "دور", "بجوار", "امام", "خلف", "شارع", "ش", "محل", "floor", "entrance", "shop", "unit",
               "مبني", "مبنى", "building", "بوابه", "gate", "مدينه", "city", "الشيخ", "قسم", "محافظه", "street", "st",
               "road", "rd", "branch", "فرع"}
_STOP_BEFORE = {"of", "to", "at", "in", "inside", "near", "beside", "behind", "opposite", "next", "front", "by", "from",
                "floor", "level", "unit", "shop", "store", "branch", "gate", "entrance", "ground", "the", "street", "st",
                "road", "rd", "axis", "city"}


def mall_key(phrase: str) -> str | None:
    """The canonical key of a mall's own name («كلاود 5» / "cloud nine" → its words, numbers as digits), None when
    nothing distinctive is left."""
    out = []
    for t in tn.tokens(phrase):
        if t in _STOP_AFTER:
            break
        if tn.is_stopword(t) or t in _MALL_WORDS:
            continue
        v = tn.number_value(t)
        out.append(v if v is not None else tn.stems(t)[-1])
    if not out or len(out) > 4 or sum(len(x) for x in out) < 3:
        return None
    return " ".join(out)


def mall_mentions(text: str | None) -> list[tuple[str, str]]:
    """(key, the name as written) for every mall a text names: "… Cloud Nine Mall, …", "in front of Diamond Mall",
    "Mall of Arabia", «مبنى b1 مول كلاود 5 مدخل 5». Punctuation ends a name ("Rehab City - Cloud 9 Mall" → Cloud 9)."""
    if not text:
        return []
    out = []
    for seg in _SEP.split(text):
        toks = tn.tokens(seg)
        for i, t in enumerate(toks):
            words = []
            if t in ("mall", "plaza"):
                j = i - 1
                while j >= 0 and len(words) < 3 and toks[j] not in _STOP_BEFORE and not tn.is_arabic_token(toks[j])                         and toks[j] not in _MALL_WORDS:
                    words.insert(0, toks[j])
                    j -= 1
                phrase = " ".join(words + [t])
                if not words and i + 2 < len(toks) and toks[i + 1] == "of":
                    words = [x for x in toks[i + 2:i + 4] if x not in _STOP_AFTER][:2]
                    phrase = " ".join([t, "of"] + words)
            elif t in ("مول", "بلازا"):
                j = i + 1
                while j < len(toks) and len(words) < 3 and toks[j] not in _STOP_AFTER and toks[j] not in _MALL_WORDS:
                    words.append(toks[j])
                    j += 1
                phrase = " ".join([t] + words)
            else:
                continue
            k = mall_key(" ".join(words)) if words else None
            if k:
                out.append((k, phrase))
    return out


def _cell(lat: float, lng: float, size: float = 0.02) -> tuple[int, int]:
    return int(math.floor(lat / size)), int(math.floor(lng / size))


def _label(p: M.Place) -> str:
    return (p.name_ar or "") + "\x1f" + (p.name_en or "")


def contain(places: list[M.Place], report: dict) -> list[M.Place]:
    """Sets `inside` and returns the derived malls (to be added to the places)."""
    pois = [p for p in places if p.kind == "poi"]
    containers = [p for p in pois if _scat(p) in CONTAINER_MAX_M and 0 < p.extent_m <= CONTAINER_MAX_M[_scat(p)]
                  and (p.name_ar or p.name_en)]
    grid: dict[tuple[int, int], list[M.Place]] = defaultdict(list)
    for c in containers:
        reach = c.extent_m / 111000.0
        a0, b0 = _cell(c.lat - reach, c.lng - reach)
        a1, b1 = _cell(c.lat + reach, c.lng + reach)
        for a in range(a0, a1 + 1):
            for b in range(b0, b1 + 1):
                grid[(a, b)].append(c)
    # malls on record by key, for the addresses
    by_key: dict[str, list[M.Place]] = defaultdict(list)
    for p in pois:
        if _scat(p) == "mall":
            for nm in (p.name_ar, p.name_en):
                if nm:
                    k = mall_key(nm)
                    if k:
                        by_key[k].append(p)
    inside_fp = inside_addr = 0
    named: dict[str, list[tuple[M.Place, str]]] = defaultdict(list)
    for p in pois:
        if _scat(p) in ("mall", "compound", "university", "airport"):
            continue
        best = None
        for c in grid.get(_cell(p.lat, p.lng), ()):
            if c is p:
                continue
            d = _hav(p.lat, p.lng, c.lat, c.lng)
            if d <= c.extent_m and (best is None or c.extent_m < best.extent_m):
                best = c
        if best is not None:
            p.inside = _label(best)
            inside_fp += 1
            continue
        texts = [p.addr] + [x for x in (p.name_ar, p.name_en) if x]
        for t in texts:
            hit = False
            for k, phrase in mall_mentions(t):
                rec = [m for m in by_key.get(k, ()) if _hav(p.lat, p.lng, m.lat, m.lng) <= MALL_NAME_M]
                if rec:
                    m = min(rec, key=lambda m: _hav(p.lat, p.lng, m.lat, m.lng))
                    if m is not p:
                        p.inside = _label(m)
                        inside_addr += 1
                        hit = True
                        break
                elif not any(_hav(p.lat, p.lng, m.lat, m.lng) <= DERIVE_FAR_M for m in by_key.get(k, ())):
                    named[k].append((p, phrase))  # "Mall of Arabia" 5 km off is a mis-pinned shop, not a second mall
            if hit:
                break
    # a mall named by several places' addresses, nowhere on record: the places' own consensus, at their median
    derived = []
    for k, rows in sorted(named.items()):
        groups: list[list[tuple[M.Place, str]]] = []
        for p, phrase in sorted(rows, key=lambda r: (r[0].lat, r[0].lng, r[0].pid)):
            for g in groups:
                if _hav(p.lat, p.lng, g[0][0].lat, g[0][0].lng) <= MALL_NAME_M:
                    g.append((p, phrase))
                    break
            else:
                groups.append([(p, phrase)])
        for g in groups:
            uniq = {p.pid: (p, ph) for p, ph in g}
            if len(uniq) < DERIVE_MIN:
                continue
            ps = [p for p, _ in uniq.values()]
            lat = sorted(p.lat for p in ps)[len(ps) // 2]
            lng = sorted(p.lng for p in ps)[len(ps) // 2]
            spell = Counter(ph for _, ph in uniq.values())
            ar = next((s for s, _ in spell.most_common() if _script(s) == "ar"), None)
            en = next((s for s, _ in spell.most_common() if _script(s) == "la"), None)
            name_ar = ar.strip() if ar else None
            name_en = " ".join(w.capitalize() for w in en.split()) if en else None
            mall = M.Place(pid="d" + hashlib.sha1(f"{k}|{lat:.4f}|{lng:.4f}".encode("utf-8")).hexdigest()[:14],
                           kind="poi", cat="mall", lat=lat, lng=lng, name_ar=name_ar, name_en=name_en, alt=[],
                           brand=None, phone=None, website=None, social=None, hours=None, addr=None, wd=None,
                           srcs=DERIVED_BIT, conf=round(min(0.8, 0.5 + 0.05 * len(ps)), 3),
                           pop=round(min(0.7, 0.4 + 0.03 * len(ps)), 3), extent_m=0.0, population=0, members=[])
            derived.append(mall)
            for p in ps:
                p.inside = _label(mall)
    report["contain"] = {"containers": len(containers), "inside_footprint": inside_fp, "inside_by_address": inside_addr,
                         "derived_malls": len(derived),
                         "inside_derived": sum(1 for p in pois if p.inside and p.inside in {_label(m) for m in derived})}
    return derived


# ── positions the sources contradict ────────────────────────────────────────────

FAR_M = 5000.0
# Kinds that are one place (an office, a company, an institution): a far second copy is a stale or registered address.
# Never food or retail, where small chains with two or three branches are common.
SINGLE_SITE = {"company", "office", "tech_company", "place", "factory", "lawyer", "accountant", "real_estate",
               "developer", "ngo", "institute", "university", "college", "hospital", "embassy", "government",
               "ministry", "courthouse", "stadium", "mall", "museum"}
GOV_FAR_M = 60000.0
# the governorates' capitals (the anchors of tools/place_index/bench/queries.py)
GOV_CAPITAL = {"cairo": (30.0444, 31.2357), "giza": (30.0131, 31.2089), "alexandria": (31.2001, 29.9187),
               "qalyubia": (30.4660, 31.1840), "dakahlia": (31.0409, 31.3785), "sharqia": (30.5877, 31.5020),
               "gharbia": (30.7865, 31.0004), "monufia": (30.5580, 31.0110), "beheira": (31.0341, 30.4682),
               "kafr_el_sheikh": (31.1107, 30.9388), "damietta": (31.4165, 31.8133), "port_said": (31.2653, 32.3019),
               "ismailia": (30.5965, 32.2715), "suez": (29.9668, 32.5498), "faiyum": (29.3084, 30.8428),
               "beni_suef": (29.0661, 31.0994), "minya": (28.1099, 30.7503), "asyut": (27.1809, 31.1837),
               "sohag": (26.5591, 31.6957), "qena": (26.1551, 32.7160), "luxor": (25.6872, 32.6396),
               "aswan": (24.0889, 32.8998), "red_sea": (27.2579, 33.8116), "new_valley": (25.4390, 30.5586),
               "matrouh": (31.3525, 27.2373), "north_sinai": (31.1316, 33.7984), "south_sinai": (28.2364, 33.6200)}
_GOV_FILL = {"محافظه", "governorate", "gov", "egypt", "مصر", "جمهوريه", "مصرالعربيه", "العربيه", "arab", "republic"}
_ROADISH = {"شارع", "ش", "طريق", "جسر", "قناه", "كورنيش", "محور", "street", "st", "road", "rd", "corniche", "axis",
            "bridge", "كوبري", "ميدان", "square"}
_PAGES = R.SOURCE_BITS[R.SRC_FSQ] | R.SOURCE_BITS[R.SRC_META] | R.SOURCE_BITS[R.SRC_MS] | R.SOURCE_BITS[R.SRC_OVT_OTHER]
_SRC_MASK = (1 << 10) - 1
CONFLICT_CONF = 0.6


def _corroborated(p: M.Place) -> bool:
    s = p.srcs & _SRC_MASK
    return bin(s).count("1") >= 2 or bool(s & R.SOURCE_BITS[R.SRC_OSM]) or bool(s & R.SOURCE_BITS[R.SRC_WD])


def _single_page(p: M.Place) -> bool:
    s = p.srcs & _SRC_MASK
    return bin(s).count("1") == 1 and bool(s & _PAGES)


_GOV_WORDS = {}


def _gov_words() -> dict[str, str]:
    if not _GOV_WORDS:
        from .enrich import GOV_IDS
        en = {"cairo": "cairo", "giza": "giza", "alexandria": "alexandria", "qalyubia": "qalyubia",
              "dakahlia": "dakahlia", "sharqia": "sharqia", "gharbia": "gharbia", "monufia": "monufia",
              "beheira": "beheira", "damietta": "damietta", "port said": "port_said", "ismailia": "ismailia",
              "suez": "suez", "faiyum": "faiyum", "fayoum": "faiyum", "beni suef": "beni_suef", "minya": "minya",
              "asyut": "asyut", "assiut": "asyut", "sohag": "sohag", "qena": "qena", "luxor": "luxor", "aswan": "aswan",
              "red sea": "red_sea", "hurghada": "red_sea", "new valley": "new_valley", "matrouh": "matrouh",
              "north sinai": "north_sinai", "south sinai": "south_sinai", "sharm": "south_sinai"}
        for ar, gid in GOV_IDS.items():
            _GOV_WORDS[tn.normalize(ar)] = gid
        for k, gid in en.items():
            _GOV_WORDS[k] = gid
    return _GOV_WORDS


def address_govs(addr: str | None) -> set[str]:
    """The governorate an address ENDS with («…، الإسكندرية», "…, Giza Governorate") — its last segment, never a street
    named after a city («شارع جسر السويس», "Port Said St", «طريق مصر - أسوان»)."""
    if not addr:
        return set()
    segs = [x for x in re.split(r"[,،\n]+", addr) if any(t not in _GOV_FILL for t in tn.tokens(x))]
    if not segs:
        return set()
    toks = tn.tokens(segs[-1])
    if not toks or any(t in _ROADISH for t in toks):
        return set()
    # the segment is the governorate and nothing else ("Gesr Al Suez" is a Cairo district, "59 Cairo" a street,
    # «خلف بنك القاهرة» a bank — measured on places-2026-10-31, the looser reading was wrong more often than right)
    rest = " ".join(t for t in toks if t not in _GOV_FILL)
    gid = _gov_words().get(rest)
    return {gid} if gid else set()


def locate(places: list[M.Place], report: dict) -> None:
    pois = [p for p in places if p.kind == "poi" and not p.brand_key and p.cat in SINGLE_SITE]
    by_name: dict[str, list[M.Place]] = defaultdict(list)
    for p in pois:
        for nm in (p.name_en, p.name_ar):
            if not nm:
                continue
            words = [tn.number_value(t) or tn.stems(t)[-1] for t in tn.tokens(nm) if not tn.is_stopword(t)]
            if words and sum(len(w) for w in words) >= 5:
                by_name[" ".join(words)].append(p)
            break
    far = 0
    for key, ps in by_name.items():
        if not 2 <= len(ps) <= 3:
            continue
        good = [p for p in ps if _corroborated(p)]
        if len(good) != 1:
            continue
        g = good[0]
        for p in ps:
            if p is not g and _single_page(p) and _hav(p.lat, p.lng, g.lat, g.lng) > FAR_M:
                p.conf = round(p.conf * CONFLICT_CONF, 3)
                far += 1
    gov_mismatch = 0
    for p in places:
        if p.kind == "poi" and p.gov and _single_page(p):
            named = address_govs(p.addr)
            if named and p.gov not in named and all(
                    _hav(p.lat, p.lng, *GOV_CAPITAL[g]) > GOV_FAR_M for g in named if g in GOV_CAPITAL):
                p.conf = round(p.conf * CONFLICT_CONF, 3)
                gov_mismatch += 1
    report["locate"] = {"far_copy_doubted": far, "address_names_another_governorate": gov_mismatch}
