"""What earlier open releases carried and the current one no longer does: the same data, the same licences.

Overture and Foursquare OS Places drop places from one release to the next: some closed, many only because a provider's
feed changed. A place gone from the current release is doubtful, not disproved, so it goes where every doubtful row goes,
the long tail (longtail.py): findable by a strong name match, under every current answer, never listed under a kind or a
chain, never shown as certainly open.

The store is a union, newest version of every id first, kept as two parquet files in the data repository's `history`
release (never the latest release: phones read `releases/latest/download/manifest.json`). Every weekly run adds the
current rows and whatever listed release is not covered yet, so a place that leaves a later release is already on file.
A row closed in a newer release stays closed: the newest version wins and the adapters drop a closed row.

`<data>/fsq_history.parquet` and `<data>/overture/places_history.parquet` = the store minus the ids of the current
release: what build.load reads. A source that cannot be read this run is skipped and reported; nothing else depends on it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import fetch as F
from . import publish as P

TAG = "history"
PUBLIC_REPO = "ibrahim212-wq/routemind-places"
BUDGET_S = 2400            # per source: a run spends at most this on releases not covered yet; the rest wait for next week
OVERTURE_COLS = ("id", "geometry", "bbox", "confidence", "websites", "socials", "phones", "brand", "addresses",
                 "names", "sources", "operating_status", "taxonomy", "categories")
STATE = "history.json"
ARCHIVE_HOST = "https://data.source.coop"
ARCHIVE_ROOT = "fused/overture/"  # the data is Overture's, under Overture's licences; the mirror adds no terms of its own
BODY = ("Places earlier Overture Maps and Foursquare OS Places releases carried. Input of the weekly place index: "
        "not an index, nothing here reaches a phone directly. Overture Maps places: CDLA Permissive 2.0 (Foursquare's "
        "rows Apache 2.0, AllThePlaces' CC0). Foursquare OS Places: Apache 2.0.")


def log(*a):
    print("[history]", *a, flush=True)


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or PUBLIC_REPO


def _download(name: str, path: str) -> bool:
    """A public asset: no token, and a store that is not there yet is simply an empty one."""
    url = f"https://github.com/{_repo()}/releases/download/{TAG}/{name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": F.UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(path, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


class Union:
    """Fed newest first: the first version of an id wins, a later table only adds ids not seen. Only the new rows of each
    table are held, so twenty releases cost what one costs."""

    def __init__(self, key: str):
        self.key, self.seen, self.tables = key, set(), []

    def add(self, t) -> int:
        import pyarrow as pa
        keep = []
        for i, v in enumerate(t[self.key].to_pylist()):
            if v is not None and v not in self.seen:
                self.seen.add(v)
                keep.append(i)
        t = t.take(pa.array(keep, type=pa.int64()))
        self.tables.append(t)
        return t.num_rows

    def table(self):
        import pyarrow as pa
        return pa.concat_tables(self.tables, promote_options="permissive")


def gone(store, current, key: str):
    """The store minus the ids the current release still has."""
    import pyarrow.compute as pc
    return store.filter(pc.invert(pc.is_in(store[key], value_set=pc.unique(current[key]))))


def _norm_fsq(t):
    """Dates were dates in some releases and strings in others."""
    import pyarrow as pa
    for c in ("date_refreshed", "date_closed", "date_created"):
        if c in t.column_names and t.schema.field(c).type != pa.string():
            t = t.set_column(t.column_names.index(c), c, t[c].cast(pa.string()))
    return t


def _read(path: str, cols=None):
    import pyarrow.parquet as pq
    if cols:
        have = pq.ParquetFile(path).schema_arrow.names
        cols = [c for c in cols if c in have]
    return pq.read_table(path, columns=cols)


def _one(data: str, name: str, key: str, current_path: str, listed: list[str], latest: str | None, covered: list[str],
         fetch_release, cols, deadline: float, out_path: str, report: dict) -> bool:
    """Returns True when the store changed. `fetch_release(rel, path)` writes one release's Egyptian rows to `path`."""
    import pyarrow.parquet as pq
    store_path = os.path.join(data, "history", f"{name}_seen.parquet")
    r = report.setdefault(name, {"releases": {}})
    if not os.path.exists(current_path):
        r["skipped"] = "no current release on this run"
        return False
    current = _norm(name, _read(current_path, cols))
    u = Union(key)
    r["current_new"] = u.add(current)
    done = []
    tmp = os.path.join(data, "history", f"{name}_one.parquet")
    for rel in sorted((x for x in listed if x != latest and x not in covered), reverse=True):
        if time.time() > deadline:
            r["waiting"] = r.get("waiting", 0) + 1
            continue
        try:
            F._retry(f"{name} {rel}", lambda rl=rel: fetch_release(rl, tmp))
            t = _norm(name, _read(tmp, cols))
            r["releases"][rel] = {"rows": t.num_rows, "new": u.add(t)}
            done.append(rel)
            log(name, rel, json.dumps(r["releases"][rel]))
        except Exception as e:  # noqa: BLE001 — one old release that cannot be read costs only that release
            r["releases"][rel] = f"{type(e).__name__}: {str(e)[:160]}"
            log(name, rel, "FAILED", r["releases"][rel])
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    if os.path.exists(store_path):
        r["stored_new"] = u.add(_norm(name, _read(store_path)))
    merged = u.table()
    r["current_rows"] = current.num_rows
    r["store_rows"] = merged.num_rows
    left = gone(merged, current, key)
    r["not_in_current"] = left.num_rows
    pq.write_table(left, out_path, compression="zstd")
    pq.write_table(merged, store_path, compression="zstd")
    covered.extend(done)
    return True


