"""Per-keystroke search speed: the shipped Kotlin engine over the files a phone on mobile data really holds.

    KOTLINC=<kotlinc.bat> python -m tools.place_index.bench.speed --index <dir> --out <dir> [--anchors downtown,tanta,...] [--items 60]

Method (docs/search-goal.md, criterion 4). For each anchor: a directory with the manifest, the national file and only the tiles
within 3 km of the user (hard links), then every red-team name typed keystroke by keystroke from 2 characters, the same query order a
person produces. Run in one JVM per anchor, RUNS times, keeping each query's best time (this desk is shared with the build and other
work); the first WARMUP queries (JIT warm-up) are not counted. The files are read through once first: this desk's disk is a 5400 rpm
drive and every seek on it is a cost no phone's flash has. The phone estimate multiplies by
PHONE_FACTOR: this desk is an Intel i5-6200U; a mid-range phone (Helio G88 / Snapdragon 680 class) has about half its single-core
speed, and ART plus eMMC / UFS 2 storage cost about 1.5 times more than HotSpot on this disk. A judgement, not a measurement: replace
it with a device trace when one exists.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from .. import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "tool"))

PHONE_FACTOR = 3.0
WARMUP = 150
RING_M = 3000.0
RUNS = 3
ANCHORS = {"downtown": ("cairo", (30.0444, 31.2357)), "mohandessin": ("giza", (30.0566, 31.2003)), "raml": ("alexandria", (31.2001, 29.9187)),
           "tanta": ("gharbia", (30.7865, 31.0004)), "mansoura": ("dakahlia", (31.0409, 31.3785)), "sohag": ("sohag", (26.5591, 31.6957))}


def typed(q: str) -> list[str]:
    return [q[:n] for n in range(2, len(q) + 1) if not q[:n].endswith(" ")]


def main(argv=None) -> None:
    import place_search_parity as P
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--anchors", default=",".join(ANCHORS))
    ap.add_argument("--items", type=int, default=60)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(dir=a.out)
    cp = P.jars()
    jar = P.compile_kotlin(work, cp)
    ix = E.Index(a.index)
    report = {}
    allq: list[float] = []
    for name in a.anchors.split(","):
        gov, (lat, lng) = ANCHORS[name]
        keep = [t for t in ix.near(lat, lng, RING_M)]
        d = os.path.join(work, name)
        os.makedirs(d)
        m = dict(ix.manifest)
        m["tiles"] = [t for t in ix.manifest["tiles"] if t["id"] in keep]
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf8") as f:
            json.dump(m, f)
        for t in keep:
            os.link(os.path.join(a.index, t + ".sqlite"), os.path.join(d, t + ".sqlite"))
        with open(os.path.join(HERE, "redteam", gov + ".json"), encoding="utf8") as f:
            items = [i for i in json.load(f)["items"] if i["t"] in ("place", "chain", "street", "intent")][:a.items]
        qs = [{"q": q, "lat": lat, "lng": lng, "route": None, "dest": None} for it in items for q in typed(it["q"])]
        qpath = os.path.join(work, name + ".json")
        with open(qpath, "w", encoding="utf8") as f:
            json.dump(qs, f, ensure_ascii=False)
        for t in keep:
            with open(os.path.join(d, t + ".sqlite"), "rb") as f:
                f.read()
        rows = None
        for _ in range(RUNS):
            out = P.run_java(jar, cp, "engine", d, P.LEXICON, qpath)
            run = [json.loads(x) for x in out.splitlines() if x.strip()]
            rows = run if rows is None else [dict(x, ms=min(x["ms"], y["ms"])) for x, y in zip(rows, run)]
        ms = sorted(r["ms"] for r in rows[WARMUP:])
        allq += ms
        slow = sorted(((r["ms"], q["q"]) for r, q in zip(rows[WARMUP:], qs[WARMUP:])), reverse=True)[:8]
        report[name] = {"files": len(keep), "queries": len(ms), "p50": ms[len(ms) // 2], "p90": ms[int(len(ms) * 0.9)], "p95": ms[int(len(ms) * 0.95)],
                        "max": ms[-1], "slowest": slow}
        print(name, json.dumps(report[name], ensure_ascii=False), flush=True)
    allq.sort()
    total = {"p50": allq[len(allq) // 2], "p90": allq[int(len(allq) * 0.9)], "p95": allq[int(len(allq) * 0.95)], "phone_factor": PHONE_FACTOR}
    total["phone_p50"] = total["p50"] * PHONE_FACTOR
    total["phone_p95"] = total["p95"] * PHONE_FACTOR
    report["ALL"] = total
    print("ALL", total)
    with open(os.path.join(a.out, "speed.json"), "w", encoding="utf8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
