"""The release gate: a weekly build is published only if it is not worse than the one it replaces.

    python -m tools.place_index.bench.gate --index <new dir> [--previous <bench.json>] [--out <bench.json>]

1. STRUCTURE   the national file and every tile named by the manifest exist with their sha256; the
               place count is ≥ 90 % of the previous release's; total ≤ BUDGET_BYTES, no file over
               MAX_FILE_BYTES (GitHub's limit is 2 GiB — ours keeps the index mirrorable on
               Cloudflare Pages, 25 MiB a file).
2. QUALITY     the benchmark (queries.py, the merged index alone) per query: a query that was found
               in the top 5 and is not any more is a REGRESSION, the reverse an improvement. Fail when
               regressions − improvements > MAX_NET_REGRESSIONS, or Hit@1 over all queries drops by
               more than MAX_HIT1_DROP, or any kind (place / category / chain) drops Hit@5 by more
               than MAX_KIND_DROP.
   The reference is the previous release's bench.json (an asset of every release) or, before the
   first release, tools/place_index/bench/baseline.json (the desk run the doc reports; tiny).
Writes the new bench.json (per-query ranks + the summary) for the next run; exit 1 = do not publish.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys

from .. import engine as E
from . import queries as Q
from . import run as RUN

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")

BUDGET_BYTES = 400_000_000
MAX_FILE_BYTES = 25 * 1024 * 1024
MIN_PLACES_RATIO = 0.90
MAX_NET_REGRESSIONS = 4
MAX_HIT1_DROP = 0.02
MAX_KIND_DROP = 0.04
# adapter (build_report "loaded") → (fetch_report key, its row count, the least share the adapter must yield).
# Floors sit at about half the measured yield (2026-10-31: Overture 0.87, Wikidata 1.0, GeoNames 0.34 —
# it keeps populated places only; Foursquare 0.56 — closed and 7-year-stale rows dropped).
SOURCE_YIELD = {
    "overture places": ("overture", "places", 0.40),
    "foursquare": ("fsq", "rows", 0.25),
    "allplaces": ("atp", "features", 0.50),
    "wikidata": ("wikidata", "items", 0.50),
    "geonames": ("geonames", "rows", 0.15),
    "user places": ("learning", "ugc_places_export", 0.50),
}


PRESENT_MIN = 0.5  # a source with records in a recent release must keep ≥ this share of its largest count


def sources(index_dir: str, prev_builds: list[str] = ()) -> list[str]:
    """No silent source loss: a source that FETCHED rows but whose adapter failed, yielded nothing, or yielded
    less than its floor refuses the release (the 2026-10-31 build dropped all 129,729 Foursquare rows on a
    TypeError and still passed). And a source that had records in any of the newest releases (`prev_builds`,
    their build_report.json) must keep ≥ PRESENT_MIN of its largest count there — a failed FETCH included
    (places-2026-10-31.2 published without its 69k Wikidata items): the last good release stays live. A source
    no recent release had (a token-gated one never configured) may fail without blocking."""
    try:
        with open(os.path.join(index_dir, "build_report.json"), encoding="utf-8") as f:
            build = json.load(f)
        with open(os.path.join(index_dir, "fetch_report.json"), encoding="utf-8") as f:
            fetch = json.load(f)
    except FileNotFoundError:
        return []  # a desk gate of an index without its reports
    errs = [f"source failed in the build: {e}" for e in build.get("failed", [])]
    loaded = build.get("loaded", {})
    for name, (key, field, floor) in SOURCE_YIELD.items():
        rep = fetch.get(key)
        got = rep.get(field) if isinstance(rep, dict) and "error" not in rep else None
        if not isinstance(got, int) or got <= 0:
            continue
        n = loaded.get(name, 0)
        if n == 0 or n < floor * got:
            errs.append(f"source {name}: fetched {got:,} rows, the build kept {n:,} ({n / got:.0%} < {floor:.0%})")
    best: dict = {}
    for p in prev_builds:
        with open(p, encoding="utf-8") as f:
            prev = json.load(f)
        for src, k in prev.get("records", {}).get("by_source", {}).items():
            if k > best.get(src, (0, ""))[0]:
                best[src] = (k, prev.get("version", os.path.basename(p)))
    now = build.get("records", {}).get("by_source", {})
    for src, (k, ver) in sorted(best.items()):
        if now.get(src, 0) < PRESENT_MIN * k:
            errs.append(f"source {src}: {now.get(src, 0):,} records, the {ver} release had {k:,} "
                        f"(< {PRESENT_MIN:.0%}) — the last good release stays live")
    return errs


def structure(index_dir: str, prev: dict | None) -> list[str]:
    errs = []
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    total = 0
    if not man.get("router"):
        errs.append("no router — a place outside the tiles around the user would be unfindable (router.py)")
    for t in [man["national"]] + man["tiles"] + ([man["router"]] if man.get("router") else []):
        p = os.path.join(index_dir, t["file"])
        if not os.path.exists(p):
            errs.append(f"missing {t['file']}")
            continue
        with open(p, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != t["sha256"]:
            errs.append(f"sha256 mismatch {t['file']}")
        if len(data) > MAX_FILE_BYTES:
            errs.append(f"{t['file']} is {len(data)} bytes > {MAX_FILE_BYTES}")
        try:
            gzip.decompress(data)
        except (OSError, EOFError) as e:
            errs.append(f"{t['file']} is not a valid gzip: {e}")
        total += len(data)
    if total > BUDGET_BYTES:
        errs.append(f"total {total} bytes > budget {BUDGET_BYTES}")
    n = man["totals"]["places"]
    if prev and prev.get("places") and n < MIN_PLACES_RATIO * prev["places"]:
        errs.append(f"places {n} < {MIN_PLACES_RATIO:.0%} of the previous {prev['places']}")
    return errs


def bench(index_dir: str) -> dict:
    lx = E.Lexicon.load(RUN.LEXICON)
    eng = E.Engine(E.Index(index_dir), lx)
    ranks, rows = {}, []
    for q in Q.Q:
        lat, lng, _ = Q.ANCHORS[q["at"]]
        rs = eng.search(q["q"], lat, lng, limit=10, route=Q.ROUTES.get(q.get("route")) if q.get("route") else None,
                        dest=q.get("dest"))
        j = RUN.judge(q, rs, (lat, lng))
        j["ms"] = 0
        j["type"] = "place" if "place" in q else "cat" if "cat" in q else "brand"
        key = f"{q['q']}@{q['at']}"
        ranks[key] = j["rank"]
        rows.append({"g": q["g"], "s": q["s"], "type": j["type"], "by": {"index": j}})
    summ = RUN.summarize(rows, ["index"])
    return {"ranks": ranks, "summary": {g: v["index"] for g, v in summ.items()}}


def compare(new: dict, ref: dict) -> tuple[list[str], dict]:
    errs = []
    reg, imp = [], []
    for k, r in new["ranks"].items():
        if k not in ref["ranks"]:
            continue
        was = ref["ranks"][k]
        now5, was5 = bool(r and r <= 5), bool(was and was <= 5)
        if was5 and not now5:
            reg.append(k)
        elif now5 and not was5:
            imp.append(k)
    if len(reg) - len(imp) > MAX_NET_REGRESSIONS:
        errs.append(f"{len(reg)} queries lost their top-5 answer, {len(imp)} gained one (net > {MAX_NET_REGRESSIONS})")
    a, b = new["summary"].get("ALL", {}), ref["summary"].get("ALL", {})
    if b and a["hit1"] < b["hit1"] - MAX_HIT1_DROP:
        errs.append(f"Hit@1 {a['hit1']} < previous {b['hit1']} − {MAX_HIT1_DROP}")
    for kind in ("ALL:place", "ALL:cat", "ALL:brand"):
        a, b = new["summary"].get(kind), ref["summary"].get(kind)
        if a and b and a["hit5"] < b["hit5"] - MAX_KIND_DROP:
            errs.append(f"{kind} Hit@5 {a['hit5']} < previous {b['hit5']} − {MAX_KIND_DROP}")
    return errs, {"regressed": reg, "improved": imp}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--previous", help="the previous release's bench.json (default: baseline.json)")
    ap.add_argument("--previous-builds", nargs="*", default=[],
                    help="the newest releases' build_report.json (the sources this build must still carry)")
    ap.add_argument("--out", help="where to write this build's bench.json (default <index>/bench.json)")
    ap.add_argument("--write-baseline", action="store_true", help="also replace baseline.json (desk only)")
    a = ap.parse_args(argv)
    ref_path = a.previous if a.previous and os.path.exists(a.previous) else BASELINE
    ref = None
    if os.path.exists(ref_path):
        with open(ref_path, encoding="utf-8") as f:
            ref = json.load(f)
    with open(os.path.join(a.index, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    errs = sources(a.index, a.previous_builds) + structure(a.index, ref)
    new = bench(a.index)
    new["version"], new["places"] = man.get("version"), man["totals"]["places"]
    delta = {}
    if ref:
        e2, delta = compare(new, ref)
        errs += e2
    new["delta"] = delta
    out = a.out or os.path.join(a.index, "bench.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    if a.write_baseline:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump({k: new[k] for k in ("version", "places", "ranks", "summary")}, f, ensure_ascii=False, indent=0)
    s = new["summary"]
    print("[gate] reference", os.path.basename(ref_path) if ref else "none")
    for g in ("ALL", "ALL:place", "ALL:cat", "ALL:brand"):
        if g in s:
            print(f"[gate] {g:10} hit1 {s[g]['hit1']:.3f} hit5 {s[g]['hit5']:.3f}"
                  + (f"  (was {ref['summary'][g]['hit1']:.3f} / {ref['summary'][g]['hit5']:.3f})"
                     if ref and g in ref["summary"] else ""))
    if delta:
        print(f"[gate] regressed {len(delta['regressed'])}, improved {len(delta['improved'])}")
        for k in delta["regressed"][:20]:
            print("[gate]   lost", k)
    for e in errs:
        print("[gate] FAIL", e)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=place-index gate refused::{e}")  # an annotation on the run's summary page
    if errs and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("### The release gate refused this build\n\n" + "".join(f"- {e}\n" for e in errs))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
