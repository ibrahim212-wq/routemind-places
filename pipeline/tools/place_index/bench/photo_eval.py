"""Measure photo matching by LOOKING at the photos (docs/place-photos-2026-10.md §5).

    python -m tools.place_index.bench.photo_eval sheets --matches <matches.json> --out <dir> [--n 160] [--seed 7]
    python -m tools.place_index.bench.photo_eval score  --matches <matches.json> --labels <labels.json>

`matches.json` is a list of {"id", "name", "cat", "city", "how", "url"} — one photo the pipeline chose for
one place (the url a thumbnail). `sheets` draws a stratified sample (per `how` × category group) into
numbered contact sheets of 12 and writes `<out>/sample.json` (number → entry) and `<out>/labels.json`
(number → "?"). A person (or the agent with an image reader) replaces each "?" with:

    ok      the photo shows the place (its front, its inside, its food — what Google would show)
    wrong   another place, the street, the district, a sign, an event that hides the place
    unclear cannot tell from the photo

`score` prints precision = ok / (ok + wrong) per source and category group, and the unclear count.
Desk tool: needs Pillow; downloads go under --out (keep it outside the repository: G:/grad_all/.p5work).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import time
import urllib.request
from collections import defaultdict

UA = "RouteMind-place-index/1.0 (photo evaluation; grad.smart.traffic@gmail.com)"

from ..photos import group_of  # noqa: E402 — the strata are the matcher's own groups


def _fetch(url: str) -> bytes | None:
    for k in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001 — a missing thumbnail is a skipped sample, not a crash
            time.sleep(2 + 3 * k)
    return None


def sheets(matches: str, out: str, n: int, seed: int) -> None:
    from PIL import Image, ImageDraw, ImageFont
    rows = json.load(open(matches, encoding="utf-8"))
    strata = defaultdict(list)
    for r in rows:
        strata[(r.get("how"), group_of(r.get("cat")))].append(r)
    rnd = random.Random(seed)
    for v in strata.values():
        rnd.shuffle(v)
    pick = []
    while len(pick) < n and any(strata.values()):   # round-robin over the strata: small groups are seen too
        for k in sorted(strata, key=str):
            if strata[k] and len(pick) < n:
                pick.append(strata[k].pop())
    os.makedirs(out, exist_ok=True)
    font = ImageFont.load_default(size=40) if hasattr(ImageFont, "load_default") else None
    sample, labels = {}, {}
    cells = []
    for i, r in enumerate(pick, start=1):
        data = _fetch(r["url"])
        time.sleep(0.4)
        if not data:
            continue
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        im.thumbnail((330, 330))
        cell = Image.new("RGB", (340, 340), (30, 30, 30))
        cell.paste(im, ((340 - im.width) // 2, (340 - im.height) // 2))
        d = ImageDraw.Draw(cell)
        d.rectangle((0, 0, 70, 48), fill=(255, 220, 0))
        d.text((6, 2), str(i), fill=(0, 0, 0), font=font)
        cells.append((i, cell))
        sample[str(i)] = r
        labels[str(i)] = "?"
    for s in range(0, len(cells), 12):
        sheet = Image.new("RGB", (4 * 340, 3 * 340), (0, 0, 0))
        for k, (_, c) in enumerate(cells[s:s + 12]):
            sheet.paste(c, ((k % 4) * 340, (k // 4) * 340))
        sheet.save(os.path.join(out, f"sheet_{s // 12 + 1:02d}.jpg"), quality=82)
    json.dump(sample, open(os.path.join(out, "sample.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not os.path.exists(os.path.join(out, "labels.json")):
        json.dump(labels, open(os.path.join(out, "labels.json"), "w", encoding="utf-8"), indent=0)
    print(f"{len(cells)} photos on {(len(cells) + 11) // 12} sheets in {out}")


def score(matches_sample: str, labels: str) -> dict:
    sample = json.load(open(matches_sample, encoding="utf-8"))
    lab = json.load(open(labels, encoding="utf-8"))
    t = defaultdict(lambda: defaultdict(int))
    for k, r in sample.items():
        v = lab.get(k, "?")
        for key in ("ALL", f"how:{r.get('how')}", f"group:{group_of(r.get('cat'))}"):
            t[key][v] += 1
    out = {}
    for key in sorted(t):
        c = t[key]
        judged = c["ok"] + c["wrong"]
        out[key] = {"n": sum(c.values()), "ok": c["ok"], "wrong": c["wrong"], "unclear": c["unclear"],
                    "precision": round(c["ok"] / judged, 3) if judged else None}
        print(f"{key:18} n={out[key]['n']:4}  ok={c['ok']:4}  wrong={c['wrong']:3}  unclear={c['unclear']:3}  "
              f"precision={out[key]['precision']}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("sheets")
    a.add_argument("--matches", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--n", type=int, default=160)
    a.add_argument("--seed", type=int, default=7)
    b = sub.add_parser("score")
    b.add_argument("--matches", required=True, help="the sample.json `sheets` wrote")
    b.add_argument("--labels", required=True)
    x = ap.parse_args(argv)
    if x.cmd == "sheets":
        sheets(x.matches, x.out, x.n, x.seed)
    else:
        score(x.matches, x.labels)


if __name__ == "__main__":
    main()
