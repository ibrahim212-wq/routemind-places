"""The important-place checklist: what must exist by how Egypt is governed, not what a list happens to name.

Every markaz / qism has a police station, every markaz town a hospital, a post office, a court and a city council; every
governorate a governorate building, a security directorate, a health and an education directorate, a general hospital
and a court. The checklist is generated from the districts (assets/atlas/world.json: 'parents' + 'governorates'), so it
has no opinion about which places we happen to hold. Two numbers per template and governorate:

  exists  a row of the right kind carrying the district's name stands within reach of it (``NEAR_M``, ``GOV_M`` for a governorate)
  found   typing the query there puts such a row in the top 3 (top 1 reported beside it)

The truth is structural: a few templates will not apply to every district (a desert qism has no court). Those show as
misses, so this measure errs low. No provider is asked anything.

usage: python -m tools.place_index.bench.checklist --index <idx> --rows <rows.jsonl> --out <dir> [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re

from .. import engine as E
from .run import LEXICON

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WORLD = os.path.join(ROOT, "assets", "atlas", "world.json")
NEAR_M = 60000  # a markaz's centroid can be far from its town (Nuweiba, Marsa Alam); the name has to be carried anyway
GOV_M = 250000
KIND_NEAR_M = 8000  # «البريد المصري» 700 m from the town's centre IS that town's post office, whatever its name leaves out
CITY_GOVS = {"C", "ALX", "PTS", "SUZ"}  # governorates of qisms only: no markaz town, no city council of its own
DROP_WORDS = ("صحراء", "desert", "باقي", "الحدود")
SEAT_WORDS = ("مركز", "قسم", "مدينة", "ثان", "اول", "أول", "ثالث", "رابع", "خامس",
              "markaz", "qism", "kism", "city", "1", "2", "3", "first", "second", "third")

# id, the query, the kinds that are enough on their own, and words any one of which is enough on its own
DISTRICT = [
    ("police", "قسم شرطة {n}", {"police"}, ("شرطه", "police")),
]
TOWN = [
    ("hospital", "مستشفى {n}", {"hospital"}, ("مستشفي", "hospital")),
    ("post", "مكتب بريد {n}", {"post_office"}, ("بريد", "post")),
    ("court", "محكمة {n}", {"courthouse"}, ("محكمه", "محاكم", "court")),
    ("council", "مجلس مدينة {n}", set(), ("مجلس", "council", "محليه", "ومدينه")),
]
GOVERNORATE = [
    ("gov_building", "ديوان عام محافظة {n}", set(), ("ديوان", "governorate")),
    ("security", "مديرية امن {n}", set(), ("امن", "security")),
    ("health_dir", "مديرية الصحة {n}", set(), ("صحه", "صحيه", "health")),
    ("edu_dir", "مديرية التربية والتعليم {n}", set(), ("تربيه", "تعليم", "education")),
    ("gen_hospital", "مستشفى {n} العام", {"hospital"}, ("مستشفي", "hospital")),
    ("court_gov", "محكمة {n} الابتدائية", {"courthouse"}, ("محكمه", "محاكم", "court")),
]


def norm(s: str | None) -> list[str]:
    s = (s or "").lower()
    s = re.sub(r"[ً-ْـ]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    return re.findall(r"[a-z0-9ء-ي]+", s)


def key(w: str) -> str:
    for lead in ("بال", "لل", "ال"):  # «بالجيزة», «الجيزة», «جيزة» are one word here
        if w.startswith(lead) and len(w) > len(lead) + 2:
            return w[len(lead):]
    return w


def seat_name(ar: str) -> str:
    """«مركز منفلوط» → «منفلوط», «قسم الجمرك» → «الجمرك», «دمنهور ثان» → «دمنهور»."""
    words = [w for w in ar.split() if w.lower() not in SEAT_WORDS]
    return " ".join(words) or ar


def dist_m(a: float, b: float, c: float, d: float) -> float:
    x = math.radians(d - b) * math.cos(math.radians((a + c) / 2))
    y = math.radians(c - a)
    return 6371000 * math.hypot(x, y)


def carries(row_words: set[str], name: str) -> bool:
    want = {key(w) for w in norm(name)}
    return bool(want) and want <= {key(w) for w in row_words}


def entries(world: dict) -> list[dict]:
    points = collections.defaultdict(list)
    for d in world["districts"]:
        points[d["parent"]].append(d["label"])
    out = []
    parents = world["parents"]
    for pid, p in sorted(parents.items()):
        name = seat_name(p["ar"])
        if not name or any(w in p["ar"].lower() or w in p["en"].lower() for w in DROP_WORDS) or not points[pid]:
            continue
        pts = points[pid]
        lat = sum(x[0] for x in pts) / len(pts)
        lng = sum(x[1] for x in pts) / len(pts)
        for tid, q, kinds, words in DISTRICT + ([] if p["g"] in CITY_GOVS else TOWN):
            out.append({"t": tid, "level": "district", "g": p["g"], "id": pid, "n": name, "en": seat_name(p["en"]),
                        "seats": pts, "q": q.format(n=name),
                        "lat": lat, "lng": lng, "kinds": kinds, "words": words, "m": NEAR_M})
    for g in world["governorates"]:
        # where its people are, not the middle of its desert: the mean of its districts
        pts = [d["label"] for d in world["districts"] if parents.get(d["parent"], {}).get("g") == g["id"]] or [g["label"]]
        lat = sum(x[0] for x in pts) / len(pts)
        lng = sum(x[1] for x in pts) / len(pts)
        for tid, q, kinds, words in GOVERNORATE:
            out.append({"t": tid, "level": "gov", "g": g["id"], "id": g["id"], "n": g["ar"], "en": g.get("en") or "",
                        "seats": [], "q": q.format(n=g["ar"]),
                        "lat": lat, "lng": lng, "kinds": kinds, "words": words, "m": GOV_M})
    return out


def row_ok(e: dict, scat: str | None, words: set[str]) -> bool:
    return scat in e["kinds"] or bool({key(w) for w in words} & {key(w) for w in e["words"]})


def right(e: dict, lat: float, lng: float, scat: str | None, words: set[str]) -> bool:
    """The right kind of place: carrying the town's name within reach, or standing in the town whatever its name says."""
    if not row_ok(e, scat, words):
        return False
    if (carries(words, e["n"]) or carries(words, e["en"])) and dist_m(e["lat"], e["lng"], lat, lng) <= e["m"]:
        return True
    return any(dist_m(x[0], x[1], lat, lng) <= KIND_NEAR_M for x in e["seats"])


