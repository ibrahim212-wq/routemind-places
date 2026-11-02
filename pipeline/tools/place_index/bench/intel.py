"""The search-INTELLIGENCE benchmark: does the on-device search behave like Google Maps for an Egyptian?

    python -m tools.place_index.bench.intel --index <dir> --out <dir>
        [--suites prefix,exact,variant,need,script,important] [--jobs 3] [--limit N]

The data (intel_queries.py) is written from knowledge of Egypt, never from the index. Each search is
the PHONE's: the query is parsed, its name words go through the name router (router.bin, else
router.bin.gz; no router = no routing) and the routed tiles (≤ ROUTE_OPEN_MAX) are searched beyond the
tiles around the user, as PlaceStore does.

  prefix     every prefix of the text from 1 character (a prefix ending in a space is skipped: the
             engine sees the same text as one character earlier), top 10, the rank of the first right
             result. Per target: chars to top 1 / top 3 (first reached; `stable_*` = from there to the
             full text without dropping out). Overall: mean / median of those over the targets that
             reach it, the share that reaches it by the full text, Hit@1 / Hit@3 at typed lengths
             2 3 4 5 6 8 and the full text (a shorter target counts at its full text); Arabic vs Latin.
  exact      rank-1 rate (the whole name typed must be the first answer), Hit@3, MRR
  variant    Hit@1 / Hit@3 / Hit@5, MRR
  need       Hit@1 (the first answer is a shop that does it, near), P@5
  script     over every Arabic-script query searched by any suite in the run (the prefix suite: its
             full text), the share of the top-5 rows that carry an Arabic name
  important  coverage (the index HAS the place: any file's place table holds a row whose name / alt
             matches within r — candidates by the rarest word through `tok`, then names_match +
             distance), findable-near (rank ≤ 3 searching `query` from the place), findable-far
             (rank ≤ 3 from downtown Cairo; places in Cairo from Alexandria's Raml)

Writes results.json (every query, top 5 with scat / distance, the verdict) and summary.json; prints a
compact table. Multiprocessing: --jobs workers, each with its own Engine.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

from .. import engine as E
from .. import router as RT
from .. import textnorm as tn
from . import intel_queries as IQ
from .queries import ANCHORS
from .run import LEXICON, names_match

LENGTHS = (2, 3, 4, 5, 6, 8)
SUITES = ("prefix", "exact", "variant", "need", "script", "important")
FAR_FROM = {"default": "downtown", "cairo": "raml"}  # where the far search of an important place is typed

_W: dict = {}


# ── worker ───────────────────────────────────────────────────────────────────────────────────────

def _init(index_dir: str) -> None:
    _W.clear()
    _W["eng"] = E.Engine(E.Index(index_dir), E.Lexicon.load(LEXICON))
    _W["router"] = None
    for fn in ("router.bin", "router.bin.gz"):
        p = os.path.join(index_dir, fn)
        if os.path.exists(p):
            try:
                _W["router"] = RT.Router(p)
            except (OSError, ValueError) as e:
                print(f"[intel] router {p} unreadable ({e}): searching without routing", flush=True)
            break


def phone_search(q: str, lat: float, lng: float, limit: int = 10):
    """(results, ms, routed tiles opened, error) — the engine fed the name router's tiles like the phone."""
    eng, router = _W["eng"], _W["router"]
    t0 = time.time()
    extra: list[str] = []
    if router is not None:
        try:
            p = eng.parse(q, lat, lng)
            words = RT.query_words(p)
            if words:
                alat, alng = lat, lng
                if p.area and not p.area.get("road"):  # a query naming an area is routed from there
                    alat, alng = p.area["lat"], p.area["lng"]
                extra = [t for t, _d in router.route_tiles(words, alat, alng)][:RT.ROUTE_OPEN_MAX]
        except Exception:  # a parse the router cannot use routes nothing; the search still runs
            extra = []
    try:
        rs, err = eng.search(q, lat, lng, limit=limit, extra=extra), None
    except Exception as e:
        rs, err = [], f"{type(e).__name__}: {e}"
    return rs, round((time.time() - t0) * 1000), extra, err


def _gates_ok(t: dict, kind: int, scat) -> bool:
    if t.get("poi") and kind == 1:
        return False
    if t.get("area") and kind != 1:
        return False
    if t.get("scats") and scat not in t["scats"]:
        return False
    return True


