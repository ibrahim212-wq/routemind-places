"""How complete is the index? Capture-recapture over the independent sources, per governorate and kind of place.

    python -m tools.place_index.bench.coverage --rows <rows.jsonl | index dir> --out <dir>

Every source is treated as an independent "capture" of the real population of places. A merged place's `srcs` says
which sources caught it, so overlaps come straight from the index, no fuzzy matching here.

  lp     Lincoln-Petersen with Chapman's correction on the two lists least likely to share a method: OSM (mappers)
         against the pages (Meta + Foursquare + Microsoft + others), N = (a+1)(b+1)/(m+1) - 1.
  chao   Chao's lower bound from capture frequencies, N = S + f1^2 / 2 f2.

Honest limits, printed with the numbers:
  * Positive dependence between lists (a famous place is in all of them) makes both estimates LOW, so coverage reads
    HIGH. Places no open source could ever catch (a shop with no page and no mapper) are invisible to the method.
  * A pair the merge failed to match (different script, moved pin) makes the overlap small, so the estimate reads HIGH
    and coverage LOW.
So the output is an estimate of what the sources' world contains, not a census: `anchors.py` holds the published
counts of real places to compare it with.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict

OSM, ATP, FSQ, MS, META, OVX, DIV, WD, GN = 1, 2, 4, 8, 16, 32, 64, 128, 256
PAGES = META | FSQ | MS | OVX | ATP

KINDS: dict[str, set[str]] = {
    "restaurants": {"restaurant", "koshary", "grill", "seafood", "pizza", "burger", "fast_food", "foul_taameya", "sweets", "bakery",
                    "butcher"},
    "cafes": {"cafe", "ahwa", "juice_bar", "ice_cream"},
    "educational_centers": {"institute", "kindergarten", "language_school", "tutoring"},
    "clinics": {"clinic", "dentist", "medical_lab", "radiology", "physiotherapy", "veterinary", "optician"},
    "pharmacies": {"pharmacy"},
    "shops": {"clothing_store", "supermarket", "mobile_shop", "furniture_store", "electronics_store", "home_goods_store", "hardware_store",
              "auto_parts", "cosmetics", "shoe_store", "bookshop", "jewelry_store", "florist", "gift_shop", "pet_store", "print_shop", "mall",
              "greengrocer", "market", "appliances", "toys", "perfume", "fabric", "tyre_shop", "spices", "sports_store"},
    "services": {"car_repair", "barber", "beauty_salon", "bank", "atm", "gas_station", "car_wash", "hotel", "gym", "spa", "real_estate_agent",
                 "travel_agency", "laundry", "lawyer", "shipping", "car_dealer", "oil_change", "plumber", "electrician", "carpenter", "tailor",
                 "exchange", "towing", "parking", "car_rental", "accountant"},
    "government": {"government_office", "police", "post_office", "courthouse", "traffic_department", "civil_registry", "notary", "embassy",
                   "fire_station", "telecom_exchange", "supply_office", "tax_office"},
    "worship": {"mosque", "church"},
    "education": {"school", "university"},
    "hospitals": {"hospital"},
}
KIND_OF = {s: k for k, v in KINDS.items() for s in v}
GENERIC = "other"


def chapman(a: int, b: int, m: int) -> float:
    return (a + 1) * (b + 1) / (m + 1) - 1


def chao(s: int, f1: int, f2: int) -> float:
    return s + (f1 * f1 / (2 * f2) if f2 else f1 * (f1 - 1) / 2)


def rows_of(path: str):
    if os.path.isdir(path):
        seen = set()
        for fn in sorted(glob.glob(os.path.join(path, "*.sqlite"))):
            con = sqlite3.connect(fn)
            con.row_factory = sqlite3.Row
            for r in con.execute("select pid, kind, scat, cat, lat, lng, gov, srcs, conf, name_ar, name_en from place"):
                if r["pid"] not in seen:
                    seen.add(r["pid"])
                    yield dict(r)
            con.close()
    else:
        with open(path, encoding="utf8") as f:
            for line in f:
                yield json.loads(line)


class Cell:
    __slots__ = ("s", "a", "b", "m", "freq")

    def __init__(self):
        self.s = self.a = self.b = self.m = 0
        self.freq = Counter()

    def add(self, srcs: int) -> None:
        bits = srcs & (OSM | ATP | FSQ | MS | META | OVX | WD | GN)
        self.s += 1
        self.freq[bin(bits).count("1")] += 1
        in_a, in_b = bool(bits & OSM), bool(bits & PAGES)
        self.a += in_a
        self.b += in_b
        self.m += in_a and in_b

    def report(self) -> dict:
        lp = chapman(self.a, self.b, self.m) if self.a and self.b else None
        ch = chao(self.s, self.freq[1], self.freq[2])
        # the index also holds places caught by neither list of the pair (Wikidata, GeoNames only): add them to LP's world
        rest = self.s - (self.a + self.b - self.m)
        lp_n = lp + rest if lp is not None else None
        best = max(x for x in (lp_n, ch) if x is not None)
        return {"have": self.s, "osm": self.a, "pages": self.b, "both": self.m, "f1": self.freq[1], "f2": self.freq[2],
                "n_lp": None if lp_n is None else round(lp_n), "n_chao": round(ch),
                "cov_lp": None if not lp_n else round(self.s / lp_n, 3), "cov_chao": round(self.s / ch, 3) if ch else None,
                "cov": round(min(1.0, self.s / best), 3) if best else None}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    overall, by_kind, by_gov, by_both = Cell(), defaultdict(Cell), defaultdict(Cell), defaultdict(Cell)
    streets = Counter()
    for r in rows_of(a.rows):
        if r["kind"] == 2:
            streets[r.get("gov") or "?"] += 1
        if r["kind"] != 0:
            continue
        k = KIND_OF.get(r["scat"] or "", GENERIC)
        g = r.get("gov") or "?"
        overall.add(r["srcs"])
        by_kind[k].add(r["srcs"])
        by_gov[g].add(r["srcs"])
        by_both[f"{g}|{k}"].add(r["srcs"])
    out = {"overall": overall.report(), "by_kind": {k: v.report() for k, v in sorted(by_kind.items())},
           "by_gov": {k: v.report() for k, v in sorted(by_gov.items())},
           "by_gov_kind": {k: v.report() for k, v in sorted(by_both.items())}, "street_pieces": dict(streets)}
    with open(os.path.join(a.out, "coverage.json"), "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    head = f"{'':24}{'have':>8}{'osm':>8}{'pages':>8}{'both':>7}{'N_lp':>10}{'N_chao':>10}{'cov_lp':>8}{'cov_ch':>8}"
    print(head)

    def line(k, c):
        print(f"{k:24}{c['have']:>8}{c['osm']:>8}{c['pages']:>8}{c['both']:>7}{str(c['n_lp']):>10}{c['n_chao']:>10}"
              f"{str(c['cov_lp']):>8}{str(c['cov_chao']):>8}")
    line("ALL", out["overall"])
    for k, c in out["by_kind"].items():
        line(k, c)
    print()
    for k, c in sorted(out["by_gov"].items(), key=lambda kv: -kv[1]["have"]):
        line(k, c)


if __name__ == "__main__":
    main()
