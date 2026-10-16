"""The weekly refresh in ONE command — the same steps on GitHub Actions and on any machine.

    python -m tools.place_index.weekly --work <dir> [--publish --repo <owner>/routemind-places] [--keep 3]
                                       [--only overture,geofabrik,hot,wikidata,geonames,fsq] [--osm pbf]
                                       [--keep-data] [--keep-index] [--no-fetch]

fetch (fetch.py) → build (build.py, `--osm pbf`, every source) → licence bundle (notice.py) →
release gate (bench/gate.py against the LATEST release's bench.json, else baseline.json) →
publish (publish.py: draft, every tile, manifest LAST, then live) → delete the multi-GB working data.

Why one command: the public repository's workflow (`ci/place-index.yml`, docs/place-search-2026-10.md
§8) and the fallback on a desk (`ci/weekly_local.ps1`, a Windows scheduled task) must do exactly the
same thing — a step list kept twice drifts. Exit status: 0 published (or built and gated without
--publish), 1 the gate refused, 2 a required source failed.

The token for --publish is read from PLACES_PUBLISH_TOKEN or GH_TOKEN (GitHub Actions passes its own
GITHUB_TOKEN, which may write the releases of the repository the workflow runs in). It is never
written anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

from . import build as B
from . import fetch as F
from . import notice as N
from . import publish as P

DEFAULT_ONLY = "overture,geofabrik,hot,wikidata,geonames,fsq"  # hot = the OSM fallback if the pbf read fails


def log(*a):
    print("[weekly]", *a, flush=True)


def previous_bench(repo: str, dst: str) -> str | None:
    """The latest published release's bench.json — what this build must not be worse than."""
    url = f"https://github.com/{repo}/releases/latest/download/bench.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": F.UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            f.write(r.read())
        return dst
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log("no previous release bench.json —", str(e)[:120], "— the gate uses bench/baseline.json")
        return None


def run(work: str, repo: str | None, publish: bool, keep: int, only: str, osm: str,
        keep_data: bool, keep_index: bool, fetch: bool = True) -> int:
    data, idx = os.path.join(work, "data"), os.path.join(work, "idx")
    os.makedirs(work, exist_ok=True)
    if os.path.exists(idx):  # never publish a stale tile from an earlier run next to fresh ones
        shutil.rmtree(idx)
    t0 = time.time()
    if fetch:
        try:
            F.main(["--data", data, "--only", only])
        except SystemExit as e:
            if e.code:
                log("fetch:", e.code)
                return 2
    elif not os.path.exists(os.path.join(data, "overture", "places_eg_bbox.parquet")):
        log("--no-fetch, but", data, "holds no Overture places")
        return 2
    version = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    B.run(data, idx, {"osm", "overture", "div", "fsq", "wd", "gn"}, osm, version)
    shutil.copyfile(os.path.join(data, "fetch_report.json"), os.path.join(idx, "fetch_report.json"))
    if not keep_data:
        shutil.rmtree(data, ignore_errors=True)
    N.write(idx)
    prev = previous_bench(repo, os.path.join(work, "prev_bench.json")) if repo else None
    from .bench import gate as G
    try:
        G.main(["--index", idx] + (["--previous", prev] if prev else []))
    except SystemExit as e:
        if e.code:
            log("the gate refused this build — nothing published")
            return 1
    tag = None
    if publish:
        token = os.environ.get("PLACES_PUBLISH_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not repo or not token:
            log("--publish needs --repo and PLACES_PUBLISH_TOKEN / GH_TOKEN")
            return 2
        tag = P.publish(idx, repo, token, keep)
    with open(os.path.join(idx, "build_report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    with open(os.path.join(idx, "bench.json"), encoding="utf-8") as f:
        bench = json.load(f)
    summary = {"version": version, "tag": tag, "places": rep["tiles"]["places"], "files": rep["tiles"]["files"],
               "mb": round(rep["tiles"]["bytes"] / 1e6, 1), "hit1": bench["summary"]["ALL"]["hit1"],
               "hit5": bench["summary"]["ALL"]["hit5"], "minutes": round((time.time() - t0) / 60, 1),
               "failed_sources": sorted(k for k, v in json.load(open(os.path.join(idx, "fetch_report.json"))).items()
                                        if isinstance(v, dict) and "error" in v)}
    with open(os.path.join(work, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    log("summary", json.dumps(summary, ensure_ascii=False))
    if not keep_index:
        # the reports stay; the tiles (≈ 100 MB gzip + ≈ 300 MB raw) are in the release now
        for fn in os.listdir(idx):
            if fn.endswith((".sqlite", ".sqlite.gz")):
                os.remove(os.path.join(idx, fn))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="working directory (data + index); multi-GB while it runs")
    ap.add_argument("--repo", default=os.environ.get("PLACES_REPO"))
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--only", default=DEFAULT_ONLY)
    ap.add_argument("--osm", default="pbf", choices=["pbf", "hot"])
    ap.add_argument("--keep-data", action="store_true", help="keep the fetched sources (debugging)")
    ap.add_argument("--keep-index", action="store_true", help="keep the built tiles after publishing")
    ap.add_argument("--no-fetch", action="store_true", help="build from what <work>/data already holds (resume)")
    a = ap.parse_args(argv)
    sys.exit(run(a.work, a.repo, a.publish, a.keep, a.only, a.osm, a.keep_data, a.keep_index, not a.no_fetch))


if __name__ == "__main__":
    main()
