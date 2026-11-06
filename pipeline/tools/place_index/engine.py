"""The on-device search engine — reference copy.

android/.../places/PlaceSearch.kt and ios/Runner/Places/PlaceSearch.swift are line-for-line
transcriptions of this file (tool/place_search_parity.py replays fixtures/engine_cases.json through
all three). Every constant lives in TUNING; nothing else hard-codes a number.

A QUERY goes through four steps:

1 PARSE (the lexicon, assets/search/egypt_lexicon.json — the Dart QueryParser's vocabulary)
    spatial phrases   «قريب مني», «near me», «على الطريق», «جنب الوصول», «في <area>»
    intent            «وجعني ضرسي» → dentist, a medicine name → pharmacy
    category          the longest token window that is a category term («محطة بنزين», «بنزينة», «gas»)
    brand             the longest window that is a lexicon brand alias («العزبي», «cib», «اهلي»)
    area              a trailing / «في»-led window naming an area in the national file
    street word       «شارع», «ش», «st», «طريق», «كوبري», «محور», «ميدان» → favour streets
  what is left is the RESIDUAL — the words that must be found in a name.

2 RETRIEVE from the files in scope (the national file + the tiles around the anchor)
    text      every residual word in all its forms (word, stem, loose, skeleton, joined pair), the
              last one also as a PREFIX (search-as-you-type), unknown words through a typo search
              over the vocabulary (same first letter, ±2 letters, edit budget by length)
    category  places of the parsed search category inside a radius that grows until enough
    brand     every branch of the parsed brand, nearest first, nationwide through the national file

3 SCORE each candidate on text match, distance, popularity, confidence and category agreement,
  with a weight profile chosen by what the query is (name / category / category + name / brand).

4 COLLAPSE same-name same-category places within COLLAPSE_M, and street pieces of one street.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass, field

from . import textnorm as tn

TUNING = {
    # text match quality per form
    "q_word": 1.0, "q_stem": 0.96, "q_join": 0.92, "q_loose": 0.84, "q_skel": 0.78, "q_skel_prefix": 0.58,
    "q_prefix_min": 0.58, "q_prefix_max": 0.94, "q_fuzzy1": 0.72, "q_fuzzy2": 0.56,
    # field factor
    "f_name": 1.0, "f_alt": 0.88, "f_addr": 0.45,
    # text score blend
    "coverage_share": 0.25, "first_word_bonus": 0.04, "exact_name_bonus": 0.10,
    # profiles: text, prox, pop, conf, cat — w_need is FITTED (bench/fit.py, 2026-11-02); the fit's name / category + name
    # profiles won on its cached re-ranking but lost on the real 346 run (an airport 25 km away, the landmark a relative
    # query resolves first — the cache cannot re-run that), so those keep the published values
    "w_name": (0.52, 0.14, 0.24, 0.10, 0.00),
    "w_category": (0.04, 0.52, 0.24, 0.14, 0.06),
    "w_cat_name": (0.46, 0.16, 0.12, 0.08, 0.18),
    "w_brand": (0.16, 0.56, 0.10, 0.14, 0.04),
    "w_area": (0.60, 0.10, 0.30, 0.00, 0.00),
    # proximity
    "tau_walkable": 900.0, "tau_local": 2500.0, "tau_destination": 9000.0, "tau_landmark": 30000.0,
    "name_half_m": 6000.0,         # name queries: prox = 1 / (1 + d / name_half_m)
    "category_radius0": 3000.0,    # first category ring, doubled until enough or the cap
    "category_radius_cap": 40000.0, "category_min": 12, "brand_radius_cap": 600000.0,
    "text_radius_m": 60000.0,      # tiles opened around the anchor for a name query
    # admission
    "min_text_name": 0.50, "min_text_cat_name": 0.42, "min_text_brand_other": 0.85, "max_postings": 4000,
    "prefix_terms": 48,
    "fuzzy_terms": 6, "driver_df": 2500, "max_drivers": 2, "max_candidates": 800, "collapse_m": 150.0, "street_word_boost": 0.12, "closed_penalty": 0.15,
    "nearby_query_tau_scale": 0.6,  # «قريب» shortens tau
    "area_trailing_max_m": 40000.0, "area_trailing_small_m": 15000.0, "refine_m": 10000.0, "expansion_factor": 0.96,  # a trailing word names an area only this near (or a city)
    "w_street": (0.48, 0.34, 0.10, 0.08, 0.00),  # street queries: the same street name is in every town
    "street_half_m": 2500.0, "short_skel_factor": 0.6, "q_skel2": 0.55, "q_skel_fuzzy": 0.62,
    "road_word_boost": 0.06, "soft_branch_text": 0.75, "detect_brand_min": 3,
    "street_unasked": 0.06,        # a street the query did not ask for («6 اكتوبر» is the city, not the bridge)
    "rel_plain_text": 0.85,        # «X جنب Y»: the plain reading wins when a place's own name (with the word) is the query
    "rel_mark_text": 0.75,         # … and the landmark must be found this well to search around it
    "f_area": 0.40,                # a word naming the place's own area («سنابل الشام مساكن ضرغام»)
    "approx_m": 1500.0,            # a pin flagged APPROX (a page geocoded to its district's centre) is never nearer
    # match classes (docs/place-search-2026-10.md §13): a real match (every word on a real name: the word, its stem,
    # the same number, the start of a word while typing, a transliteration) is worth more than any score of a fallback
    # (a skeleton, a typo, a generated name, the address); inside the real class the place's whole name gains
    # exact_bonus — a strong preference, never a wall: the famous palace beats the wedding hall named after it
    "tier_gap": 1.0, "exact_bonus": 0.06,
    "exact_short_len": 5, "exact_short_m": 30000.0,  # «baz»: a name this short is "the whole name" only this near
    "lead_cov": 0.8,               # coverage credit when the query is the START of the name (search-as-you-type)
    "chain_min": 3, "chain_sat": 12.0, "chain_bonus": 0.05,  # a name many places share nearby is a chain
    "q_generic_prefix": 0.9,       # the word being typed completes a word that says what kind («مطع» → «مطعم»)
    "f_gen": 0.92,                 # a generated other-script name (names.py), under f_alt
    "cat_in_name": 0.8,            # catm for a place whose own NAME carries the category word («… Cloud 9 Mall»)
    "w_need": (0.38, 0.39, 0.14, 0.08, 0.01),  # «شاشه عربيات»: the shops that sell it, nearest first
    "need_cat": 0.7,               # … a shop of a providing kind; 1.0 = its name says it sells it
    "need_radius_m": 15000.0,
    "short_area_len": 4,           # «المحلة» = «المحلة الكبرى»: a city's leading word names it …
    "short_area_pop": 0.5,         # … a city people know by that word
    "detect_brand_text": 0.75,
    "translit_len": 5,             # a one-word query this long reads a same-consonant word of the other script as real …
    "translit_skel": 4,            # … when they share this many consonants ("inovasys" ⇄ «نفسية» share only n-f-s)
    # typing (search goal, round 1): while only a few letters are typed the place people mean is the one around them, so
    # distance and a chain's size count for more than national fame
    "typing_len": 6, "w_typing": (0.30, 0.34, 0.20, 0.16, 0.00), "typing_half_m": 12000.0, "chain_bonus_typing": 0.14,
    "fuzzy_key_min": 5,            # a shorter word is being typed, not misspelt ("harr" is not "hair")
    "fallback_far_m": 30000.0,     # a fallback match this far answers only when it is prominent …
    "fallback_far_pop": 0.6,       # … («الاقصور» is Luxor; "tyre shop" is not a tattoo shop in Hurghada)
    "area_reach_m": 25000.0,       # a query that names a town does not answer from another town
    "longtail_penalty": 0.25,      # a long-tail row (longtail.py) answers under every stronger real match
    "join_terms": 12,              # terms per word in the two-word join: the word's own forms, then its commonest completions
    "typing_cap": 400, "brand_cap": 300,  # rows fully scored per keystroke: only the first ten are read (speed, criterion 4)
    "typing_cut_len": 4,           # … a longer word may be a whole name typed in full («الرحاب», «مدينتي»): every row of it is scored
    "far_tail": 0.08, "far_tail_m": 20000.0,  # past the exponential's reach the nearer branch still wins («مكتب بريد» from Alamein)
    "need_far_m": 60000.0,         # a product or service nobody near sells: an empty answer, not a shop in another governorate
    "kind_fallback_m": 60000.0,    # a kind with nothing near read as a name («جزار» → a village 200 km away) stays near too
}

APPROX_BIT = 1024  # records.APPROX_BIT: the row's pin is a geocoded district centre, not the place
LONGTAIL_BIT = 4096  # longtail.LONGTAIL_BIT: findable by a real name match, never listed under a kind or a chain

STREET_WORDS = {"شارع", "ش", "street", "st", "str", "طريق", "road", "rd", "كوبري", "bridge", "محور", "axis",
                "ميدان", "square", "sq", "نفق", "tunnel", "كورنيش", "corniche", "شارح"}
NEAR_WORDS = {"قريب", "قريبه", "قريبة", "اقرب", "أقرب", "جنبي", "حواليا", "near", "nearby", "nearest", "closest",
              "around", "اللي", "الي", "هنا", "مني", "me"}
IN_WORDS = {"في", "فى", "ف", "in", "at", "بال", "ب", "بمنطقه", "منطقه", "منطقة"}
AREA_WORDS = {"كفر", "عزبه", "قريه", "مدينه", "حي", "منطقه", "مركز", "قسم", "نجع", "كوم", "city", "district",
              "village", "el", "al", "governorate", "محافظه"}
# Categories whose word is the start of a NAME («كوبري أكتوبر», «ميدان التحرير»): never a category
# sweep, the word stays in the name search and marks the query as a street / structure.
NAME_TYPE_SCATS = {"bridge", "square"}
# A category search includes the kinds that ARE that category («مطعم» finds a koshary place); only true
# is-a families — the lexicon's prominence classes are not (a cemetery is not a mosque).
SCAT_FAMILY = {"restaurant": ("restaurant", "koshary", "grill", "seafood", "pizza", "burger", "fast_food", "foul_taameya")}
# Kinds whose places share names without being one chain («مسجد التوحيد», «مدرسة السلام»): no chain strength.
NO_CHAIN_SCATS = {"mosque", "church", "school", "kindergarten", "cemetery", "police", "government_office", "courthouse",
                  "civil_registry", "post_office", "university", "hospital", "health_unit"}
# «صيدلية فاتحة دلوقتي»: words that ask for a place open now — consumed (never searched as a name) and
# reported as `open_now` for the app, which alone can read hours against the clock.
OPEN_WORDS = {"فاتحه", "فاتح", "مفتوح", "مفتوحه", "دلوقتي", "دلوقت", "الان", "حاليا", "now", "open", "opened"}
# Words that are a category alone but the first word of a NAME when more words follow:
# «محطة» alone is the lexicon's fuel station, «محطة رمسيس» / «محطة سيدي جابر» is a station's name.
NAME_TYPE_WORDS = {"محطه", "station"}
ROAD_WORDS = {"طريق", "road", "rd", "محور", "axis", "كوبري", "bridge", "كورنيش", "corniche"}
STREET_ABBR = {"ش": "شارع", "st": "street", "str": "street", "rd": "road", "sq": "square",
               # «م التحرير» = ميدان التحرير, «ج القاهرة» = جامعة القاهرة (how addresses and signs shorten them)
               "م": "ميدان", "ج": "جامعه",
               # Franco street words become the Arabic word the names carry («kobry 6 october»)
               "kobry": "كوبري", "kobri": "كوبري", "kubri": "كوبري", "share3": "شارع", "shar3": "شارع",
               "sharea": "شارع", "tare2": "طريق", "tari2": "طريق", "midan": "ميدان", "medan": "ميدان",
               "me7war": "محور", "mehwar": "محور"}
FILLER = {"عايز", "عاوز", "عايزه", "عاوزه", "دور", "دورلي", "شوف", "شوفلي", "فين", "وين", "find", "show", "where", "is",
          "the", "a", "an", "want", "i", "need", "محتاج", "محتاجه", "لو", "سمحت", "please", "اقرب", "اي", "اى",
          # «حد يصلح تكييف», «اشتري جزمة منين»: the errand's verbs are not names
          "حد", "اشتري", "اجيب", "منين", "بيبيع", "بيبيعوا", "يبيع", "buy",
          # praise is not a name — «افضل مطعم», «best sushi» ask for the kind; only in queries of two words or more
          "best", "top", "good", "nice", "افضل", "احسن", "كويس", "كويسه", "حلو", "حلوه"}


# «صيدلية جنب مسجد الحصري», «ATM ورا سيتي ستارز», "pharmacy near Cairo Tower": what Egyptians give
# instead of an address — a landmark and where the place is from it. Normalized forms («وراء» → «ورا»).
REL_WORDS = {"جنب", "بجنب", "بجوار", "جوار", "بجانب", "جانب", "ورا", "خلف", "قدام", "امام", "قصاد", "مقابل",
             "behind", "beside", "opposite", "next"}
# … and «قريب من X» / "near X": relative only when a place follows (never «قريب مني», "near me")
REL_NEAR = {"قريب", "قريبه", "near", "nearby", "close", "around"}
REL_SELF = {"مني", "هنا", "me", "here", "us", "مننا", "ليا", "لي"}
REL_SKIP = {"من", "ل", "to", "from", "of", "the"}


def _toks(s: str) -> list[str]:
    return tn.tokens(s)


def relative_split(raw: str) -> tuple[str, str, str] | None:
    """(what, landmark, the direction word) when the query places what it asks for relative to a landmark."""
    toks = _toks(raw)
    for i, t in enumerate(toks):
        if t not in REL_WORDS and t not in REL_NEAR:
            continue
        head = [x for x in toks[:i] if x not in FILLER and x not in NEAR_WORDS]
        j = i + 1
        while j < len(toks) and toks[j] in REL_SKIP:
            j += 1
        mark = toks[j:]
        if not head or not mark or all(x in REL_SELF or tn.is_stopword(x) for x in mark):
            return None
        if t in REL_NEAR and j == i + 1 and t not in ("near",):
            return None  # «قريب X» without «من» is «X قريب» (near me), not a landmark
        return " ".join(head), " ".join(mark), t
    return None


def _name_has(r: "Result", word: str) -> bool:
    """The word is one of the result's own name words («امام» in «مسجد الإمام الحسين»)."""
    w = tn.stems(word)[-1]
    return any(tn.stems(t)[-1] == w for nm in (r.name_ar, r.name_en) if nm for t in tn.tokens(nm))


