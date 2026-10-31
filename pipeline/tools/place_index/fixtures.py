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
    # a landmark instead of an address (engine.py `relative_split`, 2026-10-31) and a place's own area
    "صيدلية جنب ميدان التحرير", "pharmacy near tahrir square", "كشري جنب المتحف المصري",
    "atm next to egyptian museum", "قهوة قريب من مجمع التحرير", "مطعم وسط البلد",
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
    mini_cases(work, out_dir, mman["version"])
    shutil.rmtree(work)
    return {k: (v["places"], v["bytes"]) for k, v in entries.items()}


def restate_mini(out_dir: str) -> int:
    """The expectation re-stated on the COMMITTED mini index (an engine change; the index stays as cut)."""
    import gzip
    import shutil
    work = os.path.join(out_dir, "_work")
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        mman = json.load(f)
    for t in [mman["national"]] + mman["tiles"]:
        with open(os.path.join(out_dir, t["file"]), "rb") as f:
            raw = gzip.decompress(f.read())
        with open(os.path.join(work, t["id"] + ".sqlite"), "wb") as f:
            f.write(raw)
    with open(os.path.join(work, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(mman, f, ensure_ascii=False, indent=1)
    n = mini_cases(work, out_dir, mman["version"])
    shutil.rmtree(work)
    return n


def mini_cases(work: str, out_dir: str, version: str) -> int:
    """The expectation: the reference engine on the mini index itself."""
    clat, clng = MINI_CENTER
    lx = E.Lexicon.load(os.path.join(APP, "assets", "search", "egypt_lexicon.json"))
    ix = E.Index(work)
    eng = E.Engine(ix, lx)
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
        json.dump({"index_version": version, "cases": cases}, f, ensure_ascii=False, indent=0)
    for con in ix.cons.values():
        con.close()
    return len(cases)


# ── the name router: a synthetic router (router.py) the app tests parse and query ───────────────

ROUTER_NAMES = [  # (tiles, names): realistic names through the same tokenizer the tiles use
    ([0], ["كشري أبو طارق", "Koshary Abou Tarek"]),
    ([1], ["مطعم زفير", "Zephyr Restaurant"]),
    ([2, 3], ["صيدلية الحكمة", "El Hekma Pharmacy"]),
    (list(range(4, 14)), ["فول الجحش"]),             # 10 tiles: not distinctive → only the near ones fetch
    ([5, 9], ["حلواني العبد"]),
    ([7], ["مخبز الإيمان", "ma5baz el iman"]),
    (list(range(0, 30)), ["مطعم المدينة", "شارع الجمهورية"]),  # in every tile: common, routes nothing
]
ROUTER_QUERIES = [  # (words as the engine's parse leaves them, anchor)
    (["كشري", "ابو", "طارق"], 30.05, 31.24), (["زفير"], 31.2, 29.9), (["zephyr"], 30.05, 31.24),
    (["الحكمه"], 27.2, 31.2), (["فول", "الجحش"], 30.05, 31.24), (["الجحش"], 24.1, 32.9),
    (["حلواني", "العبد"], 30.05, 31.24), (["العبد"], 30.05, 31.24), (["مطعم"], 30.05, 31.24),
    (["مطعم", "زفير"], 30.05, 31.24), (["ايمان"], 29.0, 31.1), (["ma5baz"], 30.05, 31.24),
    (["زفير", "الحكمه"], 30.05, 31.24), (["غير", "موجود", "اصلا"], 30.05, 31.24), ([], 30.05, 31.24),
]


def router_fixture() -> dict:
    """30 tiles on a grid over Egypt holding the tokens of ROUTER_NAMES; the reference's answers."""
    import base64
    import gzip
    from . import router as RT
    from . import tiles as TL
    toks: list[dict] = [dict() for _ in range(30)]
    for tiles_of, names in ROUTER_NAMES:
        for i in tiles_of:
            for nm in names:
                TL.text_tokens(nm, TL.F_NAME, toks[i])
    entries = []
    for i in range(30):
        x0, y0 = 25.0 + (i % 6) * 2.0, 22.0 + (i // 6) * 1.9
        entries.append((f"t{i:02d}", [x0, y0, x0 + 2.0, y0 + 1.9], sorted(toks[i])))
    data, _stats = RT.encode_router(entries, "fixture-router-1", max_tiles=24)  # 30 tiles: «مطعم» stays common
    gz = gzip.compress(data, compresslevel=9, mtime=0)
    r = RT.Router(data=gz)
    cases = []
    for words, lat, lng in ROUTER_QUERIES:
        routed = r.route_tiles(words, lat, lng)
        have = {t for t, _ in routed[:1]}
        cases.append({
            "words": words, "lat": lat, "lng": lng,
            "word_tiles": [r.word_tiles(w) for w in words],
            "routed": [[t, round(d, 6)] for t, d in routed],
            "have": sorted(have),
            "plan_metered": list(RT.plan(routed, have, True)),
            "plan_wifi": list(RT.plan(routed, have, False)),
        })
    fnv = [[t, format(RT.fnv1a64(t), "016x"), format(RT.fmix64(RT.fnv1a64(t)), "016x")]
           for t in ("", "a", "كشري", "~كشر", "zephyr", "مطعم", "الحكمه")]
    return {"version": "fixture-router-1", "file_b64": base64.b64encode(gz).decode("ascii"), "cases": cases, "fnv": fnv}


def write_router_fixture() -> None:
    """Re-state only the router part of text_cases.json (the text cases stay as they are)."""
    p = os.path.join(OUT, "text_cases.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d["router"] = router_fixture()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index")
    ap.add_argument("--cases", type=int, default=1600, help="sampled names for text_cases.json")
    ap.add_argument("--mini", action="store_true", help="also cut the mini index + its engine_cases.json")
    ap.add_argument("--router-only", action="store_true", help="re-state only the router fixture")
    ap.add_argument("--restate-mini", action="store_true",
                    help="re-state only engine_cases.json on the committed mini index (an engine change)")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    if a.router_only:
        write_router_fixture()
        print("[fixtures] router", len(router_fixture()["cases"]), "cases")
        return
    if a.restate_mini:
        print("[fixtures] mini cases", restate_mini(os.path.join(OUT, "mini")))
        return
    if not a.index:
        ap.error("--index is required")
    with open(os.path.join(OUT, "text_cases.json"), "w", encoding="utf-8") as f:
        json.dump({"norm_version": tn.NORM_VERSION, "cases": text_cases(a.index, a.cases), "damerau": damerau_cases(),
                   "router": router_fixture()}, f, ensure_ascii=False, separators=(",", ":"))
    if a.mini:
        print("[fixtures] mini", mini(a.index, os.path.join(OUT, "mini")))


if __name__ == "__main__":
    main()
