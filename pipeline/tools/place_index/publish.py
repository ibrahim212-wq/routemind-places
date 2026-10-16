"""Publish a built index as a GitHub Release of the public data repository.

    PLACES_PUBLISH_TOKEN=… python -m tools.place_index.publish --index <dir> --repo <owner>/routemind-places
                                                             [--keep 3] [--dry-run]

WHY A RELEASE — release assets are free, public, served from GitHub's CDN, «no limit on the total
size of a release, nor bandwidth usage» (each file < 2 GiB, ≤ 1000 per release), and need no card
and no server. The phone reads

    https://github.com/<repo>/releases/latest/download/manifest.json

(GitHub redirects `latest` to the newest published, non-draft release) and every file the manifest
names under `base` (the release's own download prefix), checking each file's sha256.

ATOMIC — the release is created as a DRAFT, every tile and the licence bundle are uploaded, the
manifest goes LAST, and only then is the release published and marked latest: a phone never sees
a manifest whose tiles are not there. Older releases beyond --keep are deleted with their tags
(a phone holding a pruned version keeps its cached tiles and moves to the new manifest at its next
check; tiles are content-addressed by sha256, so an unchanged tile is never downloaded twice).

The token: a fine-grained personal access token with «Contents: Read and write» on the data
repository ONLY (docs/place-search-2026-10.md §9 has the clicks). An empty repository gets a README
first (a release needs a commit to tag).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TAG_PREFIX = "places-"

README = """# RouteMind place index

Open place data for Egypt, built weekly from OpenStreetMap, Overture Maps, Foursquare OS Places,
Wikidata and GeoNames, as the static SQLite tiles the RouteMind app searches on the phone.