def judge(item: dict, rs: list, lat: float, lng: float) -> dict:
    oks: list[bool] = []
    out: dict = {}
    if "place" in item:
        t = item["place"]
        for r in rs:
            named = names_match(t["names"], r.row)
            d = E.haversine(r.lat, r.lng, t["near"][0], t["near"][1])
            ok = named and d <= t["r"] and _gates_ok(t, r.kind, r.scat)
            if named and not ok and "named_off" not in out:  # the right name, wrong place or wrong kind
                out["named_off"] = {"rank": len(oks) + 1, "m": round(d), "kind": r.kind, "scat": r.scat}
            oks.append(ok)
    elif "cat" in item:
        t = item["cat"]
        for r in rs:
            d = E.haversine(r.lat, r.lng, lat, lng)
            kind_ok = r.scat in t["scats"] or any(names_match([w], r.row) for w in t["words"])
            oks.append(kind_ok and d <= t["km"] * 1000)
    elif "chain" in item:
        t = item["chain"]
        for r in rs:
            d = E.haversine(r.lat, r.lng, lat, lng)
            oks.append(names_match(t["names"], r.row) and d <= t["km"] * 1000)
    out["rank"] = oks.index(True) + 1 if True in oks else None
    out["ok"] = oks[:5]
    return out


def _top(rs: list, oks=None, n=5) -> list[dict]:
    return [{"n_ar": r.name_ar, "n_en": r.name_en, "scat": r.scat, "kind": r.kind, "d": round(r.dist),
             "ok": (oks[k] if oks is not None and k < len(oks) else None)} for k, r in enumerate(rs[:n])]


def _script(q: str) -> str:
    return "ar" if tn.script_of(tn.normalize(q)) == "ar" else "latin"


def _do_prefix(i: int, item: dict) -> dict:
    text = item["q"]
    lat, lng = IQ.anchor(item["at"])
    steps = []
    full = None
    for L in range(1, len(text) + 1):
        pre = text[:L]
        if pre.endswith(" ") or not pre.strip():
            continue
        rs, ms, extra, err = phone_search(pre, lat, lng)
        j = judge(item, rs, lat, lng)
        top1 = rs[0] if rs else None
        steps.append({"L": L, "rank": j["rank"], "ms": ms, "routed": len(extra),
                      "top1": (top1.name_ar or top1.name_en) if top1 else None, **({"err": err} if err else {})})
        if L == len(text):
            full = {"rank": j["rank"], "top5": _top(rs, j["ok"]), "named_off": j.get("named_off"), "err": err}
    ranks = {s["L"]: s["rank"] for s in steps}

    def first(cut):
        return next((s["L"] for s in steps if s["rank"] is not None and s["rank"] <= cut), None)

    def stable(cut):
        best = None
        for s in reversed(steps):
            if s["rank"] is not None and s["rank"] <= cut:
                best = s["L"]
            else:
                break
        return best

    at_len = {}
    for n in LENGTHS + ("full",):
        upto = len(text) if n == "full" or n >= len(text) else n
        ls = [L for L in ranks if L <= upto]
        at_len[str(n)] = ranks[max(ls)] if ls else None
    return {"suite": "prefix", "i": i, "q": text, "at": item["at"], "g": item["g"], "script": _script(text),
            "len": len(text), "judge": _judge_of(item), "to_top1": first(1), "to_top3": first(3),
            "stable_top1": stable(1), "stable_top3": stable(3), "at_len": at_len, "full": full, "steps": steps}


def _judge_of(item: dict) -> dict:
    for k in ("place", "cat", "chain"):
        if k in item:
            return {k: item[k]}
    return {}


def _do_query(suite: str, i: int, item: dict) -> dict:
    lat, lng = IQ.anchor(item["at"])
    rs, ms, extra, err = phone_search(item["q"], lat, lng)
    row = {"suite": suite, "i": i, "q": item["q"], "at": item["at"], "g": item.get("g"), "script": _script(item["q"]),
           "ms": ms, "routed": len(extra)}
    if err:
        row["err"] = err
    if suite == "script":
        row["top5"] = _top(rs)
        return row
    j = judge(item, rs, lat, lng)
    row.update({"judge": _judge_of(item), "rank": j["rank"], "ok": j["ok"], "top5": _top(rs, j["ok"])})
    if j.get("named_off"):
        row["named_off"] = j["named_off"]
    for k in ("how", "gov"):
        if k in item:
            row[k] = item[k]
    return row


