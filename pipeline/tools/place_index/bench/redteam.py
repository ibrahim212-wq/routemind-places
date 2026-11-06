"""The red-team benchmark: thousands of Egyptian queries in every governorate, measured as a real phone would answer.

    python -m tools.place_index.bench.redteam --index <dir> --out <dir> [--mode 3km|12km|all] [--jobs 2] [--limit N]
        [--gov cairo,giza] [--no-prefix]

The queries (bench/redteam/<gov>.json) were written from knowledge of Egypt by a red-team agent that had no access to the
index, to Google or to any map service; bench/redteam.md has its brief.

`--mode` is the phone's file set, which the other benchmarks do not simulate (they see every tile in 60 km):
  3km   mobile data: the national file + the tiles within 3 km of the user + the routed tiles of the name (router + ≤ 2 fetched)
  12km  Wi-Fi: the same at 12 km, ≤ 3 fetched
  all   every tile (the ceiling: what the engine could do with the whole index on the phone)

Measures (per style, governorate and item type):
  prefix    typed at 2 / 3 / 4 / 6 characters: Hit@1 / Hit@3 (a target whose text is shorter counts at its full text)
  full      the whole text: Hit@1 / Hit@3 / Hit@5
  intent    P@5 (right rows / 5) and Hit@1, for `intent` and `ambiguous` items
  display   on Arabic queries, the top-5 rows: carry an Arabic display name / of those that have any Arabic name
  quality   duplicate rows for one place in a top 5; an unrelated row above a right one
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from .. import engine as E
from .. import router as RT
from .. import textnorm as tn
from .run import LEXICON, names_match

HERE = os.path.dirname(os.path.abspath(__file__))
LENGTHS = (2, 3, 4, 6)
RING = {"3km": 3000.0, "12km": 12000.0}
FETCH = {"3km": 2, "12km": 3}

_W: dict = {}


class PhoneIndex(E.Index):
    """The index as the phone holds it: `near` answers only from the tiles the phone has around the user."""

    def __init__(self, dirpath: str, ring_m: float | None):
        super().__init__(dirpath)
        self.ring_m = ring_m
        self.user = (0.0, 0.0)
        self.routed: list[str] = []

    def near(self, lat: float, lng: float, radius_m: float) -> list[str]:
        out = super().near(lat, lng, radius_m)
        if self.ring_m is None:
            return out
        have = set(super().near(self.user[0], self.user[1], self.ring_m)) | set(self.routed) | {"national"}
        return [t for t in out if t in have]


def _init(index_dir: str, mode: str) -> None:
    ix = PhoneIndex(index_dir, RING.get(mode))
    _W.update(eng=E.Engine(ix, E.Lexicon.load(LEXICON)), ix=ix, mode=mode, router=None)
    for fn in ("router.bin", "router.bin.gz"):
        p = os.path.join(index_dir, fn)
        if os.path.exists(p):
            _W["router"] = RT.Router(p)
            break


def search(q: str, lat: float, lng: float, limit: int = 10):
    eng, ix, router, mode = _W["eng"], _W["ix"], _W["router"], _W["mode"]
    ix.user, ix.routed = (lat, lng), []
    extra: list[str] = []
    if router is not None:
        try:
            p = eng.parse(q, lat, lng)
            words = RT.query_words(p)
            if words:
                alat, alng = (p.area["lat"], p.area["lng"]) if p.area and not p.area.get("road") else (lat, lng)
                routed = [t for t, _d in router.route_tiles(words, alat, alng)]
                if mode in RING:
                    # the tiles it already had (around the user) stay; of the others the phone fetches a few, nearest first
                    have = set(E.Index.near(ix, lat, lng, ix.ring_m))
                    fetched = [t for t in routed if t not in have][:FETCH[mode]]
                    routed = [t for t in routed if t in have] + fetched
                    if p.area and not p.area.get("road"):  # a query naming an area fetches the tiles around it like the user's own
                        routed += [t for t in E.Index.near(ix, alat, alng, ix.ring_m) if t != "national"]
                extra = routed[:RT.ROUTE_OPEN_MAX]
        except Exception:
            extra = []
    ix.routed = extra
    t0 = time.perf_counter()
    try:
        rs = eng.search(q, lat, lng, limit=limit, extra=extra)
    except Exception as e:  # noqa: BLE001 - a crash is a miss, counted and printed
        print(f"[redteam] {q!r}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        rs = []
    return rs, (time.perf_counter() - t0) * 1000


def right(item: dict, r, lat: float, lng: float) -> bool:
    row = r.row
    t = item["t"]
    if t in ("place", "street"):
        if not names_match(item["names"], row):
            return False
        if E.haversine(r.lat, r.lng, item["near"][0], item["near"][1]) > item["r_km"] * 1000:
            return False
        return r.kind == 2 if t == "street" else r.kind != 2
    if t == "chain":
        return r.kind == 0 and names_match(item["names"], row) and E.haversine(r.lat, r.lng, lat, lng) <= item["km"] * 1000
    # intent / ambiguous
    if E.haversine(r.lat, r.lng, lat, lng) > item["km"] * 1000:
        return False
    return r.scat in item.get("scats", ()) or any(names_match([w], row) for w in item.get("words", ()))


def quality(rs: list, oks: list[bool]) -> dict:
    keys = Counter()
    for r in rs[:5]:
        nm = tn.normalize(r.name_ar or r.name_en or "")
        keys[(nm, round(r.lat, 3), round(r.lng, 3))] += 1
    dup = sum(v - 1 for v in keys.values() if v > 1)
    return {"dup": dup, "bad_above": bool(oks and True in oks[:5] and oks.index(True) > 0)}


def _rank(oks: list[bool]):
    return oks.index(True) + 1 if True in oks else None


def do_item(task) -> dict:
    gov, idx, item, anchors, prefix = task
    lat, lng = anchors[item["at"]]
    q = item["q"]
    t = item["t"]
    out = {"gov": gov, "i": idx, "t": t, "q": q, "style": item.get("style"), "at": item["at"], "kind": item.get("kind")}
    rs, ms = search(q, lat, lng)
    oks = [right(item, r, lat, lng) for r in rs]
    out.update(rank=_rank(oks), ms=round(ms, 1), n=len(rs), p5=sum(oks[:5]) / 5.0, **quality(rs, oks))
    out["top"] = [{"ar": r.name_ar, "en": r.name_en, "s": r.scat, "k": r.kind, "d": round(r.dist), "ok": oks[i]}
                  for i, r in enumerate(rs[:5])]
    if tn.script_of(tn.normalize(q)) == "ar":
        out["ar_rows"] = sum(1 for r in rs[:5] if r.name_ar)
        out["rows"] = len(rs[:5])
        out["ar_avail"] = sum(1 for r in rs[:5] if r.name_ar or _has_arabic(r.row.get("alt")))
    if prefix and t in ("place", "chain", "street"):
        pre = {}
        text = q
        for L in LENGTHS:
            cut = text[:L]
            if L >= len(text):
                pre[str(L)] = out["rank"]
                continue
            if cut.endswith(" "):
                cut = cut.rstrip()
            rs2, ms2 = search(cut, lat, lng)
            pre[str(L)] = _rank([right(item, r, lat, lng) for r in rs2])
            out.setdefault("ms_pre", []).append(round(ms2, 1))
            if L == 3:
                out["top3ch"] = [{"ar": r.name_ar, "en": r.name_en, "s": r.scat, "d": round(r.dist)} for r in rs2[:3]]
        out["pre"] = pre
    return out


def _has_arabic(s) -> bool:
    if not s:
        return False
    head = s.split("\x1e", 1)[0]  # what follows \x1e is a generated name, not a real one
    return any("؀" <= c <= "ۿ" for c in head)


def load(limit: int | None, govs: set | None, sure_high_only: bool = False):
    base = os.path.join(HERE, "redteam")
    tasks = []
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".json"):
            continue
        gov = fn[:-5]
        if govs and gov not in govs:
            continue
        with open(os.path.join(base, fn), encoding="utf8") as f:
            d = json.load(f)
        anchors = {k: tuple(v) for k, v in d["anchors"].items()}
        for i, it in enumerate(d["items"]):
            if it.get("at") not in anchors or not it.get("q"):
                continue
            if it["t"] in ("place", "street") and not (it.get("near") and it.get("r_km")):
                continue
            if sure_high_only and it.get("sure") not in (None, "high"):
                continue
            tasks.append((gov, i, it, anchors))
    tasks.sort(key=lambda t: (hash(t[2]["q"]) % 1000, t[0], t[1]))
    return tasks[:limit] if limit else tasks


def _r(x):
    return None if x is None else round(x, 3)


def summarize(rows: list[dict]) -> dict:
    named = [r for r in rows if r["t"] in ("place", "chain", "street")]
    intents = [r for r in rows if r["t"] in ("intent", "ambiguous")]

    def hit(rs, k, f=lambda r: r["rank"]):
        return _r(sum(1 for r in rs if f(r) and f(r) <= k) / len(rs)) if rs else None

    def group(rs):
        g = {"n": len(rs), "h1": hit(rs, 1), "h3": hit(rs, 3), "h5": hit(rs, 5)}
        for L in LENGTHS:
            have = [r for r in rs if "pre" in r]
            if have:
                f = lambda r, L=L: r["pre"][str(L)]
                g[f"p{L}_h1"] = hit(have, 1, f)
                g[f"p{L}_h3"] = hit(have, 3, f)
        return g

    s = {"named": group(named), "intent": {"n": len(intents), "h1": hit(intents, 1), "p5": _r(sum(r["p5"] for r in intents) / len(intents)) if intents else None}}
    s["by_type"] = {t: group([r for r in named if r["t"] == t]) for t in ("place", "chain", "street")}
    s["by_style"] = {st: group([r for r in named if r.get("style") == st]) for st in sorted({r.get("style") or "?" for r in named})}
    s["by_gov"] = {g: group([r for r in named if r["gov"] == g]) for g in sorted({r["gov"] for r in rows})}
    s["intent_by_type"] = {t: {"n": len([r for r in intents if r["t"] == t]), "p5": _r(sum(r["p5"] for r in intents if r["t"] == t) / max(1, len([r for r in intents if r["t"] == t])))} for t in ("intent", "ambiguous")}
    s["intent_by_gov"] = {g: _r(sum(r["p5"] for r in intents if r["gov"] == g) / max(1, len([r for r in intents if r["gov"] == g]))) for g in sorted({r["gov"] for r in rows})}
    ar = [r for r in rows if "ar_rows" in r]
    tot = sum(r["rows"] for r in ar)
    s["display"] = {"ar_share": _r(sum(r["ar_rows"] for r in ar) / tot) if tot else None,
                    "of_available": _r(sum(r["ar_rows"] for r in ar) / max(1, sum(r["ar_avail"] for r in ar)))}
    s["quality"] = {"lists_with_duplicates": _r(sum(1 for r in rows if r["dup"]) / len(rows)),
                    "wrong_above_right": _r(sum(1 for r in rows if r["bad_above"]) / len(rows)),
                    "no_results": _r(sum(1 for r in rows if not r["n"]) / len(rows))}
    ms = sorted(r["ms"] for r in rows)
    s["python_ms"] = {"p50": ms[len(ms) // 2], "p95": ms[int(len(ms) * 0.95)]}
    return s


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="3km", choices=["3km", "12km", "all"])
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--gov")
    ap.add_argument("--no-prefix", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    tasks = load(a.limit, set(a.gov.split(",")) if a.gov else None)
    work = [(g, i, it, an, not a.no_prefix) for g, i, it, an in tasks]
    print(f"[redteam] {len(work)} items, mode {a.mode}", flush=True)
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(a.jobs, initializer=_init, initargs=(a.index, a.mode)) as ex:
        for k, r in enumerate(ex.map(do_item, work, chunksize=8)):
            rows.append(r)
            if k % 500 == 0:
                print(f"[redteam] {k}/{len(work)} {round(time.time() - t0)}s", flush=True)
    s = summarize(rows)
    with open(os.path.join(a.out, f"results_{a.mode}.json"), "w", encoding="utf8") as f:
        json.dump(rows, f, ensure_ascii=False)
    with open(os.path.join(a.out, f"summary_{a.mode}.json"), "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: s[k] for k in ("named", "intent", "by_type", "by_style", "display", "quality", "python_ms")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
