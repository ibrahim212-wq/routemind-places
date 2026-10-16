"""Run the benchmark over one or more indexes and judge every answer.

    python -m tools.place_index.bench.run --index merged=<dir> --index osm=<dir> --index overture=<dir>
        [--oracle merged] [--out <dir>] [--html <file>]

For each query and each index: the engine's top 10, judged against queries.py.
  place / area / landmark …   rank of the first result that names the target within its radius
                              → Hit@1, Hit@3, Hit@5, MRR
  category                    each of the top 5: right search category, inside the query's km
                              → Hit@1 (the first is right), P@5, and the first result's distance
                              against the ORACLE (the nearest right place any index knows)
  chain                       each of the top 5: a branch of the chain (by name), inside km
                              → Hit@1, P@5, oracle distance the same way
Writes results.json (everything) and summary.json (the tables); --html renders the review sheet.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict

from .. import engine as E
from .. import textnorm as tn
from . import queries as Q

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LEXICON = os.path.join(APP, "assets", "search", "egypt_lexicon.json")


def name_keys(text: str) -> set[str]:
    out = set()
    for t in tn.tokens(text):
        if tn.is_stopword(t):
            continue
        out.add(tn.stems(t)[-1])
        out.add(tn.loose(t))
    return out


def names_match(expected: list[str], row: dict) -> bool:
    cand = " ".join(x for x in (row.get("name_ar"), row.get("name_en"), (row.get("alt") or "").replace("\x1f", " ")) if x)
    ck = name_keys(cand)
    cand_join = tn.normalize(cand).replace(" ", "")
    for e in expected:
        ek = {tn.stems(t)[-1] for t in tn.tokens(e) if not tn.is_stopword(t)}
        if not ek:
            continue
        if all(k in ck or tn.loose(k) in ck for k in ek):
            return True
        if len(tn.normalize(e).replace(" ", "")) >= 4 and tn.normalize(e).replace(" ", "") in cand_join:
            return True
    return False


def route_dist(route, lat, lng):
    best = float("inf")
    for (a, b), (c, d) in zip(route, route[1:]):
        for k in range(11):
            t = k / 10
            best = min(best, E.haversine(lat, lng, a + (c - a) * t, b + (d - b) * t))
    return best


def judge(q: dict, results: list[E.Result], anchor) -> dict:
    lat, lng = anchor
    out = {"rank": None, "ok": []}
    if "place" in q:
        t = q["place"]
        for i, r in enumerate(results):
            named = names_match(t["names"], r.row)
            d = E.haversine(r.lat, r.lng, *t["near"])
            ok = named and d <= t["r"]
            out["ok"].append(ok)
            if ok and out["rank"] is None:
                out["rank"] = i + 1
            if named and not ok and "named_far_m" not in out:
                out["named_far_m"] = round(d)  # the right name, outside the target radius
        return out
    if "cat" in q:
        t = q["cat"]
        for r in results[:5]:
            if q.get("route"):
                d = route_dist(Q.ROUTES[q["route"]], r.lat, r.lng)
            elif q.get("dest"):
                d = E.haversine(r.lat, r.lng, *q["dest"])
            elif q.get("center"):  # «صيدلية في المعادي»: inside the named area, wherever the user is
                d = E.haversine(r.lat, r.lng, *q["center"])
            else:
                d = E.haversine(r.lat, r.lng, lat, lng)
            out["ok"].append((r.scat == t["scat"] or r.scat in E.SCAT_FAMILY.get(t["scat"], ())) and d <= t["km"] * 1000)
    if "brand" in q:
        t = q["brand"]
        for r in results[:5]:
            d = E.haversine(r.lat, r.lng, lat, lng)
            out["ok"].append(names_match(t["names"], r.row) and d <= t["km"] * 1000)
    out["rank"] = (out["ok"].index(True) + 1) if True in out["ok"] else None
    return out


def oracle(q: dict, ix: E.Index, anchor) -> float | None:
    """Distance to the nearest place that would satisfy a category / chain query, in that index."""
    lat, lng = anchor
    best = None
    if "cat" in q:
        km = q["cat"]["km"]
        pts = Q.ROUTES[q["route"]] if q.get("route") else [q["dest"]] if q.get("dest") else \
            [q["center"]] if q.get("center") else [(lat, lng)]
        for db in {d for p in pts for d in ix.near(p[0], p[1], km * 1000)}:
            fam = E.SCAT_FAMILY.get(q["cat"]["scat"], (q["cat"]["scat"],))
            for r in ix.cons[db].execute(f"SELECT lat, lng FROM place WHERE scat IN ({','.join('?' * len(fam))})", fam):
                d = (route_dist(pts, r[0], r[1]) if q.get("route") else E.haversine(r[0], r[1], *pts[0]))
                if d <= km * 1000 and (best is None or d < best):
                    best = d
    if "brand" in q:
        km = q["brand"]["km"]
        # candidates through the index's own tokens (every stem of every expected name word),
        # then the judge's name rule
        terms = {s for nm in q["brand"]["names"] for t in tn.tokens(nm) if not tn.is_stopword(t) for s in tn.stems(t)}
        for db in ix.near(lat, lng, km * 1000):
            con = ix.cons[db]
            ids = set()
            for t in terms:
                ids.update(r[0] for r in con.execute("SELECT id FROM tok WHERE t = ?", (t,)))
            for i in ids:
                r = con.execute("SELECT lat, lng, name_ar, name_en, alt FROM place WHERE id = ?", (i,)).fetchone()
                d = E.haversine(r[0], r[1], lat, lng)
                if d <= km * 1000 and (best is None or d < best) and names_match(q["brand"]["names"], dict(r)):
                    best = d
    return best


def summarize(rows: list[dict], sources: list[str]) -> dict:
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for s in sources:
            groups[row["g"]][s].append(row["by"][s])
            groups["ALL"][s].append(row["by"][s])
            kind = "place" if row["type"] == "place" else row["type"]
            groups["ALL:" + kind][s].append(row["by"][s])
            groups["style:" + row["s"]][s].append(row["by"][s])
    out = {}
    for g, by in groups.items():
        out[g] = {}
        for s, js in by.items():
            n = len(js)
            hit1 = sum(1 for j in js if j["rank"] == 1)
            hit3 = sum(1 for j in js if j["rank"] and j["rank"] <= 3)
            hit5 = sum(1 for j in js if j["rank"] and j["rank"] <= 5)
            mrr = sum(1.0 / j["rank"] for j in js if j["rank"]) / n
            p5 = [sum(j["ok"][:5]) / 5 for j in js if j.get("type") in ("cat", "brand")]
            ms = [j["ms"] for j in js]
            out[g][s] = {"n": n, "hit1": round(hit1 / n, 3), "hit3": round(hit3 / n, 3), "hit5": round(hit5 / n, 3),
                         "mrr": round(mrr, 3), "p5": round(sum(p5) / len(p5), 3) if p5 else None,
                         "ms_p50": sorted(ms)[len(ms) // 2] if ms else None}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="append", required=True, help="name=dir")
    ap.add_argument("--oracle", default=None, help="index name used for the category oracle (default: first)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--html", default=None)
    ap.add_argument("--only", default=None, help="comma list of groups")
    a = ap.parse_args(argv)
    lx = E.Lexicon.load(LEXICON)
    engines = {}
    for spec in a.index:
        name, path = spec.split("=", 1)
        engines[name] = E.Engine(E.Index(path), lx)
    sources = list(engines)
    oracle_ix = engines[a.oracle or sources[0]].ix
    rows = []
    qs = [q for q in Q.Q if not a.only or q["g"] in a.only.split(",")]
    for qi, q in enumerate(qs):
        lat, lng, gov = Q.ANCHORS[q["at"]]
        row = {"i": qi, "q": q["q"], "at": q["at"], "gov": gov, "g": q["g"], "s": q["s"],
               "type": "place" if "place" in q else "cat" if "cat" in q else "brand",
               "expect": q.get("place") or q.get("cat") or q.get("brand"), "route": q.get("route"),
               "dest": q.get("dest"), "anchor": [lat, lng], "by": {}, "res": {}}
        orc = oracle(q, oracle_ix, (lat, lng)) if row["type"] != "place" else None
        row["oracle_m"] = round(orc) if orc is not None else None
        for s, eng in engines.items():
            t = time.time()
            rs = eng.search(q["q"], lat, lng, limit=10, route=Q.ROUTES.get(q.get("route")) if q.get("route") else None,
                            dest=q.get("dest"))
            ms = round((time.time() - t) * 1000)
            j = judge(q, rs, (lat, lng))
            j["ms"] = ms
            j["type"] = row["type"]
            if row["type"] != "place" and rs:
                j["first_m"] = round(rs[0].dist)
            row["by"][s] = j
            row["res"][s] = [{"n_ar": r.name_ar, "n_en": r.name_en, "cat": r.cat, "lat": round(r.lat, 5),
                              "lng": round(r.lng, 5), "d": round(r.dist), "src": r.row.get("srcs"), "pid": r.pid,
                              "ok": (j["ok"][k] if k < len(j["ok"]) else None)} for k, r in enumerate(rs[:5])]
        rows.append(row)
        if qi % 25 == 0:
            print(f"[bench] {qi}/{len(qs)}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    summary = summarize(rows, sources)
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"sources": sources, "rows": rows}, f, ensure_ascii=False)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    if a.html:
        from . import review
        meta = {s: engines[s].ix.manifest.get("version") for s in sources}
        review.write(a.html, sources, rows, summary, meta)
    for g in ["ALL", "ALL:place", "ALL:cat", "ALL:brand"]:
        if g in summary:
            print(g, {s: (v["hit1"], v["hit5"], v["p5"]) for s, v in summary[g].items()})


if __name__ == "__main__":
    main()
