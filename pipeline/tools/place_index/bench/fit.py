"""Fit the engine's score weights against the benchmarks — never by hand on single queries.

    python -m tools.place_index.bench.fit collect --index <dir> --out <cache.json> [--jobs 3]
    python -m tools.place_index.bench.fit fit --cache <cache.json> [--report <file>]

collect  runs every query of the 346-query benchmark (queries.py) and of the intelligence benchmark (intel_queries.py:
         prefix at 2 / 3 / 4 / 6 letters and the full text, exact, variant, need) ONCE through the engine as the phone
         runs it, keeps each query's top 40 with the parts of its score (text, proximity, popularity, confidence,
         category, match class) and the benchmark's own verdict on each.
fit      re-scores the cached candidates under other weight vectors for the name, category + name and need profiles
         (score = what the engine scored − its weighted parts under TUNING + the same parts under the candidate weights:
         every other term — match class, chain strength, street boosts — is kept as the engine computed it), re-ranks,
         and reports one objective: the mean of the 346's MRR, the exact suite's Hit@1, the variant suite's MRR, the
         prefix suite's MRR over all typed lengths and the need suite's P@5. A coordinate search from TUNING; the
         winner is reported with every metric so a gain on one cannot hide a loss on another.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import os

from .. import engine as E
from . import intel as IN
from . import intel_queries as IQ
from . import queries as Q
from . import run as RUN

TOPK = 40
PROFILES = ("w_name", "w_cat_name", "w_need")


def _items() -> list[tuple]:
    out = []
    for i, q in enumerate(Q.Q):
        out.append(("b346", i, q))
    for i, it in enumerate(IQ.PREFIX):
        text = it["q"]
        lens = sorted({n for n in (2, 3, 4, 6) if n < len(text)} | {len(text)})
        for L in lens:
            pre = text[:L].rstrip()
            if pre:
                out.append(("prefix", i, dict(it, q=pre, L=L)))
    for suite in ("exact", "variant", "need"):
        for i, it in enumerate(IQ.SUITES[suite]):
            out.append((suite, i, it))
    return out


def _cands(rs, oks) -> list[dict]:
    out = []
    for k, r in enumerate(rs):
        p = r.parts
        out.append({"s": r.score, "kind": p.get("kind"), "rk": r.kind, "t": p.get("text", 0.0), "x": p.get("prox", 0.0),
                    "p": p.get("pop", 0.0), "c": p.get("conf", 0.0), "m": p.get("cat", 0.0), "tier": p.get("tier", 0),
                    "d": r.dist, "pid": r.pid, "ok": bool(oks[k]) if k < len(oks) else False})
    return out


def _collect_one(task):
    suite, i, it = task
    eng = IN._W["eng"]
    if suite == "b346":
        lat, lng = Q.ANCHORS[it["at"]][:2] if isinstance(it["at"], str) else it["at"]
        route = Q.ROUTES.get(it.get("route")) if it.get("route") else None
        rs = eng.search(it["q"], lat, lng, limit=TOPK, route=route, dest=it.get("dest"), explain=True)
        oks = RUN.judge(it, rs, (lat, lng))["ok"]
    else:
        lat, lng = IQ.anchor(it["at"])
        extra = []
        if IN._W["router"] is not None:
            p = eng.parse(it["q"], lat, lng)
            words = IN.RT.query_words(p)
            if words:
                alat, alng = (p.area["lat"], p.area["lng"]) if p.area and not p.area.get("road") else (lat, lng)
                extra = [t for t, _ in IN._W["router"].route_tiles(words, alat, alng)][:IN.RT.ROUTE_OPEN_MAX]
        rs = eng.search(it["q"], lat, lng, limit=TOPK, extra=extra, explain=True)
        # every candidate judged (intel.judge stops its verdict list at 5)
        oks = []
        for r in rs:
            oks.append(IN.judge(it, [r], lat, lng)["rank"] == 1)
    return {"suite": suite, "i": i, "q": it["q"], "L": it.get("L"), "c": _cands(rs, oks)}


def collect(index: str, out: str, jobs: int) -> None:
    items = _items()
    print(f"[fit] {len(items)} queries", flush=True)
    with mp.Pool(jobs, initializer=IN._init, initargs=(index,)) as pool:
        rows = []
        for k, row in enumerate(pool.imap(_collect_one, items, chunksize=2)):
            rows.append(row)
            if k % 50 == 0:
                print(f"[fit] {k}/{len(items)}", flush=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"tuning": {k: (list(v) if isinstance(v, tuple) else v) for k, v in E.TUNING.items()}, "rows": rows},
                  f, ensure_ascii=False)


def _lin(c: dict, w) -> float:
    return w[0] * c["t"] + w[1] * c["x"] + w[2] * c["p"] + w[3] * c["c"] + w[4] * c["m"]


def _profile(c: dict) -> str | None:
    if c["kind"] == "name" and c["rk"] == 0:
        return "w_name"
    if c["kind"] == "cat_name":
        return "w_cat_name"
    return None  # category / brand / area / street rows keep the engine's own score


def evaluate(rows: list[dict], base: dict, cand: dict) -> dict:
    per: dict = {}
    for row in rows:
        cs = []
        need = row["suite"] == "need"
        for c in row["c"]:
            prof = _profile(c)
            if need and c["kind"] == "category":
                prof = "w_need"
            s = c["s"]
            if prof is not None:
                s = s - _lin(c, base[prof]) + _lin(c, cand[prof])
            cs.append((-s, c["d"], c["pid"], c["ok"]))
        cs.sort()
        oks = [x[3] for x in cs]
        rank = oks.index(True) + 1 if True in oks else None
        per.setdefault(row["suite"], []).append((rank, sum(oks[:5]) / 5.0))
    m = {}
    for suite, xs in per.items():
        m[suite] = {"hit1": sum(1 for r, _ in xs if r == 1) / len(xs), "mrr": sum(1.0 / r for r, _ in xs if r) / len(xs),
                    "hit5": sum(1 for r, _ in xs if r and r <= 5) / len(xs),
                    "p5": sum(p for _, p in xs) / len(xs), "n": len(xs)}
    obj = [m["b346"]["mrr"], m["exact"]["hit1"], m["variant"]["mrr"], m["prefix"]["mrr"], m["need"]["p5"]]
    m["objective"] = sum(obj) / len(obj)
    return m


# The 346-query benchmark may not regress: the published engine's own numbers (docs/place-search-2026-10.md §11c,
# places-2026-10-31, measured 2026-11-01 with bench/run.py) are a floor every candidate must keep.
FLOOR_346 = {"hit1": 0.916, "hit5": 0.983, "mrr": 0.943}


def _allowed(m: dict) -> bool:
    return all(m["b346"][k] >= v - 1e-9 for k, v in FLOOR_346.items())


def fit(cache: str, report: str | None) -> None:
    d = json.load(open(cache, encoding="utf-8"))
    base = {k: tuple(d["tuning"][k]) for k in PROFILES}
    rows = d["rows"]
    best = dict(base)
    best_m = evaluate(rows, base, best)
    print("[fit] TUNING", json.dumps({k: round(v["mrr"], 4) if isinstance(v, dict) else round(v, 4)
                                      for k, v in best_m.items()}), flush=True)
    steps = (0.06, 0.03)
    for step in steps:
        improved = True
        while improved:
            improved = False
            for prof in PROFILES:
                for a, b in itertools.permutations(range(5), 2):
                    w = list(best[prof])
                    if w[b] < step:
                        continue
                    w[a] = round(w[a] + step, 4)
                    w[b] = round(w[b] - step, 4)
                    cand = dict(best)
                    cand[prof] = tuple(w)
                    m = evaluate(rows, base, cand)
                    if m["objective"] > best_m["objective"] + 1e-4 and _allowed(m):
                        best, best_m, improved = cand, m, True
    out = {"start": {k: list(v) for k, v in base.items()}, "start_metrics": evaluate(rows, base, base),
           "best": {k: list(v) for k, v in best.items()}, "best_metrics": best_m}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if report:
        with open(report, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--index", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--jobs", type=int, default=3)
    f = sub.add_parser("fit")
    f.add_argument("--cache", required=True)
    f.add_argument("--report")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        collect(a.index, a.out, a.jobs)
    else:
        fit(a.cache, a.report)


if __name__ == "__main__":
    main()
