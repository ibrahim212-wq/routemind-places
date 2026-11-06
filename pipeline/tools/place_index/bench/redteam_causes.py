"""Why did a red-team query miss? Each named miss gets one cause, so a round attacks the biggest class.

    python -m tools.place_index.bench.redteam_causes --rows <rows.jsonl> --run <dir> [--phone 3km] [--ceiling all]

  data     no row in the index carries an accepted name within the judge's radius: open data does not have it (or the judge is wrong)
  ranking  the phone has the right row in its file set and ranks it below 5 (or it is reached only with every tile: see reach)
  reach    every tile on the phone finds it where the phone's own files do not
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict

from .. import engine as E
from .run import names_match

CELL = 0.05


def load_rows(path: str) -> dict:
    grid = defaultdict(list)
    with open(path, encoding="utf8") as f:
        for line in f:
            r = json.loads(line)
            grid[(int(r["lat"] // CELL), int(r["lng"] // CELL))].append(
                {"name_ar": r["name_ar"], "name_en": r["name_en"], "alt": r["alt"], "lat": r["lat"], "lng": r["lng"], "kind": r["kind"]})
    return grid


def exists(grid: dict, names: list[str], lat: float, lng: float, r_m: float, kind) -> bool:
    reach = int(math.ceil(r_m / 111000.0 / CELL)) + 1
    ci, cj = int(lat // CELL), int(lng // CELL)
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            for row in grid.get((ci + di, cj + dj), ()):
                if kind is not None and (row["kind"] == 2) != kind:
                    continue
                if E.haversine(lat, lng, row["lat"], row["lng"]) <= r_m and names_match(names, row):
                    return True
    return False


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--phone", default="3km")
    ap.add_argument("--ceiling", default="all")
    a = ap.parse_args(argv)
    phone = json.load(open(os.path.join(a.run, f"results_{a.phone}.json"), encoding="utf8"))
    ceil_path = os.path.join(a.run, f"results_{a.ceiling}.json")
    ceil = {(r["gov"], r["i"]): r for r in json.load(open(ceil_path, encoding="utf8"))} if os.path.exists(ceil_path) else {}
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "redteam")
    items = {}
    anchors = {}
    for fn in os.listdir(base):
        if fn.endswith(".json"):
            d = json.load(open(os.path.join(base, fn), encoding="utf8"))
            g = fn[:-5]
            anchors[g] = d["anchors"]
            for i, it in enumerate(d["items"]):
                items[(g, i)] = it
    grid = load_rows(a.rows)
    causes = Counter()
    by_type = defaultdict(Counter)
    out = []
    for r in phone:
        if r["t"] not in ("place", "chain", "street"):
            continue
        it = items[(r["gov"], r["i"])]
        if it["t"] == "chain":
            lat, lng = anchors[r["gov"]][it["at"]]
            have = exists(grid, it["names"], lat, lng, it["km"] * 1000, False)
        else:
            have = exists(grid, it["names"], it["near"][0], it["near"][1], it["r_km"] * 1000, it["t"] == "street")
        if r["rank"] == 1:
            c = "hit1"
        elif not have:
            c = "data"
        else:
            cr = ceil.get((r["gov"], r["i"]))
            if cr is not None and cr["rank"] == 1:
                c = "reach"
            else:
                c = "ranking"
        causes[c] += 1
        by_type[r["t"]][c] += 1
        out.append({**{k: r[k] for k in ("gov", "t", "q", "at", "rank", "style")}, "cause": c, "top": r["top"][:3], "pre": r.get("pre")})
    print("causes", dict(causes), {k: dict(v) for k, v in by_type.items()})
    # intelligence is judged on what the index has; what it lacks is the coverage criterion's
    have = [o for o in out if o["cause"] != "data"]

    def rate(rows, f, k):
        return round(sum(1 for r in rows if f(r) and f(r) <= k) / max(1, len(rows)), 3)
    print("targets the index has:", len(have), "of", len(out),
          {"h1": rate(have, lambda r: r["rank"], 1), "h3": rate(have, lambda r: r["rank"], 3),
           **{f"p{L}_h{k}": rate([o for o in have if o.get("pre")], lambda r, L=L: r["pre"][str(L)], k) for L in (2, 3, 4, 6) for k in (1, 3)}})
    with open(os.path.join(a.run, f"causes_{a.phone}.json"), "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