def load_rows(path: str, kinds: set[str], tmpl_words: set[str]) -> list[tuple]:
    want = {key(w) for w in tmpl_words}
    rows = []
    for line in open(path, encoding="utf8"):
        r = json.loads(line)
        if r.get("kind") != 0:
            continue
        words = set(norm(r.get("name_ar"))) | set(norm(r.get("name_en"))) | set(norm(" ".join(r.get("alt") or [])))
        if r.get("scat") in kinds or {key(w) for w in words} & want:
            rows.append((r["lat"], r["lng"], r.get("scat"), frozenset(words)))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--exists-only", action="store_true", help="only what the rows hold: no engine, seconds not an hour")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    world = json.load(open(WORLD, encoding="utf8"))
    items = entries(world)
    if a.limit:
        items = items[:: max(1, len(items) // a.limit)]
    kinds = {k for e in items for k in e["kinds"]}
    tmpl_words = {w for e in items for w in e["words"]}
    rows = load_rows(a.rows, kinds, tmpl_words)
    print("rows of these kinds", len(rows), "checks", len(items))
    grid = collections.defaultdict(list)
    for r in rows:
        grid[(int(r[0] * 2), int(r[1] * 2))].append(r)
    eng = None if a.exists_only else E.Engine(E.Index(a.index), E.Lexicon.load(LEXICON))
    res = []
    for e in items:
        cx, cy = int(e["lat"] * 2), int(e["lng"] * 2)
        exists = False
        reach = int(e["m"] / 55000) + 1
        for i in range(cx - reach, cx + reach + 1):
            for j in range(cy - reach, cy + reach + 1):
                for r in grid.get((i, j), ()):
                    if not exists and right(e, r[0], r[1], r[2], set(r[3])):
                        exists = True
        rs = eng.search(e["q"], e["lat"], e["lng"], limit=5) if eng else []
        rank = None
        for i, x in enumerate(rs[:5]):
            w = set(norm(x.name_ar)) | set(norm(x.name_en))
            if right(e, x.lat, x.lng, x.scat, w):
                rank = i + 1
                break
        res.append({"t": e["t"], "level": e["level"], "g": e["g"], "id": e["id"], "n": e["n"], "q": e["q"],
                    "exists": exists, "rank": rank,
                    "top": [(x.name_ar or x.name_en, x.scat, round(x.dist)) for x in rs[:3]]})
    json.dump(res, open(os.path.join(a.out, "checklist.json"), "w", encoding="utf8"), ensure_ascii=False, indent=0)

    def line(label: str, rs: list[dict]) -> str:
        n = len(rs) or 1
        return (f"{label:14} n={len(rs):4} exists={sum(r['exists'] for r in rs) / n:.3f} "
                f"top1={sum(r['rank'] == 1 for r in rs) / n:.3f} top3={sum((r['rank'] or 9) <= 3 for r in rs) / n:.3f}")
    print(line("ALL", res))
    for t in sorted({r["t"] for r in res}):
        print(line(t, [r for r in res if r["t"] == t]))
    print("-- by governorate")
    for g in sorted({r["g"] for r in res}):
        print(line(g, [r for r in res if r["g"] == g]))


if __name__ == "__main__":
    main()