def _norm(name: str, t):
    return _norm_fsq(t) if name == "fsq" else t


def _archive():
    """Anonymous, by range requests: the Egypt box of one release costs about 135 MB of 15 GB."""
    import pyarrow.fs as fs
    try:
        return fs.S3FileSystem(anonymous=True, endpoint_override=ARCHIVE_HOST, region="us-west-2")
    except Exception as e:  # noqa: BLE001 — without the archive the bucket's releases still count
        log("archive", repr(e)[:200])
        return None


def _archive_releases(archive) -> list[str]:
    import pyarrow.fs as fs
    try:
        infos = archive.get_file_info(fs.FileSelector(ARCHIVE_ROOT))
        names = (i.path.rsplit("/", 1)[-1] for i in infos if i.type == fs.FileType.Directory)
        return sorted(n for n in names if n[:4].isdigit())  # the bucket also holds a `docs` folder
    except OSError as e:
        log("archive listing", repr(e)[:200])
        return []


def _publish(paths: list[str]) -> str:
    """Into the `history` release, never marked latest. Without a token (a desk run) nothing is uploaded."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token or not os.environ.get("GITHUB_REPOSITORY"):
        return "not uploaded (no token)"
    gh = P.Gh(token, os.environ["GITHUB_REPOSITORY"])
    code, rel = gh.call("GET", f"/repos/{gh.repo}/releases/tags/{TAG}")
    if code != 200:
        rel = gh.need("POST", f"/repos/{gh.repo}/releases",
                      body={"tag_name": TAG, "name": "Release history (pipeline input)", "body": BODY,
                            "prerelease": True, "make_latest": "false"})
    assets = {a["name"]: a["id"] for a in gh.need("GET", f"/repos/{gh.repo}/releases/{rel['id']}/assets?per_page=100")}
    for path in paths:
        name = os.path.basename(path)
        if name in assets:
            gh.call("DELETE", f"/repos/{gh.repo}/releases/assets/{assets[name]}")
        P.upload(gh, rel, name, path, "application/octet-stream")
    return f"uploaded {len(paths)}"


def run(data: str) -> dict:
    os.makedirs(os.path.join(data, "history"), exist_ok=True)
    state = {"fsq": [], "overture": []}
    state_path = os.path.join(data, "history", STATE)
    if _download(STATE, state_path):
        with open(state_path, encoding="utf-8") as f:
            state.update(json.load(f))
    for n in ("fsq", "overture"):
        _download(f"{n}_seen.parquet", os.path.join(data, "history", f"{n}_seen.parquet"))
    report: dict = {}
    budget = float(os.environ.get("HISTORY_BUDGET_S") or BUDGET_S)
    changed = []

    # Overture: its bucket holds about 60 days of releases, the Fused copy (Source Cooperative) those back to 2024
    s3 = F._s3("us-west-2")
    listed = F.overture_releases(s3)
    latest = listed[-1] if listed else None
    archive = _archive()
    old = _archive_releases(archive) if archive else []
    report["overture_archive"] = len(old)
    bucket = set(listed)

    def one_overture(rel, p):
        if rel in bucket:
            return F._extract(s3, rel, "places", "place", p)
        return F._extract(archive, rel, "places", "place", p, ARCHIVE_ROOT)

    ov_cur = os.path.join(data, "overture", "places_eg_bbox.parquet")
    if _one(data, "overture", "id", ov_cur, listed + [x for x in old if x not in bucket], latest, state["overture"],
            one_overture, OVERTURE_COLS, time.time() + budget, os.path.join(data, "overture", "places_history.parquet"), report):
        changed.append("overture")

    # Foursquare: every dated release of the Hugging Face copy, which needs the token the weekly fetch already uses
    token = os.environ.get("HF_TOKEN")
    if token:
        listed = F.fsq_hf_releases()
        cur = os.path.join(data, "fsq.parquet")
        if _one(data, "fsq", "fsq_place_id", cur, listed, listed[-1] if listed else None, state["fsq"],
                lambda rel, p: F.fetch_fsq_hf(os.path.dirname(p), token, rel=rel, out=os.path.basename(p)), F.FSQ_COLS,
                time.time() + budget, os.path.join(data, "fsq_history.parquet"), report):
            changed.append("fsq")
    else:
        report["fsq"] = {"skipped": "HF_TOKEN is not set"}

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    if changed:
        report["store"] = _publish([os.path.join(data, "history", f"{n}_seen.parquet") for n in changed] + [state_path])
    return report
