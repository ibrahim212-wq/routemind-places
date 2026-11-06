"""What a red-team run means once the data and the judge's own errors are separated from the engine's.

    python -m tools.place_index.bench.redteam_fair --results <dir>/results_3km.json --rows <rows.jsonl> [--out <file>]

The red team's targets were written from knowledge, without the index or a map: their coordinates are guesses and some of the
places do not exist where it says. So beside the score as judged, for every item:

  exists   the index holds a right row under the STRICT judge (anywhere on the phone or not). An item with none is a DATA gap,
           whatever the engine does: the honest measure of the engine is on items where a right row exists.
  loose    a place / street target is right by name within LOOSE_PLACE_KM / LOOSE_STREET_KM of the guessed point, not r_km
           (the guess is often kilometres off: «قسم شرطة قصر النيل» 1.1 km from where it was placed). Nothing else is relaxed.
  ideal    for intent items: right rows that exist within the judge's radius, capped at 5. P@5 / (ideal / 5) is what the engine
           could reach with this index; an item with ideal = 0 is a data gap.

Prints sums only, so it may be run on every split (the held split's failures are never listed anywhere)."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import zlib
from collections import defaultdict

from .. import engine as E
from .. import textnorm as tn
from .run import names_match

HERE = os.path.dirname(os.path.abspath(__file__))
LOOSE_PLACE_KM = 15.0
LOOSE_STREET_KM = 8.0
CELL = 0.1


def _items() -> dict:
    out = {}
    for f in glob.glob(os.path.join(HERE, "redteam", "*.json")):
        d = json.load(open(f, encoding="utf8"))
        for i, it in enumerate(d["items"]):
            it["_anchor"] = d["anchors"].get(it["at"])
            out[(d["gov"], i)] = it
    return out


class Rows:
    def __init__(self, path: str):
        self.cells: dict = defaultdict(list)
        with open(path, encoding="utf8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("kind") == 1:
                    continue
                self.cells[(int(r["lat"] / CELL), int(r["lng"] / CELL))].append(
                    {"lat": r["lat"], "lng": r["lng"], "kind": r["kind"], "scat": r.get("scat"), "name_ar": r.get("name_ar"),
                     "name_en": r.get("name_en"), "alt": r.get("alt")})

    def near(self, lat: float, lng: float, km: float):
        n = int(km / 9.5) + 1
        c = (int(lat / CELL), int(lng / CELL))
        for a in range(c[0] - n, c[0] + n + 1):
            for b in range(c[1] - n, c[1] + n + 1):
                for r in self.cells.get((a, b), ()):
                    if E.haversine(lat, lng, r["lat"], r["lng"]) <= km * 1000:
                        yield r


def _right_rows(it: dict, rows: Rows, cap: int) -> int:
    t = it["t"]
    n = 0
    if t in ("place", "street"):
        lat, lng = it["near"]
        for r in rows.near(lat, lng, it["r_km"]):
            if (r["kind"] == 2) == (t == "street") and names_match(it["names"], r):
                return 1
        return 0
    if not it.get("_anchor"):
        return 0
    lat, lng = it["_anchor"]
    if t == "chain":
        for r in rows.near(lat, lng, it["km"]):
            if r["kind"] == 0 and names_match(it["names"], r):
                return 1
        return 0
    scats = set(it.get("scats", ()))
    for r in rows.near(lat, lng, it["km"]):
        if r["scat"] in scats or any(names_match([w], r) for w in it.get("words", ())):
            n += 1
            if n >= cap:
                break
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf8")
    items = _items()
    res = json.load(open(a.results, encoding="utf8"))
    rows = Rows(a.rows)
    S: dict = defaultdict(lambda: defaultdict(float))
    per = []
    for r in res:
        it = items.get((r["gov"], r["i"]))
        if it is None:
            continue
        split = "dev" if zlib.crc32(tn.normalize(r["q"]).encode("utf8")) % 10 < 7 else "held"
        t = r["t"]
        for key in (t, f"{t}:{split}", "ALL_NAMED" if t in ("place", "chain", "street") else "ALL_INTENT"):
            S[key]["n"] += 1
        if t in ("place", "chain", "street"):
            ex = _right_rows(it, rows, 1)
            loose_hit = False
            top = r.get("top") or []
            if t != "chain" and top:
                km = LOOSE_PLACE_KM if t == "place" else LOOSE_STREET_KM
                t0 = top[0]
                row = {"name_ar": t0.get("ar"), "name_en": t0.get("en")}
                # the row's distance is from the user: the guess is near the anchor, so the distance from the anchor bounds it
                if (t0.get("k") == 2) == (t == "street") and names_match(it["names"], row) and t0.get("d", 1e12) <= (km + it["r_km"]) * 1000:
                    loose_hit = True
            h1 = r["rank"] == 1
            for key in (t, f"{t}:{split}", "ALL_NAMED"):
                d = S[key]
                d["h1"] += h1
                d["h3"] += bool(r["rank"] and r["rank"] <= 3)
                d["exists"] += ex
                d["h1_on_exists"] += h1 and ex
                d["h3_on_exists"] += bool(r["rank"] and r["rank"] <= 3 and ex)
                d["h1_loose"] += h1 or loose_hit
                pre3 = (r.get("pre") or {}).get("3")
                pd = r.get("pre_d")
                d["p3_on_exists"] += (pre3 == 1) and ex
                d["pd_on_exists"] += (pd == 1 if not isinstance(pd, dict) else pd.get("h1") == 1) and ex
        else:
            ideal = _right_rows(it, rows, 5)
            for key in (t, f"{t}:{split}", "ALL_INTENT"):
                d = S[key]
                d["p5"] += r["p5"]
                d["with_data"] += ideal > 0
                if ideal > 0:
                    d["p5_of_ideal"] += min(1.0, r["p5"] * 5 / ideal)
                d["ideal5"] += ideal >= 5
                if ideal >= 5:
                    d["p5_where_5"] += r["p5"]
    out = {}
    for k, d in sorted(S.items()):
        n = d["n"] or 1
        o = {"n": int(d["n"])}
        if "h1" in d:
            ex = d["exists"] or 1
            o.update(h1=round(d["h1"] / n, 3), h3=round(d["h3"] / n, 3), h1_loose=round(d["h1_loose"] / n, 3),
                     exists=round(d["exists"] / n, 3), h1_on_exists=round(d["h1_on_exists"] / ex, 3),
                     h3_on_exists=round(d["h3_on_exists"] / ex, 3), p3_on_exists=round(d["p3_on_exists"] / ex, 3),
                     pd_on_exists=round(d["pd_on_exists"] / ex, 3))
        else:
            wd = d["with_data"] or 1
            i5 = d["ideal5"] or 1
            o.update(p5=round(d["p5"] / n, 3), with_data=round(d["with_data"] / n, 3), p5_of_ideal=round(d["p5_of_ideal"] / wd, 3),
                     has5=round(d["ideal5"] / n, 3), p5_where_5=round(d["p5_where_5"] / i5, 3))
        out[k] = o
        print(k, o)
    if a.out:
        json.dump(out, open(a.out, "w", encoding="utf8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
