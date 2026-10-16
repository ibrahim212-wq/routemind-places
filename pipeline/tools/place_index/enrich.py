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
from collections import Counter, defaultdict

from . import merge as M
from . import records as R
from . import taxonomy as T
from . import textnorm as tn

ONLINE_HOSTS = ("instagram.com", "tiktok.com", "amazon.", "t.me", "wordpress.com", "youtube.com", "linktr.ee",
                "wa.me", "whatsapp", "jumia.com", "noon.com", "blogspot.", "facebook.com/share")
ALWAYS_KEEP = {"hospital", "emergency_room", "pharmacy", "clinic", "medical_center", "police", "gas_station",
               "government", "school", "university", "mosque", "church", "bank", "atm", "post_office"}


def keep(rec: R.Record) -> bool:
    """Drop a Meta row that is almost certainly an online-only shop or a personal page."""
    if rec.src not in (R.SRC_META, R.SRC_OVT_OTHER):
        return True
    web = (rec.website or "").lower()
    online = any(h in web for h in ONLINE_HOSTS)
    if online and rec.conf < 0.45 and rec.cat not in ALWAYS_KEEP:
        return False
    if rec.conf < 0.2 and rec.cat not in ALWAYS_KEEP:
        return False
    if rec.conf < 0.12:
        return False
    return True


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
            if not gid:
                continue
            common = (r["names"] or {}).get("common") or {}
            common = dict(common) if not isinstance(common, dict) else common
            self.names[gid] = (nm, common.get("en") or gid.replace("_", " ").title())
            self.polys.append(shapely.from_wkb(r["geometry"]))
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
        for b in lexicon.get("brands", []):
            aliases = set(b.get("aliases") or []) | {b.get("display_ar") or "", b.get("display_en") or ""}
            for a in aliases:
                # stopwords stay: "el abd" is two words, and "Abd" alone is half the names in Egypt
                toks = tuple(tn.tokens(a))
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

        in_names = {bid for n in names for _, bid, *_ in self._spans(n)}
        best = None
        for name, trusted in [(n, False) for n in names] + ([(source_brand, True)] if source_brand else []):
            for alias, bid, bcat, alone, first, other in self._spans(name):
                if known and bcat and not agrees(bcat):
                    continue  # another kind of place under the same word
                if trusted and not known and bid not in in_names:
                    continue  # a source's brand on a "building" / "place" the name never ties to the chain
                if not trusted:
                    if other:
                        continue
                    if len(alias) == 1 and not (alone or (first and agrees(bcat))):
                        continue
                    if len(alias) > 1 and not (alone or first or agrees(bcat)):
                        continue
                key = (len(alias), trusted, bid)
                if best is None or key > best[0]:
                    best = (key, bid)
        return best[1] if best else None


def _brand_cat_ok(brand_cat: str, scat: str) -> bool:
    if brand_cat == scat:
        return True
    related = [{"bank", "atm", "exchange"}, {"pharmacy", "clinic", "medical_lab"}, {"restaurant", "fast_food", "cafe",
               "pizza", "burger", "sweets", "bakery", "juice_bar"}, {"supermarket", "mall", "market"},
               {"mobile_shop", "electronics_store", "appliance_store"}, {"gas_station", "car_repair", "oil_change"}]
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