# ── coverage: is the place in the index at all? ──────────────────────────────────────────────────

def _cand_ids(con, names: list[str]) -> set[int]:
    """Rows that may carry one of the names: for each name, its rarest word's index forms (the word, its
    stems, and — for spelling drift — its skeleton when that is not too common) looked up in `tok`."""
    ids: set[int] = set()
    for nm in names:
        best = None
        for w in tn.tokens(nm):
            if tn.is_stopword(w):
                continue
            forms = list(dict.fromkeys([w] + tn.stems(w)[1:]))
            df, present = 0, []
            for f in forms:
                r = con.execute("SELECT n FROM vocab WHERE t = ?", (f,)).fetchone()
                if r:
                    df += r[0]
                    present.append(f)
            if present and (best is None or df < best[0]):
                best = (df, present, w)
        if best is None:
            continue
        forms = list(best[1])
        sk = tn.skeletons(tn.stems(best[2])[-1])[0]
        if len(sk) >= 3 and not sk.isdigit():
            r = con.execute("SELECT n FROM vocab WHERE t = ?", ("~" + sk,)).fetchone()
            if r and r[0] <= 20000:
                forms.append("~" + sk)
        for f in forms:
            ids.update(x[0] for x in con.execute("SELECT id FROM tok WHERE t = ?", (f,)))
    return ids