The data is in this repository's **Releases** (one release per build; `manifest.json` lists every
file with its bounding box and sha256). Licence: ODbL 1.0 — see `NOTICE.md` and `LICENSES/` in
each release.
"""


class Gh:
    def __init__(self, token: str, repo: str, dry: bool = False):
        self.token, self.repo, self.dry = token, repo, dry

    def call(self, method: str, url: str, body=None, data: bytes | None = None, ctype: str | None = None,
             ok=(200, 201, 204), tries: int = 5):
        if not url.startswith("http"):
            url = API + url
        hdr = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "routemind-place-index"}
        if body is not None:
            data = json.dumps(body).encode()
            ctype = "application/json"
        if ctype:
            hdr["Content-Type"] = ctype
        wait = 2
        for k in range(tries):
            req = urllib.request.Request(url, data=data, method=method, headers=hdr)
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    raw = r.read()
                    return r.status, (json.loads(raw) if raw and r.headers.get_content_type() == "application/json"
                                      else None)
            except urllib.error.HTTPError as e:
                raw = e.read()
                if e.code in ok:
                    return e.code, None
                if e.code in (404, 409, 422) or k == tries - 1:
                    return e.code, (json.loads(raw) if raw[:1] in (b"{", b"[") else {"message": raw[:300].decode()})
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if k == tries - 1:
                    raise
            time.sleep(wait)
            wait *= 2
        raise RuntimeError(f"{method} {url} failed")

    def need(self, method, url, **kw):
        code, js = self.call(method, url, **kw)
        if code not in (200, 201, 204):
            raise SystemExit(f"[publish] {method} {url} → {code} {js}")
        return js


def ensure_commit(gh: Gh) -> None:
    code, repo = gh.call("GET", f"/repos/{gh.repo}")
    if code != 200:
        raise SystemExit(f"[publish] repository {gh.repo} is not reachable with this token ({code}: {repo}). "
                         "Create it (public) and give the token Contents read/write on it.")
    if repo.get("private"):
        raise SystemExit(f"[publish] {gh.repo} is private — phones cannot download from it. Make it public.")
    code, _ = gh.call("GET", f"/repos/{gh.repo}/commits?per_page=1")
    if code == 409:  # empty repository
        print("[publish] empty repository: adding README.md", flush=True)
        if not gh.dry:
            gh.need("PUT", f"/repos/{gh.repo}/contents/README.md",
                    body={"message": "README", "content": base64.b64encode(README.encode()).decode()})


def free_tag(gh: Gh, version: str) -> str:
    tag, n = TAG_PREFIX + version, 1
    while gh.call("GET", f"/repos/{gh.repo}/git/ref/tags/{urllib.parse.quote(tag)}")[0] == 200:
        n += 1
        tag = f"{TAG_PREFIX}{version}.{n}"
    return tag


def files_of(index_dir: str, man: dict) -> list[tuple[str, str, str]]:
    """(asset name, local path, content type), manifest excluded — it goes last."""
    out = [(man["national"]["file"], os.path.join(index_dir, man["national"]["file"]), "application/gzip")]
    out += [(t["file"], os.path.join(index_dir, t["file"]), "application/gzip") for t in man["tiles"]]
    for fn, ct in (("NOTICE.md", "text/markdown"), ("attribution.json", "application/json"),
                   ("build_report.json", "application/json"), ("bench.json", "application/json")):
        if os.path.exists(os.path.join(index_dir, fn)):
            out.append((fn, os.path.join(index_dir, fn), ct))
    lic = os.path.join(index_dir, "LICENSES")
    # an index without its licence bundle is never published (ODbL §4.3: the notice travels with the data)
    for need in ("NOTICE.md", "attribution.json", os.path.join("LICENSES", "ODbL-1.0.txt")):
        if not os.path.exists(os.path.join(index_dir, need)):
            raise SystemExit(f"[publish] missing {need} — run tools.place_index.notice first")
    out += [("LICENSE-" + fn, os.path.join(lic, fn), "text/plain") for fn in sorted(os.listdir(lic))]
    for name, path, _ in out:
        if not os.path.exists(path):
            raise SystemExit(f"[publish] missing {path}")
    return out


def upload(gh: Gh, rel: dict, name: str, path: str, ctype: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    url = f"{UPLOADS}/repos/{gh.repo}/releases/{rel['id']}/assets?name={urllib.parse.quote(name)}"
    if gh.dry:
        return
    for k in range(4):
        code, js = gh.call("POST", url, data=data, ctype=ctype)
        if code in (200, 201):
            return
        # a half-finished upload leaves a broken asset of the same name: remove it and retry
        for a in gh.need("GET", f"/repos/{gh.repo}/releases/{rel['id']}/assets?per_page=100"):
            if a["name"] == name:
                gh.call("DELETE", f"/repos/{gh.repo}/releases/assets/{a['id']}")
        time.sleep(2 ** (k + 1))
    raise SystemExit(f"[publish] upload of {name} failed: {code} {js}")


def prune(gh: Gh, keep: int) -> None:
    rels = gh.need("GET", f"/repos/{gh.repo}/releases?per_page=100") or []
    ours = [r for r in rels if r["tag_name"].startswith(TAG_PREFIX) and not r["draft"]]
    ours.sort(key=lambda r: r["published_at"] or "", reverse=True)
    for r in ours[keep:]:
        print("[publish] pruning", r["tag_name"], flush=True)
        if not gh.dry:
            gh.call("DELETE", f"/repos/{gh.repo}/releases/{r['id']}")
            gh.call("DELETE", f"/repos/{gh.repo}/git/refs/tags/{urllib.parse.quote(r['tag_name'])}")
    for r in rels:  # drafts a failed run left behind
        if r["draft"] and r["tag_name"].startswith(TAG_PREFIX):
            if not gh.dry:
                gh.call("DELETE", f"/repos/{gh.repo}/releases/{r['id']}")


def publish(index_dir: str, repo: str, token: str, keep: int = 3, dry: bool = False, notes: str = "") -> str:
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    gh = Gh(token, repo, dry)
    ensure_commit(gh)
    prune(gh, 10_000)  # drafts only (keep everything published until the new one is live)
    tag = free_tag(gh, man["version"])
    man["tag"] = tag
    man["base"] = f"https://github.com/{repo}/releases/download/{tag}/"
    files = files_of(index_dir, man)
    tot = man.get("totals", {})
    body = (f"Place index {man['version']} — {tot.get('places', '?')} places, {tot.get('files', '?')} files, "
            f"{round(tot.get('bytes', 0) / 1e6, 1)} MB gzip. Licence ODbL 1.0 (NOTICE.md).\n\n{notes}").strip()
    print(f"[publish] {repo} {tag}: {len(files) + 1} assets", flush=True)
    rel = {"id": 0}
    if not dry:
        rel = gh.need("POST", f"/repos/{repo}/releases",
                      body={"tag_name": tag, "name": f"Place index {man['version']}", "body": body, "draft": True})
    for i, (name, path, ct) in enumerate(files):
        upload(gh, rel, name, path, ct)
        if i % 20 == 0:
            print(f"[publish] {i + 1}/{len(files)} {name}", flush=True)
    data = json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8")
    mpath = os.path.join(index_dir, "manifest.release.json")
    with open(mpath, "wb") as f:
        f.write(data)
    upload(gh, rel, "manifest.json", mpath, "application/json")
    if not dry:
        gh.need("PATCH", f"/repos/{repo}/releases/{rel['id']}", body={"draft": False, "make_latest": "true"})
    prune(gh, keep)
    print(f"[publish] live: https://github.com/{repo}/releases/latest/download/manifest.json → {tag}", flush=True)
    return tag


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--repo", default=os.environ.get("PLACES_REPO"))
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--notes-file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    token = os.environ.get("PLACES_PUBLISH_TOKEN") or os.environ.get("GH_TOKEN")
    if not a.repo or (not token and not a.dry_run):
        sys.exit("[publish] need --repo (or PLACES_REPO) and PLACES_PUBLISH_TOKEN")
    notes = open(a.notes_file, encoding="utf-8").read() if a.notes_file else ""
    publish(a.index, a.repo, token or "", a.keep, a.dry_run, notes)


if __name__ == "__main__":
    main()