def _key(toks) -> str:
    return " ".join(tn.stems(t)[-1] for t in toks)


# Words that say what KIND of thing a place is. A query word may match them exactly, never through
# a skeleton, a typo or a prefix: «ستار» must not reach "street", «cfc» must not reach a café.
GENERIC_EXTRA = {"شارع", "street", "طريق", "road", "حارة", "alley", "مول", "mall", "city", "مدينه", "center",
                 "centre", "سنتر", "مركز", "شركه", "company", "محل", "shop", "store", "فرع", "branch", "مطعم",
                 "restaurant", "كافيه", "cafe", "صيدليه", "pharmacy", "مستشفي", "hospital", "بنك", "bank",
                 "مكتب", "office", "عياده", "clinic", "مدرسه", "school", "فندق", "hotel", "جامع", "مسجد", "mosque",
                 "كنيسه", "church", "محطه", "station", "ميدان", "square", "كوبري", "bridge", "قريه", "village",
                 "عزبه", "كفر", "حي", "منطقه", "district", "compound", "كمبوند", "parking", "جراج"}


@dataclass
class Lexicon:
    cat_terms: dict          # stem-key of a term → (scat, confidence)
    proximity: dict          # scat → proximity class
    brands: dict             # stem-key of an alias → (brand id, scat)
    intents: list            # (token tuple, scat, conf, requires_all)
    medicines: set
    near_me: list            # token tuples
    along_route: list
    near_dest: list
    labels: dict             # scat → (ar, en)
    generic: set = field(default_factory=set)  # single-word category terms (see GENERIC_EXTRA)
    entities: dict = field(default_factory=dict)  # stem-key of an alias → lexicon area / landmark / road
    preps: set = field(default_factory=set)        # «جنب», «بجوار», «في» … (single words, stems)
    brands_short: dict = field(default_factory=dict)  # two-letter chain names, matched only as the whole query
    fuzzy: dict = field(default_factory=dict)  # first letter → single-word lexicon keys (≥ 4 letters), code-point order
    needs: list = field(default_factory=list)  # «شاشه عربيات» → the shop kinds that sell it (lexicon `needs`)
    max_window: int = 4

    @staticmethod
    def load(path: str) -> "Lexicon":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cat_terms, prox, labels = {}, {}, {}
        for c in d["categories"]:
            prox[c["id"]] = c["proximity_class"]
            labels[c["id"]] = (c["label_ar"], c["label_en"])
            terms = [(c["label_ar"], 1.0), (c["label_en"], 1.0)] + [(t, 0.95) for t in c.get("terms_ar", [])] + \
                    [(t, 0.95) for t in c.get("terms_en", [])] + [(t, 0.9) for t in c.get("terms_franco", [])]
            for t, conf in terms:
                k = _key(_toks(t))
                if k and (k not in cat_terms or cat_terms[k][1] < conf):
                    cat_terms[k] = (c["id"], conf)
        brands, brands_short = {}, {}
        for b in d.get("brands", []):
            for a in set(b.get("aliases", [])) | {b.get("display_ar", ""), b.get("display_en", "")}:
                k = _key(_toks(a))
                if k and (len(k) >= 3 or " " in k):
                    brands.setdefault(k, (b["id"], b.get("category_id")))
                elif k:
                    brands_short.setdefault(k, (b["id"], b.get("category_id")))  # «وي», «we»: whole query only
        intents = []
        for i in d.get("intents", []):
            for ph in i["phrases"]:
                tt = tuple(tn.stems(t)[-1] for t in _toks(ph))
                if tt:
                    intents.append((tt, i["category_id"], i.get("confidence", 0.8), i.get("requires_all_tokens", False)))
        intents.sort(key=lambda x: -len(x[0]))
        meds = {_key(_toks(m)) for m in d.get("medicines", [])}
        preps = d.get("prepositions", {})
        tup = lambda xs: sorted({tuple(tn.stems(t)[-1] for t in _toks(x)) for x in xs if _toks(x)}, key=lambda t: (-len(t), t))
        entities = {}
        for kind, rows in (("road", d.get("roads", [])), ("landmark", d.get("landmarks", [])), ("area", d.get("areas", []))):
            for e in rows:
                ent = {"id": e["id"], "ar": e["display_ar"], "en": e["display_en"], "lat": e["lat"], "lng": e["lng"],
                       "kind": kind, "radius": float(e.get("search_radius_m") or e.get("radius_m") or 2000.0),
                       "names": [e["display_ar"], e["display_en"]] + list(e.get("aliases", []))}
                for nm in ent["names"]:
                    k = _key(_toks(nm))
                    if k and (len(k) >= 3 or " " in k) and k not in entities:
                        entities[k] = ent
        preps_set = set()
        for key_ in ("near_landmark", "in_area"):
            for ph in preps.get(key_, []):
                tt = _toks(ph)
                if len(tt) == 1:
                    preps_set.add(tn.stems(tt[0])[-1])
        generic = {tn.stems(t)[-1] for t in GENERIC_EXTRA for t in _toks(t)}
        for k in cat_terms:
            if " " not in k:
                generic.add(k)
        fuzzy: dict = {}
        for k in sorted({k for k in list(cat_terms) + list(brands) + list(entities) if " " not in k and len(k) >= 4}):
            fuzzy.setdefault(k[0], []).append(k)
        # a need: its product phrases (and, for a specific one, a context phrase) as stem tuples, the kinds that sell
        # it (best first, only kinds the lexicon has) and the phrases a seller's own NAME carries
        seq = lambda xs: [t for t in (tuple(tn.stems(w)[-1] for w in _toks(x)) for x in xs) if t]
        needs = []
        for nd in d.get("needs", []):
            cats = [c for c in nd.get("categories", []) if c in prox]
            prods = seq(nd.get("products", []))
            if cats and prods:
                needs.append({"id": nd["id"], "cats": cats, "products": prods, "contexts": seq(nd.get("contexts", [])),
                              "provider": seq(nd.get("provider_words", []))})
        return Lexicon(cat_terms, prox, brands, intents, meds, tup(preps.get("near_me", [])),
                       tup(preps.get("along_route", [])), tup(preps.get("near_destination", [])), labels, generic,
                       entities, preps_set, brands_short, fuzzy, needs)


@dataclass
class Parsed:
    raw: str
    tokens: list[str]
    residual: list[str]
    scat: str | None = None
    cat_conf: float = 0.0
    brand: str | None = None
    brand_scat: str | None = None
    scope: str = "anchor"            # anchor | near_me | along_route | near_destination | in_area
    area: dict | None = None         # {name, lat, lng, radius}
    street: bool = False
    near: bool = False
    cat_words: list = field(default_factory=list)
    road_word: bool = False          # «طريق», «محور», "road": a road, not a lane
    entity: dict | None = None       # a lexicon area / landmark / road the query names
    expansions: list = field(default_factory=list)  # that entity's other names, as token lists
    typed: bool = False              # a NAME_TYPE_WORD leads a name («محطة رمسيس»)
    open_now: bool = False           # the query asked for a place open now
    area_led: bool = True            # the area was led by «في» (False: a trailing word read as an area)
    need: dict | None = None         # «شاشه عربيات»: a product / service the query asks for (Lexicon.needs)
    complete: tuple | None = None    # «مطع»: (search category, the kind word the typed word is the start of)

    @property
    def kind(self) -> str:
        if self.brand and not self.residual_beyond_brand:
            return "brand"
        if self.scat and not self.residual:
            return "category"
        if self.scat:
            return "cat_name"
        return "name"

    residual_beyond_brand: bool = False


@dataclass
class Result:
    db: str
    id: int
    pid: str
    kind: int
    cat: str
    scat: str | None
    lat: float
    lng: float
    name_ar: str | None
    name_en: str | None
    dist: float
    score: float
    text: float
    parts: dict = field(default_factory=dict)
    row: dict = field(default_factory=dict)
    adist: float = 0.0               # distance to what the query is measured from (area, route, user)
    tier: int = 0                    # the match class (3 the whole name, 2 real words, 1 a fallback)

    def name(self, lang="ar"):
        return (self.name_ar or self.name_en) if lang == "ar" else (self.name_en or self.name_ar)


_BRAND_FAMILIES = [{"bank", "atm", "exchange"}, {"pharmacy"}, {"supermarket", "mall", "market"},
                   {"mobile_shop", "electronics_store", "appliance_store"}, {"gas_station", "car_repair", "oil_change",
                   "ev_charging"}, {"restaurant", "fast_food", "burger", "pizza", "grill", "koshary", "cafe", "sweets",
                   "bakery", "juice_bar", "ice_cream"}]


