# -*- coding: utf-8 -*-
"""The Egyptian parity query set (2026-10-25, docs/research/search-parity.md) — the bench's own targets, typed the way
people type them, measured group by group.

    python -m tools.place_index.bench.parity --index <dir> [--out <dir>] [--only prefix,typo1,...]

Every PLACE and CHAIN query of the benchmark (tools/place_index/bench/queries.py — ground truth written from knowledge
of Egypt, never from the data under test) is re-typed deterministically into these groups, judged by the bench's own
judge (run.judge: the right name within the target's radius / the right chain within its reach):

  base      the query as written
  prefix3   its first 3 letters   — autocomplete from the first keystrokes (parity S1)
  prefix4   its first 4 letters
  prefix6   its first 6 letters
  typo1     one edit: a dropped, doubled, swapped or neighbouring-key letter (S22)
  typo2     two edits
  variant   Arabic spelling variants: أ/إ/ا, ة/ه, ى/ي, tatweel, a diacritic, Arabic-Indic digits (S24)
  franco    an Arabic query written in Franco-Arabic (digits for ع ح ق …; S25)
  chain     every chain query: the share of results that are the chain, and whether they come nearest-first (S29)

Prints Hit@1 / Hit@5 / MRR and the latency (p50 / p95, the Python reference engine — the device numbers come from the
JVM bench) per group, and writes summary.json + rows.json to --out.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time

from tools.place_index import engine as E
from tools.place_index.bench import queries as Q
from tools.place_index.bench import run as R

AR = set("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")
ADJ = {  # QWERTY neighbours (Latin typos)
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb",
    "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp", "p": "ol",
    "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy", "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc",
    "y": "tghu", "z": "asx",
}
ADJ_AR = {  # Arabic keyboard neighbours (the standard 101 layout)
    "ض": "صش", "ص": "ضثس", "ث": "صقي", "ق": "ثفب", "ف": "قغل", "غ": "فعا", "ع": "غهت", "ه": "عخن", "خ": "هحم",
    "ح": "خجك", "ج": "حد", "ش": "ضسئ", "س": "شيصء", "ي": "سبث", "ب": "يلق", "ل": "باف", "ا": "لتغ", "ت": "انع",
    "ن": "تمه", "م": "نكخ", "ك": "مطح", "ط": "كج", "ئ": "شء", "ء": "ئؤس", "ؤ": "ءر", "ر": "ؤى", "ى": "رة",
    "ة": "ىو", "و": "ةز", "ز": "وظ", "ظ": "ز", "د": "ج", "ذ": "د",
}
FRANCO = {
    "ا": "a", "أ": "a", "إ": "e", "آ": "a", "ب": "b", "ت": "t", "ث": "s", "ج": "g", "ح": "7", "خ": "5", "د": "d",
    "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "3", "غ": "gh",
    "ف": "f", "ق": "2", "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "ة": "a", "و": "o", "ي": "i", "ى": "a",
    "ء": "2", "ئ": "2", "ؤ": "2", " ": " ",
}
INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def is_ar(s):
    return any(c in AR for c in s)


def letters(s):
    return [i for i, c in enumerate(s) if c.isalpha() or c in AR]


def edit(s, rnd):
    """One plausible typing slip somewhere inside a word (never the first letter — people get that one right)."""
    idx = [i for i in letters(s) if i > 0 and s[i - 1] != " "]
    if not idx:
        return s
    i = rnd.choice(idx)
    kind = rnd.choice(("drop", "double", "swap", "near"))
    if kind == "drop":
        return s[:i] + s[i + 1:]
    if kind == "double":
        return s[:i] + s[i] + s[i:]
    if kind == "swap" and i + 1 < len(s) and s[i + 1] != " ":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    near = (ADJ_AR if is_ar(s[i]) else ADJ).get(s[i].lower())
    if near:
        return s[:i] + rnd.choice(near) + s[i + 1:]
    return s[:i] + s[i + 1:]


def variant(s, rnd):
    """The same Arabic words in another spelling people use (a normaliser must make them one)."""
    out = []
    for w in s.split(" "):
        if w.startswith("ا") and len(w) > 2:
            w = rnd.choice("أإ") + w[1:]
        if w.endswith("ة"):
            w = w[:-1] + "ه"
        elif w.endswith("ه") and len(w) > 2:
            w = w[:-1] + "ة"
        if w.endswith("ي"):
            w = w[:-1] + "ى"
        elif w.endswith("ى"):
            w = w[:-1] + "ي"
        if len(w) > 4 and rnd.random() < 0.5:
            k = len(w) // 2
            w = w[:k] + "ـ" + w[k:]
        out.append(w)
    t = " ".join(out)
    if len(t) > 3 and rnd.random() < 0.5:
        k = len(t) // 3
        if t[k] in AR:
            t = t[:k + 1] + "َ" + t[k + 1:]
    return t.translate(INDIC)


def franco(s):
    t = s.replace("ال", "el ") if s.startswith("ال") else s.replace(" ال", " el ")
    return "".join(FRANCO.get(c, c) for c in t).replace("  ", " ").strip()


def derive(q, gi):
    """The re-typed forms of one bench query: [(group, text)]."""
    rnd = random.Random(1000003 * gi + 17)
    t = q["q"]
    out = [("base", t)]
    if "cat" in q:
        return out
    compact = t.replace(" ", "")
    for n in (3, 4, 6):
        if len(compact) > n + 1:
            out.append(("prefix%d" % n, t[:n].strip()))
    if len(compact) >= 5:
        out.append(("typo1", edit(t, rnd)))
        out.append(("typo2", edit(edit(t, rnd), rnd)))
    if is_ar(t):
        out.append(("variant", variant(t, rnd)))
        out.append(("franco", franco(t)))
    return out


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", default="G:/grad_all/.p5work/search_parity")
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    lx = E.Lexicon.load(R.LEXICON)
    eng = E.Engine(E.Index(a.index), lx)
    only = set(a.only.split(",")) if a.only else None
    # Checkpointed: every judged row is appended to rows.jsonl at once, and a rerun skips what is already there (the
    # desk can starve a long run; nothing judged is lost).
    os.makedirs(a.out, exist_ok=True)
    ck = os.path.join(a.out, "rows.jsonl")
    rows, done = [], set()
    if os.path.exists(ck):
        for ln in open(ck, encoding="utf-8"):
            if ln.strip():
                r = json.loads(ln)
                rows.append(r)
                done.add((r["gi"], r["group"]))
    out_ck = open(ck, "a", encoding="utf-8")
    for gi, q in enumerate(Q.Q):
        lat, lng, _ = Q.ANCHORS[q["at"]]
        for grp, text in derive(q, gi):
            if only and grp not in only:
                continue
            if not text.strip() or (gi, grp) in done:
                continue
            t0 = time.time()
            rs = eng.search(text, lat, lng, limit=10, route=Q.ROUTES.get(q.get("route")) if q.get("route") else None,
                            dest=q.get("dest"))
            ms = (time.time() - t0) * 1000.0
            j = R.judge(q, rs, (lat, lng))
            row = {"gi": gi, "group": grp, "q": text, "orig": q["q"], "type": "place" if "place" in q else "cat" if "cat" in q
                   else "brand", "style": q["s"], "rank": j["rank"], "ms": round(ms, 1)}
            if "brand" in q:
                row["chain_share"] = sum(1 for x in j["ok"] if x) / max(1, len(j["ok"]))
                ds = [r.dist for r, ok in zip(rs[:5], j["ok"]) if ok]
                row["nearest_first"] = all(ds[k] <= ds[k + 1] + 1.0 for k in range(len(ds) - 1)) if len(ds) > 1 else True
            rows.append(row)
            out_ck.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_ck.flush()
        if gi % 50 == 0:
            print("[parity] %d/%d" % (gi, len(Q.Q)), flush=True)
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
        if r["type"] == "brand":
            groups.setdefault("chain", []).append(r)
    summary = {}
    for g, rs in groups.items():
        n = len(rs)
        ranks = [r["rank"] for r in rs]
        ms = sorted(r["ms"] for r in rs)
        s = {"n": n, "hit1": round(sum(1 for k in ranks if k == 1) / n, 3),
             "hit5": round(sum(1 for k in ranks if k and k <= 5) / n, 3),
             "mrr": round(sum(1.0 / k for k in ranks if k) / n, 3),
             "p50_ms": round(statistics.median(ms), 1), "p95_ms": round(ms[min(n - 1, int(0.95 * n))], 1)}
        if g == "chain":
            s["chain_share"] = round(sum(r["chain_share"] for r in rs) / n, 3)
            s["nearest_first"] = round(sum(1 for r in rs if r["nearest_first"]) / n, 3)
        summary[g] = s
    order = ["base", "prefix3", "prefix4", "prefix6", "typo1", "typo2", "variant", "franco", "chain"]
    print("\n%-9s %5s %6s %6s %6s %8s %8s" % ("group", "n", "Hit@1", "Hit@5", "MRR", "p50 ms", "p95 ms"))
    for g in order:
        if g in summary:
            s = summary[g]
            extra = ("  chain share %.2f, nearest-first %.2f" % (s["chain_share"], s["nearest_first"])) if g == "chain" else ""
            print("%-9s %5d %6.3f %6.3f %6.3f %8.1f %8.1f%s" % (g, s["n"], s["hit1"], s["hit5"], s["mrr"], s["p50_ms"],
                                                              s["p95_ms"], extra))
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(rows, open(os.path.join(a.out, "rows.json"), "w", encoding="utf-8"), ensure_ascii=False)
    misses = [r for r in rows if not r["rank"] or r["rank"] > 5]
    print("\nmisses (rank > 5): %d — e.g." % len(misses))
    for r in misses[:30]:
        print("  %-8s %-28s ← %s" % (r["group"], r["q"][:28], r["orig"][:28]))


if __name__ == "__main__":
    main()