def coverage(e: dict) -> list[dict]:
    ix = _W["eng"].ix
    nlat, nlng = e["near"]
    hits = []
    for db in ix.near(nlat, nlng, e["r"]):
        con = ix.cons[db]
        ids = sorted(_cand_ids(con, e["names"]))
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            for r in con.execute(f"SELECT * FROM place WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                row = dict(r)
                d = E.haversine(row["lat"], row["lng"], nlat, nlng)
                if d <= e["r"] and _gates_ok(e, row["kind"], row["scat"]) and names_match(e["names"], row):
                    hits.append({"db": db, "pid": row["pid"], "n_ar": row["name_ar"], "n_en": row["name_en"],
                                 "scat": row["scat"], "kind": row["kind"], "m": round(d)})
    hits.sort(key=lambda h: h["m"])
    return hits


def _do_important(i: int, e: dict) -> dict:
    item = {"place": {k: e[k] for k in ("names", "near", "r", "poi", "area", "scats") if k in e}}
    hits = coverage(e)
    out = {"suite": "important", "i": i, "q": e["query"], "gov": e["gov"], "kind": e["kind"],
           "script": _script(e["query"]), "judge": item, "covered": bool(hits), "cover_hits": hits[:3]}
    far_key = FAR_FROM.get(e["gov"], FAR_FROM["default"])
    for tag, (lat, lng) in (("near", e["near"]), ("far", IQ.anchor(far_key))):
        rs, ms, extra, err = phone_search(e["query"], lat, lng)
        j = judge(item, rs, lat, lng)
        out[tag] = {"rank": j["rank"], "ms": ms, "routed": len(extra), "top5": _top(rs, j["ok"]),
                    **({"from": far_key} if tag == "far" else {}), **({"err": err} if err else {}),
                    **({"named_off": j["named_off"]} if j.get("named_off") else {})}
    return out


def _task(task):
    suite, i, item = task
    t0 = time.time()
    try:
        if suite == "prefix":
            r = _do_prefix(i, item)
        elif suite == "important":
            r = _do_important(i, item)
        else:
            r = _do_query(suite, i, item)
    except Exception as e:  # one broken query never stops the run
        import traceback
        r = {"suite": suite, "i": i, "q": item.get("q") or item.get("query"), "error": f"{type(e).__name__}: {e}",
             "trace": traceback.format_exc(limit=4)}
    r["sec"] = round(time.time() - t0, 2)
    return r


# ── summaries ────────────────────────────────────────────────────────────────────────────────────

def _r(x, nd=3):
    return round(x, nd) if x is not None else None


def _mean(xs):
    return _r(sum(xs) / len(xs), 2) if xs else None


def _median(xs):
    return _r(statistics.median(xs), 1) if xs else None


def _share(n, d):
    return _r(n / d) if d else None


def _by_script(rows):
    groups = {"all": rows, "ar": [r for r in rows if r.get("script") == "ar"],
              "latin": [r for r in rows if r.get("script") != "ar"]}
    return {g: rs for g, rs in groups.items() if rs}


def _sum_prefix(rows):
    out = {}
    for g, rs in _by_script(rows).items():
        n = len(rs)
        t1 = [r["to_top1"] for r in rs if r["to_top1"] is not None]
        t3 = [r["to_top3"] for r in rs if r["to_top3"] is not None]
        s1 = [r["stable_top1"] for r in rs if r["stable_top1"] is not None]
        save = [1 - r["to_top1"] / r["len"] for r in rs if r["to_top1"] is not None]
        d = {"n": n,
             "to_top1_mean": _mean(t1), "to_top1_median": _median(t1),
             "to_top3_mean": _mean(t3), "to_top3_median": _median(t3),
             "stable_top1_median": _median(s1),
             "reach_top1": _share(len(t1), n), "reach_top3": _share(len(t3), n),
             "full_top1": _share(sum(1 for r in rs if r["at_len"]["full"] == 1), n),
             "full_top3": _share(sum(1 for r in rs if (r["at_len"]["full"] or 99) <= 3), n),
             "keystrokes_saved_top1": _r(sum(save) / len(save)) if save else None,
             "hit1": {}, "hit3": {}}
        for L in [str(x) for x in LENGTHS] + ["full"]:
            d["hit1"][L] = _share(sum(1 for r in rs if r["at_len"][L] == 1), n)
            d["hit3"][L] = _share(sum(1 for r in rs if (r["at_len"][L] or 99) <= 3), n)
        out[g] = d
    out["by_group"] = {}
    groups = defaultdict(list)
    for r in rows:
        groups[r["g"]].append(r)
    for g, rs in sorted(groups.items()):
        t1 = [r["to_top1"] for r in rs if r["to_top1"] is not None]
        out["by_group"][g] = {"n": len(rs), "reach_top1": _share(len(t1), len(rs)), "to_top1_median": _median(t1),
                              "full_top1": _share(sum(1 for r in rs if r["at_len"]["full"] == 1), len(rs))}
    return out


def _ranked(rs, ks=(1, 3, 5)):
    n = len(rs)
    d = {"n": n}
    for k in ks:
        d[f"hit{k}"] = _share(sum(1 for r in rs if r["rank"] and r["rank"] <= k), n)
    d["mrr"] = _r(sum(1.0 / r["rank"] for r in rs if r["rank"]) / n) if n else None
    return d


def _sum_ranked(rows, ks, key=None):
    out = {g: _ranked(rs, ks) for g, rs in _by_script(rows).items()}
    if key:
        groups = defaultdict(list)
        for r in rows:
            groups[r.get(key)].append(r)
        out["by_" + key] = {str(g): _ranked(rs, ks) for g, rs in sorted(groups.items(), key=lambda x: str(x[0]))}
    return out


def _sum_need(rows):
    out = {}
    for g, rs in _by_script(rows).items():
        n = len(rs)
        out[g] = {"n": n, "hit1": _share(sum(1 for r in rs if r["rank"] == 1), n),
                  "p5": _r(sum(sum(1 for x in r["ok"][:5] if x) / 5 for r in rs) / n) if n else None}
    return out


def _sum_script(rows):
    """Every Arabic-script query of the run: the share of its top-5 rows with an Arabic name."""
    per = defaultdict(lambda: {"queries": 0, "rows": 0, "ar_rows": 0, "first_ar": 0})
    for r in rows:
        if r.get("script") != "ar" or "error" in r:
            continue
        lists = []
        if r["suite"] == "prefix":
            lists = [r["full"]["top5"]] if r.get("full") else []
        elif r["suite"] == "important":
            lists = [r[t]["top5"] for t in ("near", "far") if r.get(t)]
        else:
            lists = [r.get("top5") or []]
        for top in lists:
            if not top:
                continue
            for key in (r["suite"], "all"):
                p = per[key]
                p["queries"] += 1
                p["rows"] += len(top)
                p["ar_rows"] += sum(1 for x in top if (x["n_ar"] or "").strip())
                p["first_ar"] += 1 if (top[0]["n_ar"] or "").strip() else 0
    return {k: {**v, "share": _share(v["ar_rows"], v["rows"]), "first_share": _share(v["first_ar"], v["queries"])}
            for k, v in per.items()}


def _sum_important(rows):
    def agg(rs):
        n = len(rs)
        return {"n": n, "covered": _share(sum(1 for r in rs if r["covered"]), n),
                "near_top3": _share(sum(1 for r in rs if (r["near"]["rank"] or 99) <= 3), n),
                "near_top1": _share(sum(1 for r in rs if r["near"]["rank"] == 1), n),
                "far_top3": _share(sum(1 for r in rs if (r["far"]["rank"] or 99) <= 3), n),
                "covered_not_found_near": sum(1 for r in rs if r["covered"] and (r["near"]["rank"] or 99) > 3)}
    rows = [r for r in rows if "error" not in r]
    out = {"all": agg(rows), "by_kind": {}, "by_gov": {}}
    for key, dst in (("kind", "by_kind"), ("gov", "by_gov")):
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        out[dst] = {g: agg(rs) for g, rs in sorted(groups.items())}
    out["missing"] = [{"q": r["q"], "gov": r["gov"], "kind": r["kind"]} for r in rows if not r["covered"]]
    out["covered_not_findable_near"] = [
        {"q": r["q"], "gov": r["gov"], "kind": r["kind"], "near_rank": r["near"]["rank"],
         "have": (r["cover_hits"][0]["n_ar"] or r["cover_hits"][0]["n_en"]) if r["cover_hits"] else None,
         "top1": (r["near"]["top5"][0]["n_ar"] or r["near"]["top5"][0]["n_en"]) if r["near"]["top5"] else None}
        for r in rows if r["covered"] and (r["near"]["rank"] or 99) > 3]
    return out


def summarize(results: list[dict]) -> dict:
    by = defaultdict(list)
    for r in results:
        by[r["suite"]].append(r)
    ok = {s: [r for r in rs if "error" not in r] for s, rs in by.items()}
    out = {"errors": [{"suite": r["suite"], "i": r["i"], "q": r.get("q"), "error": r["error"]}
                      for r in results if "error" in r]}
    if ok.get("prefix"):
        out["prefix"] = _sum_prefix(ok["prefix"])
    if ok.get("exact"):
        out["exact"] = _sum_ranked(ok["exact"], (1, 3), key="gov")
    if ok.get("variant"):
        out["variant"] = _sum_ranked(ok["variant"], (1, 3, 5), key="how")
    if ok.get("need"):
        out["need"] = _sum_need(ok["need"])
    out["script"] = _sum_script(results)
    if ok.get("important"):
        out["important"] = _sum_important(ok["important"])
    return out


def _fmt(x):
    return "-" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


def print_summary(s: dict) -> None:
    p = s.get("prefix")
    if p:
        print("\nPREFIX (keystroke by keystroke)")
        print(f"  {'':6} {'n':>4} {'→top1 mean/med':>15} {'→top3 mean/med':>15} {'reach1':>7} {'reach3':>7} "
              f"{'full1':>6} {'saved':>6}   Hit@1 at " + " ".join(f"{L:>4}" for L in [str(x) for x in LENGTHS] + ["full"]))
        for g in ("all", "ar", "latin"):
            d = p.get(g)
            if not d:
                continue
            print(f"  {g:6} {d['n']:>4} {_fmt(d['to_top1_mean']):>7}/{_fmt(d['to_top1_median']):<7} "
                  f"{_fmt(d['to_top3_mean']):>7}/{_fmt(d['to_top3_median']):<7} {_fmt(d['reach_top1']):>7} "
                  f"{_fmt(d['reach_top3']):>7} {_fmt(d['full_top1']):>6} {_fmt(d['keystrokes_saved_top1']):>6}   "
                  f"{'':9}" + " ".join(f"{_fmt(v):>4}" for v in d["hit1"].values()))
            print(f"  {'':6} {'':>4} {'':>15} {'':>15} {'':>7} {'':>7} {'':>6} {'':>6}   Hit@3 at "
                  + " ".join(f"{_fmt(v):>4}" for v in d["hit3"].values()))
    for name, ks in (("exact", ("hit1", "hit3", "mrr")), ("variant", ("hit1", "hit3", "hit5", "mrr")),
                     ("need", ("hit1", "p5"))):
        d = s.get(name)
        if not d:
            continue
        print(f"\n{name.upper()}  " + "   ".join(
            f"{g}: n={d[g]['n']} " + " ".join(f"{k}={_fmt(d[g][k])}" for k in ks) for g in ("all", "ar", "latin") if g in d))
    sc = s.get("script")
    if sc:
        print("\nSCRIPT (Arabic queries: top-5 rows with an Arabic name)  " + "  ".join(
            f"{k}={_fmt(v['share'])} (first {_fmt(v['first_share'])}, q={v['queries']})" for k, v in sorted(sc.items())))
    im = s.get("important")
    if im:
        a = im["all"]
        print(f"\nIMPORTANT  n={a['n']} covered={_fmt(a['covered'])} near@3={_fmt(a['near_top3'])} "
              f"near@1={_fmt(a['near_top1'])} far@3={_fmt(a['far_top3'])}")
        for dst in ("by_kind", "by_gov"):
            print("  " + dst + ": " + "  ".join(
                f"{g} {v['n']}:{_fmt(v['covered'])}/{_fmt(v['near_top3'])}/{_fmt(v['far_top3'])}" for g, v in im[dst].items()))
        if im["missing"]:
            print(f"  missing ({len(im['missing'])}): " + ", ".join(f"{m['q']} [{m['gov']}]" for m in im["missing"]))
    if s.get("errors"):
        print(f"\nERRORS ({len(s['errors'])}): " + "; ".join(f"{e['suite']}[{e['i']}] {e['error']}" for e in s["errors"][:10]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--index", required=True, help="the index directory (manifest.json, national + tiles, router.bin)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--suites", default=",".join(SUITES))
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="the first N entries of each suite (a smoke run)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    problems = IQ.validate()
    if problems:
        for p in problems:
            print("[intel] DATA PROBLEM", p)
        sys.exit(2)
    suites = [s.strip() for s in a.suites.split(",") if s.strip()]
    for s in suites:
        if s not in SUITES:
            ap.error(f"unknown suite {s} (have {', '.join(SUITES)})")
    tasks = []
    for s in SUITES:  # the long prefix targets first: the pool ends evenly
        if s in suites:
            items = IQ.SUITES[s][:a.limit] if a.limit else IQ.SUITES[s]
            tasks += [(s, i, it) for i, it in enumerate(items)]
    print(f"[intel] {len(tasks)} tasks ({', '.join(f'{s}={sum(1 for t in tasks if t[0] == s)}' for s in suites)}), "
          f"{a.jobs} job(s), index {a.index}", flush=True)
    t0 = time.time()
    results = []

    def progress(k):
        if k % 20 == 0 or k == len(tasks):
            print(f"[intel] {k}/{len(tasks)}  {round(time.time() - t0)} s", flush=True)

    if a.jobs <= 1:
        _init(a.index)
        print(f"[intel] router: {'yes' if _W['router'] else 'none'}", flush=True)
        for k, t in enumerate(tasks, 1):
            results.append(_task(t))
            progress(k)
    else:
        from multiprocessing import Pool
        with Pool(a.jobs, initializer=_init, initargs=(a.index,)) as pool:
            for k, r in enumerate(pool.imap_unordered(_task, tasks, chunksize=1), 1):
                results.append(r)
                progress(k)
    results.sort(key=lambda r: (SUITES.index(r["suite"]), r["i"]))
    summary = summarize(results)
    summary["meta"] = {"index": os.path.abspath(a.index), "suites": suites, "limit": a.limit, "jobs": a.jobs,
                       "tasks": len(tasks), "seconds": round(time.time() - t0),
                       "router": any(os.path.exists(os.path.join(a.index, f)) for f in ("router.bin", "router.bin.gz")),
                       "anchors": {k: v[:2] for k, v in ANCHORS.items()}}
    try:
        with open(os.path.join(a.index, "manifest.json"), encoding="utf-8") as f:
            summary["meta"]["version"] = json.load(f).get("version")
    except (OSError, ValueError):
        pass
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": summary["meta"], "rows": results}, f, ensure_ascii=False)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print_summary(summary)
    print(f"\n[intel] {len(results)} results in {round(time.time() - t0)} s → {a.out}", flush=True)


if __name__ == "__main__":
    main()
