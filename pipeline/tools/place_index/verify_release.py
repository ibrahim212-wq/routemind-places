"""Verify a PUBLISHED release the way a phone sees it (docs/place-search-2026-10.md §8).

    python -m tools.place_index.verify_release [--repo ibrahim212-wq/routemind-places] [--city cairo]
                                               [--work <dir>] [--keep]

1. the app's own manifest URL (`releases/latest/download/manifest.json`, PlaceStore.DEFAULT_MANIFEST_URL)
   resolves, names its release in `tag` and `base`, and `base` is that release's download prefix;
2. the licence bundle the attribution screen and ODbL need is downloadable (attribution.json, NOTICE.md,
   LICENSE-ODbL-1.0.txt) and so is the release's bench.json;
3. the national file and every tile around the city download from `base`, match the manifest's sha256,
   gunzip, and open read-only as SQLite — exactly PlaceStore's path;
4. the benchmark queries anchored in that city run through the reference engine on THOSE files, and each
   one's rank equals the rank the release gate measured on the built files (bench.json) — the published
   bytes answer exactly what was measured.
Exit 1 on any failure. The downloads (≈ 30 MB for Cairo) are deleted unless --keep.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.request

from . import engine as E
from .bench import queries as Q
from .bench import run as RUN

CITIES = {"cairo": (29.82, 30.95, 30.25, 31.60), "alexandria": (31.05, 29.75, 31.35, 30.10)}  # s, w, n, e
UA = "RouteMind-place-index/1.0 (verify)"


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for k in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except OSError:
            if k == 3:
                raise
    raise RuntimeError(url)


def main(argv=None) -> int:
    for st in (sys.stdout, sys.stderr):  # a Windows console / log file is not UTF-8 by default
        st.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="ibrahim212-wq/routemind-places")
    ap.add_argument("--city", default="cairo", choices=sorted(CITIES))
    ap.add_argument("--work")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    work = a.work or tempfile.mkdtemp(prefix="rm-verify-")
    os.makedirs(work, exist_ok=True)
    fails = []

    def check(cond, what):
        print(("  ok   " if cond else "  FAIL ") + what, flush=True)
        if not cond:
            fails.append(what)

    url = f"https://github.com/{a.repo}/releases/latest/download/manifest.json"
    man = json.loads(get(url))
    tag, base = man.get("tag"), man.get("base", "")
    check(bool(tag) and base == f"https://github.com/{a.repo}/releases/download/{tag}/",
          f"manifest {url} → release {tag}, base {base}")
    check(man.get("attribution") == "attribution.json" and man.get("notice") == "NOTICE.md", "manifest names the licence bundle")
    for f in ("attribution.json", "NOTICE.md", "LICENSE-ODbL-1.0.txt", "bench.json"):
        try:
            n = len(get(base + f))
            check(n > 0, f"{f} downloadable ({n} bytes)")
        except OSError as e:
            check(False, f"{f} downloadable ({e})")
    att = json.loads(get(base + "attribution.json"))
    check(att.get("license") == "ODbL-1.0" and any(s["key"] == "osm" for s in att.get("sources", [])),
          "attribution: ODbL with OpenStreetMap credited — " + ", ".join(s["key"] for s in att.get("sources", [])))

    s, w, n, e = CITIES[a.city]
    # the engine reaches 60 km for a name: every tile it could open for a query anchored in the city
    m = 0.62
    want = [man["national"]] + [t for t in man["tiles"] if t["bbox"][2] >= w - m and t["bbox"][0] <= e + m
                                and t["bbox"][3] >= s - m and t["bbox"][1] <= n + m]
    total = 0
    for t in want:
        gz = get(base + t["file"])
        total += len(gz)
        ok = hashlib.sha256(gz).hexdigest() == t["sha256"]
        raw = gzip.decompress(gz)
        path = os.path.join(work, t["id"] + ".sqlite")
        with open(path, "wb") as f:
            f.write(raw)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        count = con.execute("SELECT count(*) FROM place").fetchone()[0]
        con.close()
        if not ok or count != t["places"]:
            check(False, f"{t['file']}: sha256 {'ok' if ok else 'MISMATCH'}, places {count} vs manifest {t['places']}")
    check(not fails, f"{len(want)} files ({total / 1e6:.1f} MB): sha256 = manifest, gunzip, SQLite opens, place counts = manifest")
    with open(os.path.join(work, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({**man, "tiles": [t for t in man["tiles"] if t in want]}, f)

    bench = json.loads(get(base + "bench.json"))
    lx = E.Lexicon.load(RUN.LEXICON)
    eng = E.Engine(E.Index(work), lx)
    same = differ = hit1 = hit5 = n_q = 0
    for q in Q.Q:
        lat, lng, _ = Q.ANCHORS[q["at"]]
        if not (s <= lat <= n and w <= lng <= e) or q.get("route") or q.get("dest") or q["g"] in ("far",):
            continue
        rs = eng.search(q["q"], lat, lng, limit=10, route=None, dest=None)
        rank = RUN.judge(q, rs, (lat, lng))["rank"]
        was = bench["ranks"].get(f"{q['q']}@{q['at']}")
        n_q += 1
        hit1 += rank == 1
        hit5 += bool(rank and rank <= 5)
        if rank == was:
            same += 1
        else:
            differ += 1
            print(f"         rank {rank} vs gate {was}: «{q['q']}» @ {q['at']}")
    check(differ == 0, f"{n_q} {a.city} benchmark queries on the downloaded files: {same} ranks identical to the gate's, "
                       f"Hit@1 {hit1 / max(1, n_q):.3f}, Hit@5 {hit5 / max(1, n_q):.3f}")
    for con in eng.ix.cons.values():  # Windows cannot delete an open SQLite file
        con.close()
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("verify_release:", "OK" if not fails else f"{len(fails)} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
