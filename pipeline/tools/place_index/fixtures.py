"""Parity fixtures: what the Kotlin and Swift copies of the engine must reproduce exactly.

    python -m tools.place_index.fixtures --index <dir> [--mini]   # writes tools/place_index/fixtures/

text_cases.json    real names from the index + hand-picked edge cases → normalize / tokens and,
                   per token, stems / skeletons / loose (textnorm.py ⇄ PlaceText.kt ⇄ PlaceText.swift)
mini/              a few hundred kilobytes of downtown Cairo cut from a built index (the national
                   file within 8 km of Tahrir, every place within 650 m) + engine_cases.json: the
                   parse and the top 10 the reference engine returns ON THAT INDEX, replayed by
                   PlaceSearchTest (JVM) and RunnerTests/PlaceSearchTests.swift (Codemagic) — the
                   one check the Swift copy gets that the desk cannot give it
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3

from . import engine as E
from . import textnorm as tn

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
APP = os.path.abspath(os.path.join(HERE, "..", ".."))

EDGE = [
    "", " ", "المُهَنْدِسِين", "صيدليات العزبي - فرع المعادي", "B.TECH بي تك", "شارع9 المعادي", "ڤودافون",
    "Café Supreme", "مستشفى ٥٧٣٥٧", "El-Ezaby Pharmacy", "m3ady", "2al3a", "للسيارات", "بالمعادي", "والدقي",
    "Cairo Festival City Mall كايرو فستيفال", "ÇAĞLAYAN", "STRAẞE", "مـــول", "ﻣﻮﻝ", "ۀ ہ ھ", "۱۲۳ ١٢٣",
    "ميدان «التحرير»", "Mo'men", "McDonald's", "L'Avenue", "Ristorante 6october", "q8", "كشري أبو طارق",
    "El 3azaby", "saydaleyet el ezaby", "khan el 5alily", "gam3et el qahera", "mostashfa", "sh. el tahrir",
    "αβγ Привет", "×÷", "a b\tc\nd", "؟؛،٪", "ﷲ", "abc123", "123abc", "شارع 26 يوليو", "26th of July",
    "Port Tawfik", "بور توفيق", "Dahab", "دهب", "الإسكندرية", "Alexandria", "alex", "elite", "almaza",
]


def text_cases(index_dir: str, n: int = 4000) -> list[dict]:
    names = list(EDGE)
    con = sqlite3.connect(os.path.join(index_dir, "national.sqlite"))
    rows = [r for r in con.execute("SELECT name_ar, name_en, alt FROM place")]
    rnd = random.Random(20261015)
    for r in rnd.sample(rows, min(len(rows), n // 2)):
        for x in r:
            if x:
                names.extend(x.split("\x1f"))
    tiles = [f for f in os.listdir(index_dir) if f.startswith("t") and f.endswith(".sqlite")]
    for f in rnd.sample(tiles, min(6, len(tiles))):
        c = sqlite3.connect(os.path.join(index_dir, f))
        rr = [r for r in c.execute("SELECT name_ar, name_en, addr FROM place")]
        for r in rnd.sample(rr, min(len(rr), n // 12)):
            names.extend(x for x in r if x)
    seen, out = set(), []
    for s in names:
        if s in seen:
            continue
        seen.add(s)
        toks = tn.tokens(s)
        out.append({"in": s, "norm": tn.normalize(s), "script": tn.script_of(tn.normalize(s)),
                    "tok": [{"t": t, "stems": tn.stems(t), "skel": tn.skeletons(t), "loose": tn.loose(t),
                             "edits": tn.max_edits(t), "stop": tn.is_stopword(t)} for t in toks]})
    # edit distances on near pairs
    return out


def damerau_cases() -> list[list]:
    pairs = [("صيدليه", "صيدلبه"), ("pharmcy", "pharmacy"), ("abcd", "acbd"), ("kitten", "sitting"),
             ("مستشفي", "مستشفئ"), ("", "abc"), ("abc", ""), ("ca", "abc"), ("starbucks", "starbuks"),
             ("ماكدونالدز", "ماكدونلدز"), ("zamalek", "zamalk"), ("heliopolis", "heliopolice")]
    out = []
    for a, b in pairs:
        for c in (0, 1, 2, 3):
            out.append([a, b, c, tn.damerau(a, b, c)])
    return out


# ── the mini index: a few hundred kilobytes of downtown Cairo the app tests replay ─────────────
# (android PlaceSearchTest on the JVM, RunnerTests/PlaceSearchTests.swift on Codemagic). Rows are
# copied from a built index as they are — tok rows included — and vocab is recounted over the rows
# kept, which is exactly what tiles.py would have written for those places.
MINI_CENTER = (30.0444, 31.2357)   # Tahrir
MINI_TILE_M = 650.0
MINI_NATIONAL_M = 8000.0
MINI_QUERIES = [
    "مطعم", "صيدلية", "بنزينة", "atm", "كافيه قريب", "مستشفى", "بنك مصر", "العزبي", "سيف", "مترو", "محطة مترو",
    "مترو السادات", "ميدان التحرير", "التحرير", "tahrir", "المتحف المصري", "egyptian museum", "el mat7af el masry",
    "جامعة القاهرة", "القصر العيني", "kasr el aini", "قصر النيل", "كوبري قصر النيل", "شارع طلعت حرب", "talaat harb",
    "ش محمد محمود", "شارع قصر العيني", "جاردن سيتي", "garden city", "الزمالك", "وسط البلد", "downtown", "عابدين",
    "كشري", "كشري التحرير", "koshary tahrir", "فلفلة", "felfela", "قهوة", "ahwa", "فندق", "hotel", "سميراميس",
    "semiramis", "هيلتون", "مول", "مجمع التحرير", "mogamma", "الجامعة الامريكية", "auc", "مسجد عمر مكرم",
    "صيدليه العزبى", "phrmacy", "مستشفي", "بنزينه قريبه", "صراف", "مكتبة", "مكتبة الشروق", "سينما", "metro station",
    "طلعت حرب", "جروبي", "groppi", "cafe riche", "ريش", "فيرمونت", "nile ritz", "ريتز كارلتون", "عمر افندي",
    "باب اللوق", "سوق باب اللوق", "الدقي", "dokki", "المنيل", "manial", "كوبري الجلاء", "الاوبرا", "دار الاوبرا",
    "cairo tower", "برج القاهرة", "ماكدونالدز", "kfc", "كنتاكي", "بيتزا هت", "هارديز", "قسم شرطة", "سجل مدني",
    # the parse rules: open-now words, a landmark that is also a category word, Franco street words, typo'd
    # category words, a station name, a category + area, the restaurant family, an exact name
    "صيدلية فاتحة دلوقتي", "دار الاوبرا", "kobry 6 october", "صيدلبة", "بنزنيه", "محطة مترو السادات",
    "فول وطعمية", "مطعم قريب", "صيدلية في جاردن سيتي", "بنزينة في الزمالك", "شارع قصر النيل وسط البلد",
    "مكتبة الشروق التحرير", "كشري ابو طارق", "قهوة في وسط البلد",
]


def mini(index_dir: str, out_dir: str) -> dict:
    import gzip
    import hashlib
    import shutil
    from . import tiles as TL
    os.makedirs(out_dir, exist_ok=True)
    clat, clng = MINI_CENTER
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    work = os.path.join(out_dir, "_work")
    os.makedirs(work, exist_ok=True)

    def cut(src_paths: list[str], radius: float, dst: str, tile_id: str, with_cats: bool) -> int:
        if os.path.exists(dst):
            os.remove(dst)
        out = sqlite3.connect(dst)
        out.executescript(TL.DDL)
        n = 0
        rows, toks, areas = [], [], {}
        for sp in src_paths:
            con = sqlite3.connect(sp)
            arows = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, ar, en FROM area")}
            new_id = {}
            for r in con.execute("SELECT * FROM place"):
                if E.haversine(clat, clng, r[5], r[6]) > radius:
                    continue
                n += 1
                r = list(r)
                new_id[r[0]] = n
                r[0] = n
                if r[11] is not None:
                    key = arows.get(r[11])
                    r[11] = areas.setdefault(key, len(areas) + 1) if key else None
                rows.append(r)
            for t, old, f in con.execute("SELECT t, id, f FROM tok"):
                if old in new_id:
                    toks.append((t, new_id[old], f))
            if with_cats:
                cats = list(con.execute("SELECT * FROM category"))
                out.executemany("INSERT INTO category VALUES (?,?,?,?)", cats)
            meta = dict(con.execute("SELECT k, v FROM meta"))
            con.close()
        out.executemany("INSERT INTO place VALUES (" + ",".join("?" * 23) + ")", rows)
        out.executemany("INSERT INTO area VALUES (?,?,?)", [(i, k[0], k[1]) for k, i in areas.items()])
        toks.sort()
        out.executemany("INSERT INTO tok VALUES (?,?,?)", toks)
        df: dict = {}
        for t, _, _ in toks:
            df[t] = df.get(t, 0) + 1
        out.executemany("INSERT INTO vocab VALUES (?,?)", sorted(df.items()))
        meta.update({"tile": tile_id, "places": str(n)})
        out.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
        out.executescript(TL.POST)
        out.commit()
        out.execute("VACUUM")
        out.close()
        return n

    near_tiles = [os.path.join(index_dir, t["id"] + ".sqlite") for t in man["tiles"]
                  if t["bbox"][0] <= clng + 0.02 and t["bbox"][2] >= clng - 0.02
                  and t["bbox"][1] <= clat + 0.02 and t["bbox"][3] >= clat - 0.02]
    entries = {}
    for tid, srcs, radius, cats in (("national", [os.path.join(index_dir, "national.sqlite")], MINI_NATIONAL_M, True),
                                    ("t", near_tiles, MINI_TILE_M, False)):
        raw = os.path.join(work, tid + ".sqlite")
        n = cut(srcs, radius, raw, tid, cats)
        with open(raw, "rb") as f:
            gz = gzip.compress(f.read(), compresslevel=9, mtime=0)
        with open(os.path.join(out_dir, tid + ".sqlite.gz"), "wb") as f:
            f.write(gz)
        d = MINI_TILE_M / 111000.0
        bbox = [round(clng - d * 1.2, 5), round(clat - d, 5), round(clng + d * 1.2, 5), round(clat + d, 5)] if tid == "t" \
            else man["national"]["bbox"]
        entries[tid] = {"id": tid, "bbox": bbox, "file": tid + ".sqlite.gz", "bytes": len(gz),
                        "sha256": hashlib.sha256(gz).hexdigest(), "places": n}
    mman = {"schema": man["schema"], "norm": man["norm"], "version": "mini-" + str(man.get("version")),
            "built": man.get("built"), "license": man.get("license"), "national": entries["national"],
            "tiles": [entries["t"]]}
    with open(os.path.join(work, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(mman, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(mman, f, ensure_ascii=False, indent=1)
    # the expectation: the reference engine on the mini index itself
    lx = E.Lexicon.load(os.path.join(APP, "assets", "search", "egypt_lexicon.json"))
    eng = E.Engine(E.Index(work), lx)
    cases = []
    for q in MINI_QUERIES:
        p = eng.parse(q, clat, clng)
        rs = eng.search(q, clat, clng, limit=10)
        cases.append({"q": q, "lat": clat, "lng": clng,
                      "parse": {"kind": p.kind, "scat": p.scat, "brand": p.brand, "scope": p.scope,
                                "area": (p.area or {}).get("name"), "entity": (p.entity or {}).get("id"),
                                "street": p.street, "near": p.near, "residual": p.residual, "open_now": p.open_now},
                      "top": [{"pid": r.pid, "score": r.score, "text": r.text} for r in rs]})
    with open(os.path.join(out_dir, "engine_cases.json"), "w", encoding="utf-8") as f:
        json.dump({"index_version": mman["version"], "cases": cases}, f, ensure_ascii=False, indent=0)
    shutil.rmtree(work)
    return {k: (v["places"], v["bytes"]) for k, v in entries.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--cases", type=int, default=1600, help="sampled names for text_cases.json")
    ap.add_argument("--mini", action="store_true", help="also cut the mini index + its engine_cases.json")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "text_cases.json"), "w", encoding="utf-8") as f:
        json.dump({"norm_version": tn.NORM_VERSION, "cases": text_cases(a.index, a.cases), "damerau": damerau_cases()},
                  f, ensure_ascii=False, separators=(",", ":"))
    if a.mini:
        print("[fixtures] mini", mini(a.index, os.path.join(OUT, "mini")))


if __name__ == "__main__":
    main()
