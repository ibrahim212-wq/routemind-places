"""Build the KIND + NAME benchmark (the owner's findings 2026-11-09, docs/search-goal.md): queries where a kind word meets a
name — the class «كشري اشرف» (a koshary named Ashraf, above a doctor, a tomb and streets that only share «اشرف») — and names
that CONTAIN a kind word and must not lose («مستشفى السلام», «مسجد الحسين», «بنك مصر», «سيتي ستارز»).

    python -m tools.place_index.bench.kindname_build --rows <rows.jsonl> --out tools/place_index/bench/kindname_set.json

Every judge is a REAL row of the published index (never a guess), anchored a seeded 1–3 km (kind + name) / 3–8 km (famous)
away, sampled across every governorate. The file is FROZEN: re-running re-states it on purpose. Groups:
  owner      the owner's own queries from his phone (one example per class)
  kindname   «<kind word> <name>» where the name word ALSO names places of other kinds nearby (the ambiguity that hurt)
  famous     a prominent place whose own name starts with a kind word, typed whole
  examples   the owner's named examples of names that hold a kind word (kept as they are, or better)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import defaultdict

from .. import textnorm as tn

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LEXICON = os.path.join(ROOT, "assets", "search", "egypt_lexicon.json")
SEED = 20261109
PER_GOV_KINDNAME = 6
RARE_KINDS = {"mosque", "church", "school", "university"}  # at most one of these per governorate: shops are the class
GENERIC_NAME_WORDS = {"ابو", "اولاد", "عبد", "ال", "سيدي", "الشيخ", "الحاج", "ام"}
PER_GOV_FAMOUS = 3

# the owner's examples of names that hold a kind word: name variants, city anchor (where the place is looked for), radius
EXAMPLES = [
    ("مستشفى السلام", ["مستشفى السلام", "as salam hospital", "el salam hospital"], (30.0566, 31.2003)),
    ("مسجد الحسين", ["مسجد الحسين", "الامام الحسين", "al hussein mosque"], (30.0444, 31.2357)),
    ("قهوة الفيشاوي", ["الفيشاوي", "el fishawy", "fishawi"], (30.0444, 31.2357)),
    ("مطعم الدهان", ["الدهان", "el dahan"], (30.0444, 31.2357)),
    ("جامعة القاهرة", ["جامعة القاهرة", "cairo university"], (30.0050, 31.1600)),
    ("سيتي ستارز", ["سيتي ستارز", "city stars", "citystars"], (30.0600, 31.3300)),
    ("محطة مصر", ["محطة مصر", "رمسيس", "ramses", "cairo railway station"], (30.0444, 31.2357)),
]


def dist(a, b, c, d):
    return math.hypot((a - c) * 111_000, (b - d) * 111_000 * math.cos(math.radians(a)))


def offset(rnd, lat, lng, lo_m, hi_m):
    r = rnd.uniform(lo_m, hi_m)
    t = rnd.uniform(0, 2 * math.pi)
    return (round(lat + r * math.cos(t) / 111_000, 5), round(lng + r * math.sin(t) / (111_000 * math.cos(math.radians(lat))), 5))


def kind_words() -> dict[str, str]:
    """A single kind word (normalised) → its category id, from the lexicon's own terms."""
    lx = json.load(open(LEXICON, encoding="utf8"))
    out = {}
    for c in lx["categories"]:
        for w in [c.get("label_ar") or ""] + list(c.get("terms_ar") or []):
            n = tn.normalize(w)
            if n and " " not in n and n not in out:
                out[n] = c["id"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rnd = random.Random(SEED)
    kw = kind_words()
    rows = []
    name_scats = defaultdict(set)  # (gov, name word) → the scats of places carrying it
    area_words = set()  # every word of an area / town name: «الغردقه» in a name is a place, not a name
    for line in open(a.rows, encoding="utf8"):
        r = json.loads(line)
        if r.get("kind") == 1:
            area_words.update(t for t in tn.tokens(r.get("name_ar") or "") if not tn.is_stopword(t))
            continue
        if r.get("kind") != 0 or not r.get("name_ar") or (r.get("srcs") or 0) & 4096:
            continue
        toks = [t for t in tn.tokens(r["name_ar"]) if not tn.is_stopword(t)]
        if not toks:
            continue
        r["_toks"] = toks
        rows.append(r)
        for t in toks:
            name_scats[(r.get("gov"), t)].add(r.get("scat"))
    items = []

    # owner — «كشري اشرف» from 6th of October City (the owner's phone, 2026-11-09)
    items.append({"group": "owner", "q": "كشري اشرف", "at": [29.9714, 30.9440], "g": "giza",
                  "place": {"names": ["كشري اشرف"], "near": [29.953943, 30.938204], "r": 600, "scats": ["koshary"]}})

    # kindname — a kind word + an ambiguous name word, the row of exactly that kind
    by_gov = defaultdict(list)
    for r in rows:
        t = r["_toks"]
        if len(t) not in (2, 3):
            continue
        cat = kw.get(t[0])
        if not cat or r.get("scat") != cat:
            continue
        others = name_scats[(r.get("gov"), t[1])] - {cat}
        if len(others) >= 3 and len(t[1]) >= 3 and not any(w in area_words for w in t[1:])                 and t[1] not in GENERIC_NAME_WORDS:
            by_gov[r.get("gov")].append(r)
    for gov in sorted(g for g in by_gov if g):
        pool = sorted(by_gov[gov], key=lambda r: r["pid"])
        rnd.shuffle(pool)
        seen, per_kind = set(), defaultdict(int)
        for r in pool:
            q = " ".join(r["_toks"])  # the whole name: a truncated one («مطعم ابو») is no query anyone types
            if q in seen or per_kind[r["scat"]] >= (1 if r["scat"] in RARE_KINDS else 2):
                continue
            seen.add(q)
            per_kind[r["scat"]] += 1
            items.append({"group": "kindname", "q": q, "at": list(offset(rnd, r["lat"], r["lng"], 1000, 3000)), "g": gov,
                          "place": {"names": [r["name_ar"]], "near": [r["lat"], r["lng"]], "r": 300, "scats": [r["scat"]]}})
            if len(seen) >= PER_GOV_KINDNAME:
                break

    # famous — a prominent place whose own name starts with a kind word, typed whole
    fam = defaultdict(list)
    for r in rows:
        if (r.get("pop") or 0) >= 0.85 and kw.get(r["_toks"][0]) and 2 <= len(r["_toks"]) <= 4:
            fam[r.get("gov")].append(r)
    for gov in sorted(g for g in fam if g):
        pool = sorted(fam[gov], key=lambda r: (-r["pop"], r["pid"]))[:30]
        rnd.shuffle(pool)
        for r in pool[:PER_GOV_FAMOUS]:
            items.append({"group": "famous", "q": r["name_ar"], "at": list(offset(rnd, r["lat"], r["lng"], 3000, 8000)), "g": gov,
                          "place": {"names": [r["name_ar"]], "near": [r["lat"], r["lng"]], "r": 400}})

    # examples — the owner's named names that hold a kind word: the nearest real row of that name to its city
    for q, names, city in EXAMPLES:
        cands = [r for r in rows if any(tn.normalize(n) == tn.normalize(r["name_ar"]) for n in names)]
        if not cands:
            continue
        r = min(cands, key=lambda r: dist(r["lat"], r["lng"], city[0], city[1]))
        items.append({"group": "examples", "q": q, "at": list(offset(rnd, r["lat"], r["lng"], 2000, 5000)), "g": r.get("gov"),
                      "place": {"names": names, "near": [r["lat"], r["lng"]], "r": 1500}})

    json.dump({"seed": SEED, "rows": os.path.basename(a.rows), "items": items}, open(a.out, "w", encoding="utf8"),
              ensure_ascii=False, indent=0)
    from collections import Counter
    print("[kindname]", len(items), Counter(i["group"] for i in items), "governorates", len({i["g"] for i in items}))


if __name__ == "__main__":
    main()