def _brand_family(scat, brand_scat) -> bool:
    if not scat or not brand_scat:
        return False
    if scat == brand_scat:
        return True
    return any(scat in f and brand_scat in f for f in _BRAND_FAMILIES)


def _rank(r: "Result"):
    """Best score first; equal scores by distance, then by id — never by retrieval order, which is
    the SQLite planner's and differs between the Python, Android and iOS builds of SQLite."""
    return (-r.score, r.dist, r.pid)


def haversine(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


class Index:
    """The national file + every tile in a directory (the phone opens only what it has)."""

    def __init__(self, dirpath: str):
        with open(os.path.join(dirpath, "manifest.json"), encoding="utf-8") as f:
            self.manifest = json.load(f)
        self.dir = dirpath
        self.cons: dict[str, sqlite3.Connection] = {}
        self.bbox: dict[str, list[float]] = {}
        self.nplaces: dict[str, int] = {}
        for t in [self.manifest["national"]] + self.manifest["tiles"]:
            path = os.path.join(dirpath, t["id"] + ".sqlite")
            if not os.path.exists(path):
                continue
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            self.cons[t["id"]] = con
            self.bbox[t["id"]] = t["bbox"]
            self.nplaces[t["id"]] = t["places"]

    def near(self, lat: float, lng: float, radius_m: float) -> list[str]:
        """The national file, then every tile within radius_m — NEAREST FIRST, so any cap applied
        downstream drops the far candidates, never the near ones."""
        dlat = radius_m / 111000.0
        dlng = radius_m / (111000.0 * max(0.2, math.cos(math.radians(lat))))
        tiles = []
        for tid, (x0, y0, x1, y1) in self.bbox.items():
            if tid == "national":
                continue
            if x1 >= lng - dlng and x0 <= lng + dlng and y1 >= lat - dlat and y0 <= lat + dlat:
                cx = min(max(lng, x0), x1)
                cy = min(max(lat, y0), y1)
                tiles.append((haversine(lat, lng, cy, cx), tid))
        tiles.sort()
        return (["national"] if "national" in self.cons else []) + [t for _, t in tiles]


class Engine:
    def __init__(self, index: Index, lexicon: Lexicon, tuning: dict | None = None):
        self.ix = index
        self.lx = lexicon
        self.T = dict(TUNING)
        if tuning:
            self.T.update(tuning)
        self._area_cache: dict = {}
        self._area_names: dict = {}
        self._extra: list[str] = []
        self._wm_cls = 0      # word_match's match class of its last call
        self._tier = 0        # _text_score's match class of its last call
        self._multi = False   # the words being scored are more than one (word_match's transliteration rule)
        self._qlen = 0        # the words of the query being searched (_search), stopwords aside

    # ── 1 parse ─────────────────────────────────────────────────────────────

    def parse(self, raw: str, lat: float, lng: float, no_area: bool = False) -> Parsed:
        """Phrases first (scope, intent), then ONE longest-window scan over brands, lexicon entities
        and categories at once — the longest window wins, ties go brand > entity > category (the
        Dart QueryParser's rule) — then a second category scan over what is left, then the area."""
        toks = _toks(raw)
        if len(toks) > 1:
            toks = [STREET_ABBR.get(t, t) for t in toks]
        p = Parsed(raw=raw, tokens=toks, residual=[])
        keys = [tn.stems(t)[-1] for t in toks]
        used = [False] * len(toks)

        def find_seq(seq):
            n = len(seq)
            for i in range(len(keys) - n + 1):
                if all(not used[i + j] for j in range(n)) and tuple(keys[i:i + n]) == seq:
                    return i
            return -1

        for scope, phrases in (("along_route", self.lx.along_route), ("near_destination", self.lx.near_dest),
                               ("near_me", self.lx.near_me)):
            for ph in phrases:
                i = find_seq(ph)
                if i >= 0:
                    for j in range(len(ph)):
                        used[i + j] = True
                    p.scope = scope if p.scope == "anchor" else p.scope
                    if scope == "near_me":
                        p.near = True
        for tt, scat, conf, req_all in self.lx.intents:
            if req_all:
                pos = [keys.index(t) if t in keys else -1 for t in tt]
                if all(x >= 0 and not used[x] for x in pos):
                    for x in pos:
                        used[x] = True
                    p.scat, p.cat_conf = scat, conf
                    break
            else:
                i = find_seq(tt)
                if i >= 0:
                    for j in range(len(tt)):
                        used[i + j] = True
                    p.scat, p.cat_conf = scat, conf
                    break
        for i, t in enumerate(toks):
            if not used[i] and t in NEAR_WORDS and len(toks) > 1:
                used[i] = True
                p.near = True
            elif not used[i] and t in FILLER and len(toks) > 1:
                used[i] = True
            elif not used[i] and len(toks) > 1 and keys[i] in self.lx.preps and t not in IN_WORDS:
                used[i] = True  # «جنب», «بجوار», «قدام»: the place after it is the anchor
        # a product or service with what makes it specific («شاشه عربيات», «تصليح تكييف») before the kinds: «بطارية
        # عربية» is a car battery, not «بطارية» + a name
        if p.scat is None:
            self._need(p, keys, used, True)
        # a word nobody wrote (no lexicon key, not in the national file) one typo from a lexicon word
        for i, t in enumerate(toks):
            if not used[i] and t not in STREET_WORDS and t not in IN_WORDS and not tn.is_stopword(t):
                fk = self._fuzzy_key(keys[i], t)
                if fk:
                    keys[i] = fk

        def scan(allow_brand: bool, allow_entity: bool, allow_cat: bool):
            free = used.count(False)
            for n in range(min(self.lx.max_window, len(toks)), 0, -1):
                for i in range(len(toks) - n + 1):
                    if any(used[i:i + n]):
                        continue
                    k = " ".join(keys[i:i + n])
                    if allow_brand and k in self.lx.brands and not (n == 1 and i in self._skip_brand):
                        return "brand", i, n, self.lx.brands[k]
                    # a lone word that says what KIND of place («مطار», «مول») is the category when
                    # other words follow, never the lexicon's one landmark of that kind («المطار»)
                    # …nor a window that holds a station word with more words around it («محطة مصر
                    # اسكندرية» is Alexandria's station, not Cairo's), nor a word that is also a kind of
                    # place when the query asks for the nearest one («دهب قريب» is gold, not Dahab)
                    if allow_entity and k in self.lx.entities and not (n == 1 and free > 1 and k in self.lx.generic) \
                            and not (free > n and any(keys[j] in NAME_TYPE_WORDS for j in range(i, i + n))) \
                            and not (n == 1 and p.near and k in self.lx.cat_terms):
                        return "entity", i, n, self.lx.entities[k]
                    if allow_cat and k in self.lx.cat_terms and self.lx.cat_terms[k][0] not in NAME_TYPE_SCATS \
                            and not (n == 1 and free > 1 and k in NAME_TYPE_WORDS):
                        return "cat", i, n, self.lx.cat_terms[k]
            return None

        free_keys = [keys[i] for i in range(len(toks)) if not used[i]]
        if len(free_keys) == 1 and free_keys[0] in self.lx.brands_short:
            i = next(j for j in range(len(toks)) if not used[j])
            p.brand, p.brand_scat = self.lx.brands_short[free_keys[0]]
            p.brand_span = (i, 1)
            used[i] = True
        entity_span = None
        self._skip_brand = set()
        hit = scan(p.brand is None, True, p.scat is None)
        while hit:
            what, i, n, val = hit
            for j in range(n):
                used[i + j] = True
            if what == "brand" and n == 1 and p.scat and val[1] != p.scat:
                # «مول مصر»: one word that is also a chain's nickname, after a different kind of
                # place, is part of that place's name
                for j in range(n):
                    used[i + j] = False
                self._skip_brand.add(i)
            elif what == "brand":
                p.brand, p.brand_scat = val
                p.brand_span = (i, n)
            elif what == "entity":
                p.entity = val
                entity_span = (i, n)
            else:
                p.scat, p.cat_conf = val
                p.cat_words = toks[i:i + n]
            hit = scan(p.brand is None, p.entity is None, p.scat is None)
        if p.scat is not None:
            # another word of the same kind is part of the category, not a name («فرن عيش», «صيدلية دوا»)
            for i, k in enumerate(keys):
                if not used[i] and len(toks) > 1 and self.lx.cat_terms.get(k, (None,))[0] == p.scat:
                    used[i] = True
                    p.cat_words = p.cat_words + [toks[i]]
            for i, t in enumerate(toks):
                if not used[i] and t in OPEN_WORDS:
                    used[i] = True
                    p.open_now = True
        if p.scat is None:
            for i, k in enumerate(keys):
                if not used[i] and k in self.lx.medicines:
                    p.scat, p.cat_conf = "pharmacy", 0.85
                    used[i] = True
        if p.scat is None and p.brand is None and p.entity is None:
            self._need(p, keys, used, False)  # «جزمه», «كفر موبايل»: a product alone
        for i, t in enumerate(toks):
            if not used[i] and t in STREET_WORDS:
                p.street = True
                if t in ROAD_WORDS:
                    p.road_word = True
            if not used[i] and keys[i] in NAME_TYPE_WORDS and len(toks) > 1:
                p.typed = True
        # the entity: an anchor when the query asks for a kind / chain near it, else its other
        # names join the search («الدايري» → «الطريق الدائري», «cfc» → «كايرو فيستيفال سيتي»)
        if p.entity:
            ent = self._refine_entity(p.entity)
            p.entity = ent
            i, n = entity_span
            others = [j for j in range(len(toks)) if not used[j] and toks[j] not in STREET_WORDS
                      and toks[j] not in IN_WORDS and not (i <= j < i + n)]
            if p.scat or p.brand or (others and ent["kind"] != "road"):
                # «صيدلية جنب سيتي ستارز», «شارع 9 المعادي»: the entity is WHERE, the rest is WHAT
                p.area = {"name": ent["ar"], "lat": ent["lat"], "lng": ent["lng"], "radius": ent["radius"],
                          "cat": ent["kind"], "road": ent["kind"] == "road"}
                p.scope = "in_area" if p.scope == "anchor" else p.scope
            elif others:
                for j in range(n):
                    used[i + j] = False  # a road named inside a longer query is just words
                p.entity = None
            else:
                for j in range(n):
                    used[i + j] = False  # its own words stay searchable as typed
                seen = set()
                for nm in ent["names"]:
                    tt = [t for t in _toks(nm) if not tn.is_stopword(t)]
                    k2 = " ".join(tt)
                    if tt and k2 not in seen:
                        seen.add(k2)
                        p.expansions.append(tt)
                p.expansions = p.expansions[:8]
        # area: «في X» anywhere, or a trailing X after a category / brand / street word
        rest = [i for i in range(len(toks)) if not used[i]]
        self._parsed_target = bool(p.scat or p.brand)
        if p.area is None and rest and not no_area and \
                (p.scat or p.brand or p.street or p.typed or any(toks[i] in IN_WORDS for i in rest)):
            area = self._find_area(toks, used, lat, lng)
            if area:
                p.area_led = area.pop("led")
                i0, n0 = area.pop("span")
                if p.typed:
                    for j in range(i0, i0 + n0):
                        used[j] = False  # «محطة سيدي جابر»: the area is where to look, its words stay the name
                p.area = area
                p.scope = "in_area" if p.scope == "anchor" else p.scope
        for i, t in enumerate(toks):
            if not used[i] and t in IN_WORDS and len(toks) > 1:
                used[i] = True
        p.residual = [t for i, t in enumerate(toks) if not used[i] and not tn.is_stopword(t)]
        if p.brand:
            # the brand's own words stay searchable as text (a branch's name carries them)
            i, n = p.brand_span
            p.residual_beyond_brand = bool(p.residual and not all(t in STREET_WORDS for t in p.residual))
            p.residual = toks[i:i + n] + p.residual
        if p.kind == "name" and len(p.residual) == 1 and p.entity is None and not p.street:
            p.complete = self._completion(p.residual[0])
        return p

    def _need(self, p: Parsed, keys: list, used: list, with_context: bool) -> None:
        """The need the query names: a product phrase as one run of unused words and — for a need that has
        contexts — one of its context phrases elsewhere. The longest match wins (product + context words), ties the
        lexicon's order. Its words are consumed; p.scat is the first kind that sells it."""
        def at(seq, banned):
            n = len(seq)
            for i in range(len(keys) - n + 1):
                if all(not used[i + j] and (i + j) not in banned for j in range(n)) and tuple(keys[i:i + n]) == seq:
                    return i
            return -1
        best = None
        for nd in self.lx.needs:
            if bool(nd["contexts"]) != with_context:
                continue
            for prod in nd["products"]:
                i = at(prod, ())
                if i < 0:
                    continue
                span = set(range(i, i + len(prod)))
                if with_context:
                    for ctx in nd["contexts"]:
                        j = at(ctx, span)
                        if j >= 0:
                            size = len(prod) + len(ctx)
                            if best is None or size > best[0]:
                                best = (size, nd, span | set(range(j, j + len(ctx))))
                            break
                elif best is None or len(prod) > best[0]:
                    best = (len(prod), nd, span)
        if best is None:
            return
        _, nd, span = best
        for j in sorted(span):
            used[j] = True
        p.need = nd
        p.scat, p.cat_conf = nd["cats"][0], 0.9
        p.cat_words = [p.tokens[j] for j in sorted(span)]

    def _completion(self, w: str):
        """«مطع» → (restaurant, «مطعم»): the one word typed so far is the start of a word that says what kind of
        place — of ONE search category (the shortest such word stands for it). None when it starts no kind word or
        those of several kinds (“res” → restaurant / rest area), when it is a whole kind word already, or too short."""
        k = tn.stems(w)[-1]
        if len(k) < (3 if tn.is_arabic_token(k) else 4) or tn.has_digit(k) or k in self.lx.cat_terms:
            return None
        hits: dict = {}
        for term, (scat, _) in self.lx.cat_terms.items():
            if " " in term or not term.startswith(k) or scat in NAME_TYPE_SCATS:
                continue
            old = hits.get(scat)
            if old is None or (len(term), term) < (len(old), old):
                hits[scat] = term
        if len(hits) != 1:
            return None
        scat, term = next(iter(hits.items()))
        return scat, term

    def _fuzzy_key(self, k: str, tok: str):
        """«صيدلبه» → «صيدليه», "heliopolice" → "heliopolis": a word that is neither a lexicon key nor
        in the national file's vocabulary, one edit budget from a single-word lexicon key with the same
        first letter. The closest wins; ties go to the first in code-point order."""
        lx = self.lx
        if len(k) < self.T["fuzzy_key_min"] or k.isdigit() or k in lx.cat_terms or k in lx.brands or k in lx.entities:
            return None
        key = ("fuzzy", k, tok)
        if key in self._area_cache:
            return self._area_cache[key]
        out = None
        con = self.ix.cons.get("national")
        known = con is not None and any(con.execute("SELECT 1 FROM vocab WHERE t = ?", (f,)).fetchone()
                                        for f in (tok, k))
        budget = tn.max_edits(k)
        if not known and budget:
            best = None
            for cand in lx.fuzzy.get(k[0], ()):
                if abs(len(cand) - len(k)) > budget:
                    continue
                e = tn.damerau(k, cand, budget)
                if e <= budget and (best is None or e < best[0]):
                    best = (e, cand)
            out = best[1] if best else None
        self._area_cache[key] = out
        return out

    def _refine_entity(self, ent: dict) -> dict:
        """A lexicon point is someone's memory of where a place is; the index knows. Move the
        entity to the best national match of its own names within REFINE_M."""
        key = ("refine", ent["id"])
        if key in self._area_cache:
            return self._area_cache[key]
        out = ent
        con = self.ix.cons.get("national")
        if con is not None and ent["kind"] != "road":
            best = None
            for nm in ent["names"][:4]:
                words = [t for t in _toks(nm) if not tn.is_stopword(t)]
                if not words:
                    continue
                rare = min(words, key=lambda w: len(w) * -1)
                for f in [rare] + tn.stems(rare)[1:]:
                    for r in con.execute("SELECT place.* FROM tok JOIN place ON place.id = tok.id WHERE tok.t = ? ORDER BY tok.id LIMIT 200", (f,)):
                        row = dict(r)
                        d = haversine(ent["lat"], ent["lng"], row["lat"], row["lng"])
                        if d > self.T["refine_m"]:
                            continue
                        sc = self._text_score(words, {"_db": "national"}, row)
                        if sc >= 0.9 and (best is None or (sc, row["pop"]) > (best[0], best[1])):
                            best = (sc, row["pop"], row)
            if best:
                out = dict(ent)
                out["lat"], out["lng"] = best[2]["lat"], best[2]["lng"]
        self._area_cache[key] = out
        return out

    def _find_area(self, toks, used, lat, lng):
        con = self.ix.cons.get("national")
        if con is None:
            return None
        cands = []
        n_t = len(toks)
        for n in range(min(4, n_t), 0, -1):
            for i in range(n_t - n + 1):
                if any(used[i:i + n]):
                    continue
                # an area is either led by «في» or is the trailing window
                led = i > 0 and toks[i - 1] in IN_WORDS
                trailing = i + n == n_t
                if not (led or trailing):
                    continue
                words = toks[i:i + n]
                if all(w in IN_WORDS or w in STREET_WORDS or w.isdigit() for w in words):
                    continue
                # what is left must still be a query: a street word alone is not one («ش مكرم عبيد»)
                left = [toks[j] for j in range(n_t) if not used[j] and not (i <= j < i + n)
                        and toks[j] not in IN_WORDS]
                if not left and not self._parsed_target:
                    continue
                if left and all(w in STREET_WORDS for w in left) and not self._parsed_target:
                    continue
                for a in self._areas_named(words):
                    d = haversine(lat, lng, a["lat"], a["lng"])
                    # without «في», a trailing word is an area only when the area is near or big — and
                    # big only when the words are its whole name («الشيخ» is not Kafr El-Sheikh) or the
                    # city's own short name («المحلة» = «المحلة الكبرى»)
                    if not led and d > self.T["area_trailing_max_m"] and (not (a["full"] or a["short"]) or a["cat"] not in (
                            "city", "governorate", "markaz", "town")):
                        continue
                    if not led and a["cat"] in ("neighbourhood", "hamlet", "village") and d > self.T["area_trailing_small_m"]:
                        continue
                    cands.append((-(n * 10) - (2 if led else 0), 1 if a["short"] else 0, d, i, n, a))
            if cands:
                break
        if not cands:
            return None
        # «المنشية» is the district called that, before «عزبة المنشية» next door
        cands.sort(key=lambda c: (c[0], c[1], 0 if c[5]["full"] else 1, c[2] / (1 + 0.5 * c[5]["pop"])))
        cands = [(c[0], c[2], c[3], c[4], c[5]) for c in cands]
        _, d, i, n, a = cands[0]
        for j in range(n):
            used[i + j] = True
        if i > 0 and toks[i - 1] in IN_WORDS:
            used[i - 1] = True
        radius = max(1500.0, min(15000.0, a["ext"] or 0.0) or {1: 2500.0}.get(1, 2500.0))
        return {"name": a["name_ar"] or a["name_en"], "lat": a["lat"], "lng": a["lng"], "radius": radius,
                "cat": a["cat"], "led": i > 0 and toks[i - 1] in IN_WORDS, "span": (i, n)}

    def _areas_named(self, words):
        key = " ".join(words)
        if key in self._area_cache:
            return self._area_cache[key]
        con = self.ix.cons["national"]
        # every word must be a word / stem of the area's name
        ids = None
        for w in words:
            forms = set(tn.stems(w))
            rows = set()
            for f in forms:
                for r in con.execute("SELECT tok.id FROM tok JOIN place ON place.id = tok.id "
                                     "WHERE tok.t = ? AND (tok.f & 3) = 0 AND place.kind = 1", (f,)):
                    rows.add(r[0])
            ids = rows if ids is None else ids & rows
            if not ids:
                break
        out = []
        if ids:
            q = ",".join(str(i) for i in sorted(ids)[:400])
            want = {tn.stems(w)[-1] for w in words}
            want_core = want - AREA_WORDS
            short = None  # the most populous city whose name LEADS with the one word typed
            for r in con.execute(f"SELECT id, lat, lng, name_ar, name_en, cat, ext, pop, kind FROM place WHERE id IN ({q}) AND kind = 1 ORDER BY id"):
                # the area's own name (either language, minus «كفر / قرية / حي …») is what was typed;
                # `full` = every word of it was typed, «كفر» included
                for nm in (r["name_ar"], r["name_en"]):
                    order = [tn.stems(t)[-1] for t in _toks(nm or "") if not tn.is_stopword(t)]
                    words_ = set(order)
                    core = words_ - AREA_WORDS
                    if core and core == want_core:
                        row = dict(r)
                        row["full"] = words_ == want
                        row["short"] = False
                        out.append(row)
                        break
                    lead = [t for t in order if t not in AREA_WORDS]
                    # an Arabic usage («المحلة», «شبين»): an English name leads with its modifier ("October Gardens")
                    if len(want_core) == 1 and len(lead) >= 2 and lead[0] in want_core and tn.is_arabic_token(lead[0]) \
                            and len(lead[0]) >= self.T["short_area_len"] and r["cat"] in ("city", "town", "markaz") and \
                            r["pop"] >= self.T["short_area_pop"] and \
                            (short is None or (r["pop"], -r["id"]) > (short["pop"], -short["id"])):
                        short = dict(r)
                        short["full"] = False
                        short["short"] = True
            if short is not None and all(o["id"] != short["id"] for o in out):
                out.append(short)
        self._area_cache[key] = out
        return out

    # ── 2 retrieve + 3 score ────────────────────────────────────────────────

    def search(self, raw: str, lat: float, lng: float, limit: int = 10, route=None, dest=None, dbs=None,
               explain=False, extra=None) -> list[Result]:
        """An interpretation that finds nothing is the wrong one: a trailing word read as an area
        («مترو السادات» → Sadat City) is retried as part of the name, and a category nobody
        tagged («استراحة») is retried as the words of a name.

        `extra` = tiles the NAME ROUTER says hold the query's words (router.py): searched for text
        after the tiles around the anchor, whatever their distance.

        A query placed relative to a landmark («صيدلية جنب مسجد الحصري») resolves the landmark first and
        searches the rest around it — unless the plain reading finds a place whose own name holds the
        direction word («مسجد الامام الحسين»: «امام» is part of the name), or the phrase is the
        destination's («جنب الوصول»)."""
        self._extra = [x for x in (extra or []) if x in self.ix.cons]
        plain = self._search_plain(raw, lat, lng, limit, route, dest, dbs, explain)
        rel = relative_split(raw) if not route else None
        if rel is not None and self.parse(raw, lat, lng).scope in ("along_route", "near_destination"):
            rel = None  # «صيدلية جنب الوصول»: the destination, not a landmark
        if rel is None:
            return plain
        what, mark, word = rel
        if plain and plain[0].text >= self.T["rel_plain_text"]:
            # the plain reading named a place: it stands when the direction word is part of that name, or the place
            # is the kind the query asks for («مسجد الامام الحسين» → the mosque; «صيدلية ورا محطة سيدي جابر» → not
            # the station)
            hs = self.parse(what, lat, lng).scat
            top = plain[0]
            if _name_has(top, word) or (hs and (top.scat == hs or top.scat in SCAT_FAMILY.get(hs, ()))):
                return plain
        marks = self._search_plain(mark, lat, lng, 1, None, None, dbs, explain)
        if not marks or marks[0].text < self.T["rel_mark_text"]:
            return plain
        m = marks[0]
        near = self._search_plain(what, m.lat, m.lng, limit, None, None, dbs, explain, near=True)
        for r in near:
            r.dist = haversine(lat, lng, r.lat, r.lng)  # what the user sees is still their own distance
        seen = {r.pid for r in near}
        return (near + [r for r in plain if r.pid not in seen])[:limit]

    def _search_plain(self, raw: str, lat: float, lng: float, limit: int, route, dest, dbs, explain,
                      near: bool = False) -> list[Result]:
        p = self.parse(raw, lat, lng)
        if near:
            p.near = True
        out = self._search(p, lat, lng, limit, route, dest, dbs, explain)
        if p.area is not None and not p.area_led and not route:
            out = self._whole_reading(raw, p, out, lat, lng, limit, dest, dbs, explain, near)
        if not out and p.area is not None and not p.area_led:
            p = self.parse(raw, lat, lng, no_area=True)
            if near:
                p.near = True
            out = self._search(p, lat, lng, limit, route, dest, dbs, explain)
        if not out and p.kind == "name" and len(p.residual) == 2:
            a, b = p.residual  # «بور توفيق» ⇄ «بورتوفيق»: the name written as one word
            if len(a) + len(b) <= 12 and tn.is_arabic_token(a) == tn.is_arabic_token(b):
                p.residual = [a + b]
                out = self._search(p, lat, lng, limit, route, dest, dbs, explain)
        if not out and p.kind == "category" and p.cat_words:
            p.residual = [t for t in p.cat_words if not tn.is_stopword(t)]
            p.scat, p.cat_words = None, []
            out = [r for r in self._search(p, lat, lng, limit, route, dest, dbs, explain) if r.dist <= self.T["kind_fallback_m"]]
        # a category + name query knows from its own scoring whether a whole name was typed: most keystrokes are not one
        if p.kind in ("category", "cat_name") and not p.brand and (p.kind == "category" or self._saw_exact):
            exact = self._exact_names(raw, lat, lng, dbs, p.cat_words)
            if exact:
                seen = {r.pid for r in exact}
                out = (exact + [r for r in out if r.pid not in seen])[:limit]
        return out

    def _text_scope(self, lat: float, lng: float) -> list[str]:
        """The files a name is looked for in: the national file and the tiles around the anchor
        (nearest first), then the routed tiles beyond them."""
        near = self.ix.near(lat, lng, self.T["text_radius_m"])
        return near + [x for x in self._extra if x not in near]

    def _whole_reading(self, raw: str, p: Parsed, out: list, lat: float, lng: float, limit: int, dest, dbs, explain,
                       near: bool) -> list[Result]:
        """A trailing word read as a town may be part of the name: «مترو السادات» is the station, not metros near Sadat City;
        «قسم العجوزه» is the police station named that, «مستشفى نجع حمادي» the hospital. Places whose own names hold every
        word (the kind word may be their kind instead) answer first, nearest first, whatever the first reading found."""
        q = self.parse(raw, lat, lng, no_area=True)
        if near:
            q.near = True
        if q.brand or not q.residual:
            return out
        whole = self._search(q, lat, lng, limit, None, dest, dbs, explain)
        strong = [r for r in whole if r.tier >= 2 and r.kind != 1 and (q.scat is None or r.scat == q.scat or
                                                                         r.scat in SCAT_FAMILY.get(q.scat, ()))
                  and r.adist <= self.T["fallback_far_m"] * 2]
        if not strong:
            return out
        seen = {r.pid for r in strong}
        return (strong + [r for r in out if r.pid not in seen])[:limit]

    def _exact_names(self, raw: str, lat: float, lng: float, dbs, cat_words: list) -> list[Result]:
        """Places whose whole name IS the query («مكتبة الإسكندرية», «معبد الكرنك», «مطعم الدهان»):
        first, whatever the parse made of the words — but only when the query names something (a
        word that is not a kind of place), so «محطة بنزين» stays a category search."""
        T = self.T
        toks = [STREET_ABBR.get(t, t) for t in _toks(raw)]
        words = [t for t in toks if not tn.is_stopword(t) and t not in NEAR_WORDS and t not in FILLER
                 and t not in IN_WORDS]
        if len(words) < 2:
            return []
        want = {tn.stems(w)[-1] for w in words}
        kind_words = {tn.stems(w)[-1] for w in cat_words}
        if all(w in self.lx.generic or w in kind_words for w in want):
            return []
        cands: dict = {}
        self._text_candidates(words, dbs or self._text_scope(lat, lng), cands)
        out = []
        for (db, pid), c in cands.items():
            row = self._row(db, pid)
            if row is None:
                continue
            if not self._is_exact(words, row):
                continue
            d = haversine(lat, lng, row["lat"], row["lng"])
            w = T["w_name"]
            # placed FIRST by _search_plain, so scored above every class (the app re-sorts by score)
            s = w[0] + w[1] * (1.0 / (1.0 + d / T["name_half_m"])) + w[2] * row["pop"] + w[3] * row["conf"] + \
                T["tier_gap"] * 3
            out.append(Result(db, pid, row["pid"], row["kind"], row["cat"], row["scat"], row["lat"], row["lng"],
                              row["name_ar"], row["name_en"], d, s, 1.0, {}, dict(row), d, 3))
        out.sort(key=_rank)
        return self._collapse(out, 3)

    def _search(self, p: Parsed, lat: float, lng: float, limit: int, route, dest, dbs, explain) -> list[Result]:
        T = self.T
        alat, alng = lat, lng
        if p.area and not p.area.get("road"):
            alat, alng = p.area["lat"], p.area["lng"]
        elif p.scope == "near_destination" and dest:
            alat, alng = dest
        kind = p.kind
        self._qlen = sum(1 for t in p.tokens if not tn.is_stopword(t))
        tau = self._tau(p)
        if p.near:
            tau *= T["nearby_query_tau_scale"]
        self._saw_exact = False
        typing = kind == "name" and not p.street and bool(p.residual) and len("".join(p.residual)) <= T["typing_len"]
        self._typing_now = typing
        scope = dbs or self._text_scope(alat, alng)
        cands: dict[tuple[str, int], dict] = {}

        # text — a category word that is part of a name («مول مصر», «مستشفى السلام») is the most
        # selective word there is inside a tile, so it may drive retrieval too
        if p.residual:
            self._text_candidates(p.cat_words + p.residual if kind == "cat_name" else p.residual, scope, cands)
        for exp in p.expansions:
            self._text_candidates(exp, scope, cands, prefix=False)  # another WHOLE name of the entity: no completions
        # category / brand / need: the kinds that sell it, and the shops whose own names say they do
        # only a query that is ALL kind reads the kind's rows: a row of the kind without the rest of the words is dropped below (min_text_cat_name): reading them all cost every keystroke
        if p.need is not None and kind == "category":
            for sc in p.need["cats"]:
                self._category_candidates(sc, alat, alng, scope, cands, p, route)
            nscope = self.ix.near(alat, alng, T["need_radius_m"])
            for ph in p.need["provider"]:
                self._text_candidates(list(ph), nscope, cands, prefix=False)
        elif p.scat and kind == "category":
            self._category_candidates(p.scat, alat, alng, scope, cands, p, route)
        if p.complete is not None:
            self._category_candidates(p.complete[0], alat, alng, scope, cands, p, route)
        if p.brand:
            self._brand_candidates(p.brand, alat, alng, cands)

        if typing and not route and len(cands) > T["typing_cap"] and len("".join(p.residual)) <= T["typing_cut_len"]:
            cands = self._typing_cut(cands, scope, alat, alng)
        out: list[Result] = []
        for (db, pid), c in cands.items():
            row = c.get("row") or self._row(db, pid)
            if row is None:
                continue
            if route:
                d = self._route_distance(route, row["lat"], row["lng"])
                d_user = haversine(lat, lng, row["lat"], row["lng"])
            else:
                d = haversine(alat, alng, row["lat"], row["lng"])
                d_user = haversine(lat, lng, row["lat"], row["lng"])
            if row["srcs"] & APPROX_BIT:
                d = max(d, T["approx_m"])  # it stands somewhere in the district: it may not claim to be right here
            text = self._text_score(p.residual, c, row) if p.residual else 0.0
            tier = self._tier if p.residual else 0
            for exp in p.expansions:
                te = T["expansion_factor"] * self._text_score(exp, c, row)
                if te > text:
                    text, tier = te, min(self._tier, 2)  # another name of the entity is not what was typed
            if p.area and kind != "name" and d > max(p.area["radius"] * 2.2, 4000):
                continue
            catm = 0.0
            if p.need is not None:
                catm = self._need_match(p.need, row, db)
            elif p.scat:
                if row["scat"] == p.scat or row["scat"] in SCAT_FAMILY.get(p.scat, ()):
                    catm = 1.0
                elif p.brand and row["brand"] == p.brand:
                    catm = 0.8
                elif kind == "cat_name" and p.cat_words and self._names_have(p.cat_words, row):
                    catm = T["cat_in_name"]  # «Zepter Rehab City - Cloud 9 Mall» answers «cloud9 mall»
            if kind == "category":
                if (p.need is not None and catm <= 0.0) or (p.need is None and catm < 1.0):
                    continue
                if p.need is not None:
                    w = T["w_need"]
                    text_part = catm  # its name says it sells it, else it is a kind that does
                    catm = 1.0
                else:
                    w = T["w_category"]
                    text_part = 1.0
                prox = math.exp(-d / tau) + T["far_tail"] / (1.0 + d / T["far_tail_m"])
                tier = 2
                if p.need is not None and d > T["need_far_m"]:
                    continue
            elif kind == "cat_name":
                if p.need is not None:
                    catm = 1.0 if catm > 0.0 else 0.0
                if text < T["min_text_cat_name"] and catm < 1.0:
                    continue
                if text < T["min_text_cat_name"] * 0.6:
                    continue
                w = T["w_cat_name"]
                prox = 1.0 / (1.0 + d / max(tau, T["name_half_m"] * 0.5))
                text_part = text
                if catm <= 0.0 and tier >= 2:
                    tier = 1  # «مستشفى السلام»: a mosque called «السلام» answers only as a fallback
                elif tier == 3 and catm < 0.8 and not self._is_exact(p.cat_words + p.residual, row):
                    tier = 2  # «السلام» alone is not «مستشفى السلام» unless it IS a hospital
                elif tier == 2 and self._is_exact(p.cat_words + p.residual, row):
                    tier = 3
            elif kind == "brand":
                is_branch = row["brand"] == p.brand
                if (not is_branch and row["kind"] == 0 and text >= T["soft_branch_text"] and p.brand_scat
                        and _brand_family(row["scat"], p.brand_scat)):
                    is_branch = True  # «بنزينة الشرقاوي مصر للبترول»: an untagged branch, by name and kind
                if not is_branch and (text < T["min_text_brand_other"] or row["kind"] != 0):
                    continue  # a street named after the bank is not one of its branches
                w = T["w_brand"]
                prox = math.exp(-d / max(tau, 4000.0)) + T["far_tail"] / (1.0 + d / T["far_tail_m"])
                text_part = 1.0 if is_branch else text * 0.6
                catm = 1.0 if is_branch else catm
                tier = 2 if is_branch else min(tier, 1)  # «كنتاكي» the mosque is not a KFC
            else:
                if p.complete is not None and (row["scat"] == p.complete[0] or
                                               row["scat"] in SCAT_FAMILY.get(p.complete[0], ())):
                    # «مطع»: the place is of the kind the word being typed completes to («مطعم»)
                    tc = self.word_match(p.residual[0], True, [(p.complete[1], 0, True)])
                    if tc > text:
                        text = tc
                    tier = max(tier, 2)
                if text < T["min_text_name"]:
                    continue
                if row["kind"] == 2 and p.street:
                    w = T["w_street"]
                    prox = 1.0 / (1.0 + d / T["street_half_m"])
                elif typing and tier < 3 and self._last_q < T["q_stem"]:
                    # only a word still being typed: «دهب», "auc" typed whole are the places called that, wherever they are
                    w = T["w_typing"]
                    prox = 1.0 / (1.0 + d / T["typing_half_m"])
                else:
                    w = T["w_area"] if row["kind"] == 1 else T["w_name"]
                    prox = 1.0 / (1.0 + d / T["name_half_m"])
                text_part = text
                if p.area and not p.area.get("road") and not p.area_led and d > max(p.area["radius"] * 3, T["area_reach_m"]):
                    continue  # «شارع الجلاء قنا» is not the street in Sohag; nothing there = the reading without the town
                if tier < 2 and d_user > T["fallback_far_m"] and row["pop"] < T["fallback_far_pop"]:
                    continue
                if row["srcs"] & LONGTAIL_BIT and tier < 2:
                    continue
                if tier == 3 and len(p.residual) == 1 and len(p.residual[0]) < T["exact_short_len"] and \
                        d > T["exact_short_m"]:
                    tier = 2  # «baz» is a far village's whole name, not what is being typed
            s = w[0] * text_part + w[1] * prox + w[2] * row["pop"] + w[3] * row["conf"] + w[4] * catm
            if row["srcs"] & LONGTAIL_BIT:
                if kind in ("category", "brand"):
                    continue
                s -= T["longtail_penalty"]
            if kind == "name" and row["kind"] == 2 and not p.street:
                s -= T["street_unasked"]
            if p.street and row["kind"] == 2:
                s += T["street_word_boost"]
                if p.road_word and row["cat"] in ("road", "highway", "axis", "bridge"):
                    s += T["road_word_boost"]
            s += T["tier_gap"] * min(tier, 2) + (T["exact_bonus"] if tier == 3 else 0.0)
            if tier == 3:
                self._saw_exact = True
            out.append(Result(db, pid, row["pid"], row["kind"], row["cat"], row["scat"], row["lat"], row["lng"],
                              row["name_ar"], row["name_en"], d_user, s, text,
                              {"text": round(text_part, 3), "prox": round(prox, 3), "pop": row["pop"],
                               "conf": row["conf"], "cat": catm, "kind": kind, "tier": tier} if explain else {},
                              dict(row), d, tier))
        if p.entity and kind == "name":
            out.extend(self._entity_result(p, out, lat, lng, explain))
        if kind in ("name", "cat_name"):
            self._chain_strength(out)
        out.sort(key=_rank)
        if kind == "name":
            out = self._detected_brand(out, alat, alng, tau)
        return self._collapse(out, limit)

    def _typing_cut(self, cands: dict, scope: list, lat: float, lng: float) -> dict:
        """While a word is being typed thousands of names start with it and ten are read. Every candidate is ranked on what needs no
        text work (distance, prominence, confidence: the typing profile without its text term) and only the best typing_cap are scored."""
        T = self.T
        w = T["w_typing"]
        rank = {db: i for i, db in enumerate(scope)}
        order = []
        for k, c in cands.items():
            row = c.get("row") or self._row(k[0], k[1])
            if row is None:
                continue
            c["row"] = row
            d = haversine(lat, lng, row["lat"], row["lng"])
            if row["srcs"] & APPROX_BIT:
                d = max(d, T["approx_m"])
            cheap = w[1] / (1.0 + d / T["typing_half_m"]) + w[2] * row["pop"] + w[3] * row["conf"]
            order.append((-cheap, rank.get(k[0], len(rank)), k[1], k))
        order.sort()
        keep = {x[3] for x in order[:T["typing_cap"]]}
        return {k: c for k, c in cands.items() if k in keep}

    def _chain_strength(self, out: list) -> None:
        """Many places answering with one brand — or one name — are a chain the user is likely after («baz» →
        Bazooka, «kans» → Kansas Fried Chicken): each real-class member gains chain_bonus × log(n) / log(chain_sat)."""
        T = self.T
        keys = []
        counts: dict = {}
        for r in out:
            k = None
            nm = r.name_en or r.name_ar
            if r.tier >= 2 and r.kind == 0 and r.scat not in NO_CHAIN_SCATS and (r.row.get("brand") or nm):
                k = r.row.get("brand") or ("n:" + tn.normalize(nm))
                counts[k] = counts.get(k, 0) + 1
            keys.append(k)
        for r, k in zip(out, keys):
            if k is not None and counts[k] >= T["chain_min"]:
                bonus = T["chain_bonus_typing"] if self._typing_now else T["chain_bonus"]
                r.score += bonus * min(1.0, math.log(counts[k]) / math.log(T["chain_sat"]))

    def _names_have(self, words: list[str], row: dict) -> bool:
        """Every word is one of the place's own name words (or a real alternative name's), by itself or its stem."""
        toks = [(t, f, x) for t, f, x in self._place_tokens(row) if (f & 3) < 2 and not (f & 8)]
        for w in words:
            self.word_match(w, False, toks)
            if self._wm_cls < 2:
                return False
        return True

    def _need_match(self, nd: dict, row: dict, db: str | None) -> float:
        """1.0 when the place's own name says it sells the need (every word of one provider phrase among its name
        words), need_cat when it is of a kind that does, else 0."""
        stems = None
        for ph in nd["provider"]:
            if stems is None:
                stems = {tn.stems(t)[-1] for t, f, _ in self._place_tokens(row, db) if (f & 3) < 2 and not (f & 12)}
            if all(w in stems for w in ph):
                return 1.0
        sc = row["scat"]
        if any(sc == c or sc in SCAT_FAMILY.get(c, ()) for c in nd["cats"]):
            return self.T["need_cat"]
        return 0.0

    def _detected_brand(self, out: list, lat: float, lng: float, tau: float) -> list:
        """A name the index knows as a chain (its places share a brand key, lexicon or auto): rank
        those branches as a chain — nearest first — the Dart BrandDetector's rule, on the index."""
        T = self.T
        top = [r for r in out[:12] if r.row.get("brand") and r.text >= T["detect_brand_text"]]
        if len(top) < T["detect_brand_min"]:
            return out
        counts: dict = {}
        for r in top:
            counts[r.row["brand"]] = counts.get(r.row["brand"], 0) + 1
        brand, n = max(counts.items(), key=lambda kv: kv[1])
        if n < T["detect_brand_min"]:
            return out
        # Only the order AMONG the chain's branches changes (nearest first, the chain law); each branch takes the
        # score of a slot the branches already held, so the answers keep ONE scale. Scoring the branches on the chain
        # scale beside answers on the name scale sank them under weaker names as soon as a name became a chain (more
        # rows → an auto brand: places-2026-10-31.3, «جروبي» from Maadi, Talaat Harb 1 → 11).
        w = T["w_brand"]
        branches = [r for r in out if r.row.get("brand") == brand and r.text >= T["detect_brand_text"]]
        slots = sorted((r.score for r in branches), reverse=True)
        for r in branches:
            d = haversine(lat, lng, r.lat, r.lng)
            if r.row["srcs"] & APPROX_BIT:
                d = max(d, T["approx_m"])
            r.score = w[0] + w[1] * (math.exp(-d / max(tau, 4000.0)) + T["far_tail"] / (1.0 + d / T["far_tail_m"])) + \
                w[2] * r.row["pop"] + w[3] * r.row["conf"] + w[4]
        branches.sort(key=_rank)
        for r, s in zip(branches, slots):
            r.score = s
        out.sort(key=_rank)
        return out

    def _entity_result(self, p: Parsed, out: list, lat: float, lng: float, explain: bool) -> list:
        """The lexicon's own pin for the named area / landmark / road when the index has no good
        match near it — a curated name must never answer with nothing."""
        T = self.T
        e = p.entity
        for r in out:
            if r.text >= 0.8 and haversine(r.lat, r.lng, e["lat"], e["lng"]) <= max(e["radius"], T["refine_m"]):
                return []
        d = haversine(lat, lng, e["lat"], e["lng"])
        w = T["w_area"] if e["kind"] == "area" else T["w_name"]
        pop = 0.6
        s = w[0] * 0.92 + w[1] * (1.0 / (1.0 + d / T["name_half_m"])) + w[2] * pop + w[3] * 0.9 + T["tier_gap"] * 2
        cat = {"area": "neighbourhood", "road": "road", "landmark": "landmark"}[e["kind"]]
        row = {"pid": "lex:" + e["id"], "kind": 1 if e["kind"] == "area" else 0, "cat": cat, "scat": None,
               "lat": e["lat"], "lng": e["lng"], "name_ar": e["ar"], "name_en": e["en"], "alt": None, "grp": None,
               "brand": None, "pop": pop, "conf": 0.9, "srcs": 0}
        return [Result("lexicon", 0, row["pid"], row["kind"], cat, None, e["lat"], e["lng"], e["ar"], e["en"], d, s,
                       1.0, {"kind": "lexicon"} if explain else {}, row, d)]

    def _tau(self, p: Parsed) -> float:
        T = self.T
        cls = self.lx.proximity.get(p.scat or p.brand_scat or "", "local")
        return {"walkable": T["tau_walkable"], "local": T["tau_local"], "destination": T["tau_destination"],
                "landmark": T["tau_landmark"]}.get(cls, T["tau_local"])

    def _row(self, db: str, pid: int):
        r = self.ix.cons[db].execute("SELECT * FROM place WHERE id = ?", (pid,)).fetchone()
        return dict(r) if r else None

    # ── text retrieval ──────────────────────────────────────────────────────
    # A query word's INDEX forms (what the tile stores) find candidates; its MATCH against a
    # candidate's own tokens (word_match) scores them. Only SELECTIVE words drive retrieval — a
    # word in thousands of names («شارع», «صيدلية», «el») would flood the candidate set, and the
    # words around it are what identify the place anyway.

    def _index_forms(self, q: str) -> list[str]:
        out = [q] + tn.stems(q)[1:]
        if not tn.has_number(q):
            for sk in tn.skeletons(q)[:2]:
                if len(sk) >= 2 and not sk.isdigit():
                    out.append("~" + sk)
        for f in tn.number_forms(q):  # «ثان» also finds «الثاني» and «2»
            if f not in out:
                out.append(f)
        return out

    def _terms(self, con, q: str, last: bool) -> list[tuple[str, int]]:
        """(index term, df) for one query word in one file: its exact forms, its completions when it
        is the word being typed, and — only when nothing else matched — its near spellings."""
        T = self.T
        out: dict[str, int] = {}
        for f in self._index_forms(q):
            r = con.execute("SELECT n FROM vocab WHERE t = ?", (f,)).fetchone()
            if r:
                out[f] = r[0]
        if last and len(q) >= 2:
            for t, n in con.execute("SELECT t, n FROM vocab WHERE t > ? AND t < ? ORDER BY n DESC, t LIMIT ?",
                                    (q, q + "\uffff", T["prefix_terms"])):
                out.setdefault(t, n)
            qs = tn.squeeze_latin(q)
            if qs != q:  # "harr" also starts "Harods"
                for t, n in con.execute("SELECT t, n FROM vocab WHERE t >= ? AND t < ? ORDER BY n DESC, t LIMIT ?",
                                        (qs, qs + "\uffff", T["prefix_terms"])):
                    out.setdefault(t, n)
            for sk in (tn.skeletons(q)[:1] if not tn.has_number(q) else []):
                if len(sk) >= 3 and not sk.isdigit():
                    for t, n in con.execute("SELECT t, n FROM vocab WHERE t > ? AND t < ? ORDER BY n DESC, t LIMIT ?",
                                            ("~" + sk, "~" + sk + "\uffff", T["prefix_terms"] // 2)):
                        out.setdefault(t, n)
        if not out and not tn.has_number(q):
            for sk in tn.skeletons(q)[:1]:
                if len(sk) >= 4:
                    for t, n in con.execute("SELECT t, n FROM vocab WHERE t >= ? AND t < ? AND length(t) BETWEEN ? AND ? ORDER BY t",
                                            ("~" + sk[0], "~" + sk[0] + "\uffff", len(sk), len(sk) + 2)):
                        if tn.damerau(sk, t[1:], 1) <= 1:
                            out.setdefault(t, n)
        if not any(not t.startswith("~") for t in out) and len(q) >= 3 and not tn.has_number(q):
            qf = tn.stems(q)[-1]  # an article never carries the typo
            budget = tn.max_edits(qf)
            if budget:
                first = qf[0]
                scored = []
                for t, n in con.execute("SELECT t, n FROM vocab WHERE t >= ? AND t < ? AND length(t) BETWEEN ? AND ? ORDER BY t",
                                        (first, first + "\uffff", len(qf) - budget, len(qf) + budget)):
                    e = tn.damerau(qf, t, budget)
                    if e <= budget:
                        scored.append((e, -n, t))
                scored.sort()
                for e, n, t in scored[:T["fuzzy_terms"]]:
                    out.setdefault(t, -n)
        return list(out.items())

    def _text_candidates(self, words: list[str], scope: list[str], cands: dict, prefix: bool = True):
        """`prefix` = the last word may be one being typed (False for a need's provider phrase)."""
        T = self.T
        n = len(words)
        per_word = []  # [(word index, [(db, term, df)], total df)]
        for wi, q in enumerate(words):
            terms = []
            for db in scope:
                for t, df in self._terms(self.ix.cons[db], q, prefix and wi == n - 1):
                    terms.append((db, t, df))
            total = sum(df for _, _, df in terms)
            per_word.append((wi, terms, total))
        # "cloud 9" also finds a place written "Cloud9": a word and a number beside it, joined (exact forms only)
        for wi in range(n - 1):
            a, b = words[wi], words[wi + 1]
            if (tn.is_digits(a) or tn.is_digits(b)) and len(a) + len(b) <= 12:
                terms = []
                for db in scope:
                    r = self.ix.cons[db].execute("SELECT n FROM vocab WHERE t = ?", (a + b,)).fetchone()
                    if r:
                        terms.append((db, a + b, r[0]))
                if terms:
                    per_word.append((n + wi, terms, sum(df for _, _, df in terms)))
        usable = [w for w in per_word if w[1]]
        if not usable:
            return
        usable.sort(key=lambda w: w[2])
        drivers = [w for w in usable if w[2] <= T["driver_df"]] or usable[:1]
        drivers = drivers[:T["max_drivers"]]
        pre: dict[tuple[str, int], float] = {}
        for wi, terms, _ in drivers:
            for db, t, _ in terms:
                for pid, f in self.ix.cons[db].execute("SELECT id, f FROM tok WHERE t = ? ORDER BY id LIMIT ?", (t, T["max_postings"])):
                    k = (db, pid)
                    pre[k] = pre.get(k, 0.0) + (1.0 if (f & 3) == 0 else 0.6)
        if len(usable) >= 2 and usable[0][2] > T["driver_df"]:
            # every word is common («أبو السيد», «حلواني العبد»: each word is in thousands of names, the
            # place in a few): a place holding BOTH of the two rarest words outranks one holding the
            # driver alone, so the cap below can never drop it
            a, b = usable[0][1], usable[1][1]
            for db in scope:
                ta = [t for d, t, _ in a if d == db][:T["join_terms"]]
                tb = [t for d, t, _ in b if d == db][:T["join_terms"]]
                if not ta or not tb:
                    continue
                sql = ("SELECT DISTINCT x.id FROM tok x JOIN tok y ON y.id = x.id AND y.t IN ("
                       + ",".join("?" * len(tb)) + ") WHERE x.t IN (" + ",".join("?" * len(ta))
                       + ") ORDER BY x.id LIMIT ?")
                for (pid,) in self.ix.cons[db].execute(sql, (*tb, *ta, T["max_postings"])):
                    k = (db, pid)
                    pre[k] = pre.get(k, 0.0) + 1.0
        if len(pre) > T["max_candidates"]:
            # nearest tile first (scope is nearest-first): the cap drops far candidates, never near ones
            rank = {db: i for i, db in enumerate(scope)}
            keep = sorted(pre.items(), key=lambda kv: (-kv[1], rank[kv[0][0]], kv[0][1]))[:T["max_candidates"]]
            pre = dict(keep)
        for k in pre:
            c = cands.setdefault(k, {})
            c["_db"] = k[0]
            c["text"] = True

    # ── in-memory word match (the same function scores every candidate, wherever it came from)

    def _area_text(self, db: str | None, aid) -> str | None:
        """The names of the area a row points at (its file's `area` table), «ar\\x1fen»."""
        if db is None or aid is None:
            return None
        key = (db, aid)
        if key not in self._area_names:
            r = self.ix.cons[db].execute("SELECT ar, en FROM area WHERE id = ?", (aid,)).fetchone()
            self._area_names[key] = "\x1f".join(x for x in (r[0], r[1]) if x) or None if r else None
        return self._area_names[key]

    def _place_tokens(self, row: dict, db: str | None = None) -> list[tuple[str, int, bool]]:
        """Field 0 the names, 1 the alternative names, 2 the address, 3 the place's own AREA: a query that
        names a neighbourhood the parse did not read as one («Trust Code مساكن الجيزة») still finds it."""
        out = []
        # names generated in the other script (names.py) follow a "\x1e" in `alt`: field bit 8, a fallback
        real_alt, _, gen_alt = (row.get("alt") or "").partition("\x1e")
        for field_, text in ((0, row.get("name_ar")), (0, row.get("name_en")), (1, real_alt), (9, gen_alt),
                             (2, row.get("addr")), (3, self._area_text(db, row.get("area")))):
            if not text:
                continue
            for part in text.split("\x1f"):
                toks = [t for t in tn.tokens(part) if not tn.is_stopword(t)]
                for i, t in enumerate(toks):
                    out.append((t, field_, i == 0))
                    if (field_ & 3) < 2:
                        for x in tn.alnum_parts(t):  # "Cloud9" is also "cloud 9"
                            out.append((x, field_, False))
                if (field_ & 3) < 2:
                    for i in range(len(toks) - 1):
                        if len(toks[i]) + len(toks[i + 1]) <= 12:
                            out.append((toks[i] + toks[i + 1], field_ | 4, False))
                        v = tn.number_value(toks[i + 1])
                        if v is not None and not tn.is_digits(toks[i + 1]) and not tn.is_arabic_token(toks[i]) \
                                and not tn.has_number(toks[i]):
                            out.append((toks[i] + v, field_ | 4, False))  # "Cloud Nine" is also "cloud9"
        return out

    def _prefix_qual(self, q: str, q_stem: str, t: str, ts: list, first: bool) -> float:
        T = self.T
        core = t if t.startswith(q) else ts[-1]
        ratio = len(q if t.startswith(q) else q_stem) / max(1, len(core))
        qual = T["q_prefix_min"] + (T["q_prefix_max"] - T["q_prefix_min"]) * ratio
        if len(q) == 1 and not first:
            qual *= 0.6
        return qual

    def word_match(self, q: str, last: bool, toks: list[tuple[str, int, bool]]) -> float:
        """The best quality of one query word against a place's tokens. Also sets self._wm_cls, the word's MATCH
        CLASS: 2 = real (on a name or a real alternative name: the word, its stem, the same number, a joined pair, the
        start of a name word while typing, a vowel spelling of a word of 4+ letters), 1 = only a fallback (a skeleton,
        a typo, a generated other-script name, the address, the area), 0 = no match. A word with a digit matches
        only exactly: «cloud9» is not «cloud 5»."""
        T = self.T
        qs = tn.stems(q)
        q_stem = qs[-1]
        q_loose = tn.loose(q)
        q_num = tn.number_value(q)
        q_dig = tn.has_number(q)
        q_sq = tn.squeeze_latin(q)
        q_sk = [s for s in tn.skeletons(q) if len(s) >= 2 and not s.isdigit()] if not q_dig else []
        budget = tn.max_edits(q) if not q_dig else 0
        best = 0.0
        real_best = 0.0
        generic = self.lx.generic
        for t, field_, first in toks:
            join = (field_ & 4) != 0
            gen = (field_ & 8) != 0
            fld = field_ & 3
            if fld >= 2 and best >= T["f_addr"]:
                break  # the address and the area come last and can add nothing to a name match this good
            ts = tn.stems(t)
            real = True
            if t == q:
                qual = T["q_join"] if join else T["q_word"]
            elif ts[-1] == q_stem or q in ts or t in qs:
                qual = T["q_join"] if join else T["q_stem"]
            elif q_num is not None and not join and tn.number_value(t) == q_num:
                qual = T["q_stem"]  # «ثان» = «الثاني» = «2»
            elif ts[-1] in generic or t in generic:
                # a word that says what KIND of place: never a skeleton or a typo, only completed while typing
                if not (last and not join and len(q) >= 2 and (t.startswith(q) or ts[-1].startswith(q_stem))):
                    continue
                qual = self._prefix_qual(q, q_stem, t, ts, first) * T["q_generic_prefix"]
            elif q_dig or tn.has_number(t):
                if not (last and not join and not tn.is_digits(q) and t.startswith(q)):
                    continue  # "9" never completes "90"; "cloud" completes "cloud9"
                qual = self._prefix_qual(q, q_stem, t, ts, first)
            elif not join and len(q_loose) >= 2 and tn.loose(t) == q_loose:
                qual = T["q_loose"]
                # a finished word in another vowel spelling is real («السيد» = «سيدي», «سبينيز» = «سبينز»); the word being
                # typed needs four consonants for it («مطع» is not «المطيعة», "kans" not "Kanayis")
                real = len(q_loose) >= 4 or not last
                if not real and last and (t.startswith(q) or ts[-1].startswith(q_stem)):
                    # … but the start of the word being typed is real whatever its vowels («البحر» → «البحري»)
                    real = True
                    qual = max(qual, self._prefix_qual(q, q_stem, t, ts, first))
            elif last and (t.startswith(q) or ts[-1].startswith(q_stem)) and len(q) >= 1:
                qual = self._prefix_qual(q, q_stem, t, ts, first)
            elif last and q_sq != q and tn.squeeze_latin(t).startswith(q_sq):
                qual = self._prefix_qual(q_sq, q_sq, tn.squeeze_latin(t), [tn.squeeze_latin(t)], first)
            else:
                if real_best >= T["q_skel"] + T["first_word_bonus"]:
                    continue  # no fallback reaches a real match this good: the skeletons and typos of this name cost most of a keystroke
                real = False
                qual = 0.0
                t_sk = [s for s in tn.skeletons(t) if len(s) >= 2]
                short = len(q) <= 3
                for a in q_sk:
                    for b in t_sk:
                        if a == b:
                            if len(a) >= 3:
                                v = T["q_skel"]
                                if (self._multi or (len(q) >= T["translit_len"] and len(a) >= T["translit_skel"])) and \
                                        tn.is_arabic_token(q) != tn.is_arabic_token(t):
                                    real = True  # «مول مصر» ⇄ "mol masr", «بازوكا» ⇄ Bazooka; never "kans" ⇄ «الكنائس»
                            elif len(q_stem) <= 6 and len(ts[-1]) <= 6:
                                v = T["q_skel2"]  # «maadi» ⇄ «المعادي» ("md"), never «mohamed»
                            else:
                                continue
                            qual = max(qual, v * (T["short_skel_factor"] if short else 1.0))
                        elif last and len(a) >= 2 and b.startswith(a):
                            qual = max(qual, T["q_skel_prefix"])
                        elif len(a) >= 4 and len(b) >= 4 and abs(len(a) - len(b)) <= 1 and tn.damerau(a, b, 1) <= 1:
                            qual = max(qual, T["q_skel_fuzzy"])  # «سبينيز» ⇄ «سبينس» ⇄ "spinneys"
                if qual == 0.0 and budget and not join and abs(len(t) - len(q)) <= budget:
                    e = tn.damerau(q, t, budget)
                    if e <= budget:
                        qual = T["q_fuzzy1"] if e == 1 else T["q_fuzzy2"]
            if qual == 0.0:
                continue
            qual *= (T["f_name"], T["f_alt"], T["f_addr"], T["f_area"])[fld]
            if gen:
                qual *= T["f_gen"]
            if first and fld == 0:
                qual = min(1.0, qual + T["first_word_bonus"])
            if real and fld < 2 and not gen and qual > real_best:
                real_best = qual
            if qual > best:
                best = qual
                if best >= 1.0 and real_best >= 1.0:
                    break
        self._wm_cls = 2 if real_best > 0.0 else (1 if best > 0.0 else 0)
        return best

    def _idf(self, db: str, word: str) -> float:
        con = self.ix.cons[db]
        df = 0
        for f in [word] + tn.stems(word)[1:]:
            r = con.execute("SELECT n FROM vocab WHERE t = ?", (f,)).fetchone()
            if r:
                df = max(df, r[0])
        N = max(1, self.ix.nplaces.get(db, 1000))
        return math.log(1 + N / (1 + df)) / math.log(1 + N)

    def _text_score(self, words: list[str], c: dict, row: dict) -> float:
        """The text score of a place for the query words; also sets self._tier, the place's MATCH CLASS for them:
        3 = its whole name (or a real alternative name) is the query, 2 = every word matched a real name
        (word_match class 2), 1 = some word only by a fallback or not at all, 0 = no text match."""
        T = self.T
        self._tier = 0
        self._last_q = 0.0
        self._multi = len(words) >= 2 or self._qlen >= 2  # «mol masr»: the category word counts
        toks = self._place_tokens(row, c.get("_db"))
        if not toks:
            return 0.0
        n = len(words)
        quals, clss = [], []
        for i, w in enumerate(words):
            quals.append(self.word_match(w, i == n - 1, toks))
            clss.append(self._wm_cls)
        self._last_q = quals[-1] if quals else 0.0
        ws = [max(0.12, self._idf_cached(c.get("_db", "national"), w)) for w in words]
        tot = sum(ws)
        missing = [i for i in range(n) if quals[i] == 0.0]
        if missing:
            if n <= 2:
                return 0.0
            if len(missing) > 1 or ws[missing[0]] > 0.5 * tot:
                return 0.0
        text = sum(ws[i] * quals[i] for i in range(n)) / tot
        # coverage: how much of the place's own (display) name the query accounts for — or the START of it, the
        # way a name is typed («baz» → «Bazooka Fried Chicken»)
        best_cov = 0.0
        for nm in (row.get("name_ar"), row.get("name_en")):
            if not nm:
                continue
            nt = [(t, 0, i == 0) for i, t in enumerate(x for x in tn.tokens(nm) if not tn.is_stopword(x))]
            if not nt:
                continue
            hit = 0
            for t in nt:
                if any(self.word_match(w, i == n - 1, [t]) >= 0.7 for i, w in enumerate(words)):
                    hit += 1
            cov = hit / len(nt)
            # only while the last word is still being typed: «مجمع» typed whole is not the start of «مجمع معابد دندرة»
            if cov < T["lead_cov"] and n <= len(nt) and self._typing(words[-1], nt[n - 1][0]) and \
                    all(self.word_match(words[i], i == n - 1, [nt[i]]) >= 0.7 for i in range(n)):
                cov = T["lead_cov"]
            best_cov = max(best_cov, cov)
        text = (1 - T["coverage_share"]) * text + T["coverage_share"] * best_cov
        if best_cov >= 0.999 and not missing and min(quals) >= 0.9:
            text = min(1.0, text + T["exact_name_bonus"])
        if missing or min(clss) < 2:
            self._tier = 1
        else:
            # the whole name, when the query names something (a kind word alone, «جامعة», is never a whole name)
            named = any(tn.stems(w)[-1] not in self.lx.generic for w in words)
            self._tier = 3 if named and self._is_exact(words, row) else 2
        return text

    @staticmethod
    def _typing(q: str, t: str) -> bool:
        """The name word t continues q, which is not yet a whole word of it ("baz" → "bazooka")."""
        ts = tn.stems(t)
        q_stem = tn.stems(q)[-1]
        if t == q or ts[-1] == q_stem or q in ts:
            return False
        return t.startswith(q) or ts[-1].startswith(q_stem)

    @staticmethod
    def _canon(t: str) -> str:
        v = tn.number_value(t)
        return v if v is not None else tn.stems(t)[-1]

    def _is_exact(self, words: list[str], row: dict) -> bool:
        """The place's whole name — or one of its real alternative names — is the query: the same words (stems, the
        same numbers) in any order, or the same letters without spaces («cloud9 mall» = «Cloud 9 Mall»)."""
        qw = [w for w in words if not tn.is_stopword(w)]
        if not qw:
            return False
        want = sorted(self._canon(w) for w in qw)
        joined = "".join(qw)
        real_alt = (row.get("alt") or "").partition("\x1e")[0]
        for nm in [row.get("name_ar"), row.get("name_en")] + real_alt.split("\x1f"):
            nt = [x for x in tn.tokens(nm or "") if not tn.is_stopword(x)]
            if nt and (sorted(self._canon(x) for x in nt) == want or "".join(nt) == joined):
                return True
        return False

    def _idf_cached(self, db, w):
        key = (db, w)
        if not hasattr(self, "_idfc"):
            self._idfc = {}
        if key not in self._idfc:
            self._idfc[key] = self._idf(db, w)
        return self._idfc[key]

    def _category_candidates(self, scat, lat, lng, scope, cands, p, route):
        T = self.T
        radius = T["category_radius0"]
        cls = self.lx.proximity.get(scat, "local")
        cap = T["category_radius_cap"] * (2.5 if cls in ("destination", "landmark") else 1.0)
        if p.area:
            radius = max(radius, p.area["radius"] * 1.5)
        pts = route if route else [(lat, lng)]
        while True:
            found = 0
            seen = set()
            for (qlat, qlng) in pts[:: max(1, len(pts) // 12)] if route else pts:
                dlat = radius / 111000.0
                dlng = radius / (111000.0 * max(0.2, math.cos(math.radians(qlat))))
                for db in self.ix.near(qlat, qlng, radius):
                    con = self.ix.cons[db]
                    rows = [r for member in SCAT_FAMILY.get(scat, (scat,)) for r in con.execute(
                        "SELECT * FROM place WHERE scat = ? AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
                        (member, qlat - dlat, qlat + dlat, qlng - dlng, qlng + dlng))]
                    for r in rows:
                        k = (db, r["id"])
                        if k in seen or r["srcs"] & LONGTAIL_BIT:
                            continue
                        seen.add(k)
                        if haversine(qlat, qlng, r["lat"], r["lng"]) <= radius:
                            c = cands.setdefault(k, {"m": {}})
                            c["row"] = dict(r)
                            c["_db"] = db
                            found += 1
            if found >= T["category_min"] or radius >= cap:
                break
            radius *= 2

    def _brand_candidates(self, brand, lat, lng, cands):
        found = []
        for i, db in enumerate(self.ix.near(lat, lng, 25000)):
            for r in self.ix.cons[db].execute("SELECT * FROM place WHERE brand = ?", (brand,)):
                found.append((haversine(lat, lng, r["lat"], r["lng"]), i, r["id"], db, dict(r)))
        found.sort(key=lambda x: x[:3])  # a chain has thousands of branches and the nearest are what is asked for
        for _, _, pid, db, row in found[:self.T["brand_cap"]]:
            c = cands.setdefault((db, pid), {"m": {}})
            c["row"] = row
            c["_db"] = db

    def _route_distance(self, route, lat, lng):
        return min(haversine(lat, lng, a, b) for a, b in route[:: max(1, len(route) // 200)])

    def _collapse(self, rs: list[Result], limit: int) -> list[Result]:
        """One row per place: the pieces of one street become the piece NEAREST what the query is measured
        from (the named area, the route, else the user), keeping the best piece's score; same-name
        same-category rows within collapse_m become the best one."""
        T = self.T
        best_piece: dict[str, Result] = {}
        top_score: dict[str, float] = {}
        for r in rs:
            g = r.row.get("grp")
            if g:
                top_score[g] = max(top_score.get(g, 0.0), r.score)
                if g not in best_piece or r.adist < best_piece[g].adist:
                    best_piece[g] = r
        if best_piece:
            kept = []
            for r in rs:
                g = r.row.get("grp")
                if g:
                    if best_piece[g] is r:
                        r.score = top_score[g]
                        kept.append(r)
                else:
                    kept.append(r)
            rs = sorted(kept, key=_rank)
        out: list[Result] = []
        for r in rs:
            nk = tn.normalize(r.name_ar or r.name_en or "")
            dup = False
            for o in out:
                if o.cat == r.cat or o.scat == r.scat:
                    on = tn.normalize(o.name_ar or o.name_en or "")
                    if on == nk and haversine(o.lat, o.lng, r.lat, r.lng) < T["collapse_m"]:
                        dup = True
                        break
            if not dup:
                out.append(r)
                if len(out) >= limit:  # nobody reads further: comparing every row with every row cost 80 % of a keystroke
                    break
        return out
