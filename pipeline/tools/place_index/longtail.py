"""The long tail: real names the index used to throw away, findable by name but never shown as "near me".

Two sources, neither of them a new provider:

  weak_places    the rows `enrich.keep_reason` drops and `enrich.rescue` does not bring back: low-confidence Facebook pages and
                 Foursquare venues nobody refreshed in 7 years. Too doubtful to list under "pharmacy near me"; but when someone
                 types the name of a small business, a doubtful answer beats none.
  mentioned      places and streets named inside other places' addresses and names («بجوار كافيه الماسة», «امام اولاد رضوان
                 للسيراميك», «شارع عرفات متفرع من …») that no source has as a place. A person wrote that the place stands
                 there, so the mentioning page's pin is evidence of where it is.

A row of the long tail carries LONGTAIL_BIT in `srcs`. The engine (all four copies) never returns it for a category or a chain
list, only for a name whose every word really matched, under every stronger answer. A chain branch named by an address is NOT
long tail: «بجوار بيم» in Sohag is the evidence the chain list lacks, so it is a branch (DERIVED_BIT, brand key set).
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

from . import merge as M
from . import records as R
from . import textnorm as tn

LONGTAIL_BIT = 4096
DERIVED_BIT = 2048

WEAK_CONF_MAX = 0.3
WEAK_POP_MAX = 0.2
SAME_PLACE_M = 150.0
GROUP_M = 400.0           # mentions of one name this close are one place
KNOWN_M = 1200.0          # a mention of a place on record this near is that place: it already counted (enrich.mentions)
STREET_KNOWN_M = 3000.0   # a street of that name this near is that street
MAX_WORDS = 6
KNOWN_SCAN_MAX = 4000     # a word on more rows than this says nothing about one place

_REL = r"(?:بجوار|بجانب|بجنب|جنب|امام|أمام|إمام|قدام|خلف|ورا|وراء|داخل|جوه|تحت|فوق|عند|next to|behind|opposite|in front of|inside|near)"
_RE_REL = re.compile(_REL + r"\s+([^\d,،؛:;\-–—\.\(\)\\/\n\r|]{3,60})", re.I)
_RE_STREET = re.compile(r"(?:^|[\s,،\-–—\(])(شارع|ش\.|ش |طريق|حارة|حاره|عطفة|زقاق)\s*([^\d,،؛:;\-–—\.\(\)\\/\n\r|]{3,40})", re.I)
_RE_STOP = re.compile(r"\s(?:و?" + _REL + r"|متفرع|تقاطع|ناصية|ناصيه|الدور|دور|عمارة|عماره|برج|رقم|مدخل|فرع|بعد|قبل|من|في|فى|على|علي|مع|at|on|in|of)\s.*$", re.I)
_RE_PART = re.compile(r"^(?:سور|بوابة|بوابه|سلم|باب|ناصية|ناصيه|مدخل|سلالم|gate of|entrance of)\s+", re.I)
_RE_ROAD = re.compile(r"^(?:شارع|ش\.?|طريق|حارة|حاره|عطفة|زقاق|street|road)\s", re.I)
# a place word alone, a road part, a direction: nothing to go to
_NOT_A_PLACE = {"بوابة", "بوابه", "المدخل", "مدخل", "المحطة", "المحطه", "الشارع", "شارع", "الميدان", "ميدان", "الكوبري", "كوبري", "الطريق", "البحر", "النيل",
                "السوق", "الموقف", "المسجد", "الجامع", "المدرسة", "المدرسه", "العمارة", "العماره", "البرج", "الدائري", "الدائرى", "main", "gate", "the", "street",
                "road", "bridge", "square", "station", "mosque", "school", "market", "tower", "building"}


def _clean(text: str) -> str | None:
    s = _RE_STOP.sub("", " " + text.strip() + " ").strip(" .,،-–—_:;\"'«»")
    s = re.sub(r"\s+", " ", s)
    s = _RE_PART.sub("", s)  # «سور الامن المركزي» stands beside the security HQ; «بوابة مدرسة …» is the school
    toks = s.split(" ")
    if not s or len(toks) > MAX_WORDS or len(s) < 3 or sum(ch.isalpha() for ch in s) < 3:
        return None
    return s


def _words(text: str) -> list[str]:
    return [tn.stems(t)[-1] for t in tn.tokens(text) if not tn.is_stopword(t)]


def _same_name(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return small <= big or len(sa & sb) / max(1, len(small)) >= 0.9


class _Known:
    """Who is already on record, by name word: a name is looked up through its rarest word, so Cairo costs what Sohag costs."""

    def __init__(self, places: list):
        self.by_word: dict[str, list] = defaultdict(list)
        for p in places:
            names = [_words(n) for n in (p.name_ar, p.name_en, *p.alt) if n]
            entry = (p.lat, p.lng, p.kind, names)
            for w in {w for n in names for w in n}:
                self.by_word[w].append(entry)

    def has(self, words: list[str], lat: float, lng: float, radius: float, street: bool | None = None) -> bool:
        if not words:
            return False
        # every word's list but the commonest words': a shorter name on record («الزمالك» for «نادي الزمالك») may lack the rarest word
        lists = sorted((self.by_word.get(w, ()) for w in set(words)), key=len)
        dlat = radius / 111000.0
        for i, rows in enumerate(lists):
            if i and len(rows) > KNOWN_SCAN_MAX:
                break
            for plat, plng, kind, names in rows:
                if abs(plat - lat) > dlat or (street is not None and (kind == "street") != street):
                    continue
                if R.haversine(lat, lng, plat, plng) <= radius and any(_same_name(words, n) for n in names):
                    return True
        return False


def weak_places(weak_recs: list, known: list, report: dict) -> list:
    """The dropped rows as places of their own, minus what is already on record under the same name."""
    if not weak_recs:
        report["longtail"] = {"weak_rows": 0, "weak_places": 0}
        return []
    ps = M.merge(weak_recs)
    k = _Known(known)
    out = []
    for p in ps:
        if p.kind != "poi":
            continue
        words = _words(p.name_ar or p.name_en or "")
        if not words or k.has(words, p.lat, p.lng, SAME_PLACE_M):
            continue
        p.srcs |= LONGTAIL_BIT
        p.conf = min(p.conf, WEAK_CONF_MAX)
        p.pop = min(p.pop, WEAK_POP_MAX)
        out.append(p)
    report["longtail"] = {"weak_rows": len(weak_recs), "weak_merged": len(ps), "weak_places": len(out)}
    return out


def _script(s: str) -> str:
    return "ar" if any("؀" <= c <= "ۿ" for c in s) else "la"


def _new_place(key: str, kind: str, cat: str, lat: float, lng: float, spell: Counter, srcs: int, conf: float, pop: float):
    ar = next((s for s, _ in spell.most_common() if _script(s) == "ar"), None)
    en = next((s for s, _ in spell.most_common() if _script(s) == "la"), None)
    return M.Place(pid="d" + hashlib.sha1(f"{key}|{lat:.4f}|{lng:.4f}".encode("utf-8")).hexdigest()[:14], kind=kind, cat=cat, lat=lat, lng=lng,
                   name_ar=ar, name_en=" ".join(w.capitalize() for w in en.split()) if en else None, alt=[], brand=None, phone=None, website=None,
                   social=None, hours=None, addr=None, wd=None, srcs=srcs, conf=conf, pop=pop, extent_m=0.0, population=0, members=[])


def _groups(rows: list[tuple[float, float, str, str]]) -> list[list]:
    """(lat, lng, spelling, source pid): the mentions of one name, grouped by place (GROUP_M, greedy, deterministic)."""
    groups: list[list] = []
    for r in sorted(rows, key=lambda x: (x[0], x[1], x[3])):
        for g in groups:
            if R.haversine(r[0], r[1], g[0][0], g[0][1]) <= GROUP_M:
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def mentioned(places: list, streets: list, ki, bm, generic: set, report: dict) -> tuple[list, list]:
    """(places, street points) that only other places' addresses and names know."""
    named: dict[str, list] = defaultdict(list)
    roads: dict[str, list] = defaultdict(list)
    for p in places:
        if p.kind != "poi" or p.srcs & R.APPROX_BIT:  # a district-centre pin says nothing about where the neighbour stands
            continue
        for text in (p.addr, p.name_ar, p.name_en):
            if not text:
                continue
            for m in _RE_REL.findall(text):
                c = _clean(m)
                if c and _RE_ROAD.match(c):
                    roads[" ".join(_words(c)[1:])].append((p.lat, p.lng, c, p.pid))
                elif c:
                    named[" ".join(_words(c))].append((p.lat, p.lng, c, p.pid))
        if p.addr:
            for head, m in _RE_STREET.findall(p.addr):
                c = _clean(m)
                if c:
                    prefix = {"ش.": "شارع", "ش ": "شارع"}.get(head, head.strip())
                    roads[" ".join(_words(c))].append((p.lat, p.lng, f"{prefix} {c}", p.pid))
    known_all = _Known(list(places) + list(streets))
    out_p, out_s = [], []
    for key, rows in sorted(named.items()):
        words = key.split(" ") if key else []
        if not words or (len(words) == 1 and (words[0] in generic or words[0] in _NOT_A_PLACE)):
            continue
        for g in _groups(rows):
            lat = sorted(r[0] for r in g)[len(g) // 2]
            lng = sorted(r[1] for r in g)[len(g) // 2]
            if known_all.has(words, lat, lng, KNOWN_M):
                continue
            n = len({r[3] for r in g})
            if (len(words) == 1 or all(w in generic for w in words)) and n < 2:  # «المستشفى العام», «هيبر»: only when two places agree
                continue
            spell = Counter(r[2] for r in g)
            names = list(spell)
            cat = ki.infer("place", names) or "place"
            brand_key = bm.match(names, cat, None, None)
            srcs = DERIVED_BIT | (0 if brand_key else LONGTAIL_BIT)
            p = _new_place(key, "poi", cat, lat, lng, spell, srcs, round(min(0.7, 0.4 + 0.1 * n), 3), round(min(0.4, 0.15 + 0.05 * n), 3))
            p.brand_key = brand_key
            out_p.append(p)
    for key, rows in sorted(roads.items()):
        words = key.split(" ") if key else []
        if not words or (len(words) == 1 and words[0] in _NOT_A_PLACE):
            continue
        for g in _groups(rows):
            lat = sorted(r[0] for r in g)[len(g) // 2]
            lng = sorted(r[1] for r in g)[len(g) // 2]
            if known_all.has(words, lat, lng, STREET_KNOWN_M, street=True):
                continue
            n = len({r[3] for r in g})
            out_s.append(_new_place(key, "street", "street", lat, lng, Counter(r[2] for r in g), DERIVED_BIT, round(min(0.7, 0.4 + 0.1 * n), 3),
                                    round(min(0.4, 0.15 + 0.05 * n), 3)))
    report["mentioned"] = {"names": len(named), "street_names": len(roads), "places": len(out_p),
                           "chain_branches": sum(1 for p in out_p if p.brand_key), "streets": len(out_s)}
    return out_p, out_s
