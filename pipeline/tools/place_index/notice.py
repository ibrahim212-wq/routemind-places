"""The licence bundle that ships with every index release (docs/place-search-2026-10.md §3).

    python -m tools.place_index.notice --index <dir>      # writes NOTICE.md, attribution.json, LICENSES/

The index is ONE database made from several open datasets, so it is an ODbL 1.0 Derivative
Database of OpenStreetMap (ODbL 4.4 / 4.5a: a database that contains OSM data, extracted or
merged, stays ODbL) and carries every other source's notice with it:

  OpenStreetMap          ODbL 1.0         «© OpenStreetMap contributors», the database offered
                                          under the ODbL (this release IS the database — §4.6)
  Overture Maps Places   CDLA-Permissive-2.0   the licence text with the data (§2.1)
  Overture divisions     ODbL 1.0 (OSM-derived) — counted with OpenStreetMap
  Foursquare OS Places   Apache-2.0       the licence + Foursquare's NOTICE.txt in full (§4(a), (d)),
                                          a notice of our changes (§4(b))
  Wikidata               CC0 1.0          no condition; credited anyway
  GeoNames               CC BY 4.0        attribution + licence link + «changes were made»

The files go next to the tiles in the release; the app's attribution screen
(lib/features/profile/presentation/screens/place_data_attribution_screen.dart) shows the same lines in Arabic and
English and reads `attribution.json` of the index it has, so a source that a build skipped is not
credited and a new one is.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil

from . import records as R

HERE = os.path.dirname(os.path.abspath(__file__))
LIC = os.path.join(HERE, "licenses")

# key = the build's --sources code(s); bits = records.SOURCE_BITS present in a place's `srcs`
SOURCES = [
    {"key": "osm", "bits": [R.SOURCE_BITS[R.SRC_OSM], R.SOURCE_BITS[R.SRC_DIV]],
     "name": "OpenStreetMap", "holder": "© OpenStreetMap contributors",
     "license": "ODbL-1.0", "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
     "url": "https://www.openstreetmap.org/copyright", "file": "ODbL-1.0.txt"},
    {"key": "overture", "bits": [R.SOURCE_BITS[R.SRC_ATP], R.SOURCE_BITS[R.SRC_MS], R.SOURCE_BITS[R.SRC_META],
                                 R.SOURCE_BITS[R.SRC_OVT_OTHER]],
     "name": "Overture Maps Foundation — Places", "holder": "© Overture Maps Foundation",
     "license": "CDLA-Permissive-2.0", "license_url": "https://cdla.dev/permissive-2-0/",
     "url": "https://overturemaps.org", "file": "CDLA-Permissive-2.0.txt"},
    {"key": "fsq", "bits": [R.SOURCE_BITS[R.SRC_FSQ]],
     "name": "Foursquare Open Source Places", "holder": "© 2025 Foursquare Labs, Inc.",
     "license": "Apache-2.0", "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
     "url": "https://opensource.foursquare.com/os-places/", "file": "Apache-2.0.txt",
     "notice": "Foursquare-NOTICE.txt"},
    {"key": "wd", "bits": [R.SOURCE_BITS[R.SRC_WD]],
     "name": "Wikidata", "holder": "Wikidata contributors",
     "license": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
     "url": "https://www.wikidata.org", "file": None},
    {"key": "gn", "bits": [R.SOURCE_BITS[R.SRC_GN]],
     "name": "GeoNames", "holder": "GeoNames (geonames.org)",
     "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
     "url": "https://www.geonames.org", "file": "CC-BY-4.0.txt"},
]

CHANGES = ("RouteMind changed the data: records were filtered to Egypt, normalized (Arabic orthography, "
           "Latin case and diacritics), classified into RouteMind's categories, matched across sources and "
           "merged into one record per place (the field taken from the most reliable source), and written as "
           "searchable SQLite tiles with derived search tokens.")


def present(index_dir: str) -> list[dict]:
    """The sources that really contributed a place to this build (bits seen in the national file + tiles)."""
    import sqlite3
    seen = 0
    for f in os.listdir(index_dir):
        if f.endswith(".sqlite") and (f.startswith("t") or f == "national.sqlite"):
            con = sqlite3.connect(os.path.join(index_dir, f))
            for (b,) in con.execute("SELECT DISTINCT srcs FROM place"):
                seen |= int(b or 0)
            con.close()
    return [s for s in SOURCES if any(seen & b for b in s["bits"])]


def write(index_dir: str, version: str | None = None) -> dict:
    srcs = present(index_dir)
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    version = version or man.get("version")
    lic_dir = os.path.join(index_dir, "LICENSES")
    os.makedirs(lic_dir, exist_ok=True)
    files = {"ODbL-1.0.txt"}
    for s in srcs:
        for k in ("file", "notice"):
            if s.get(k):
                files.add(s[k])
    for fn in sorted(files):
        shutil.copyfile(os.path.join(LIC, fn), os.path.join(lic_dir, fn))
    lines = [
        f"# RouteMind place index {version}",
        "",
        "This database is made available under the Open Database License (ODbL) 1.0: "
        "https://opendatacommons.org/licenses/odbl/1-0/ (full text in LICENSES/ODbL-1.0.txt). "
        "Any rights in individual contents of the database are licensed under the licence of the source "
        "they came from, listed below. The database is this release: every tile and the national file, "
        "downloadable by anyone at the same address the app uses.",
        "",
        "## Sources",
        "",
    ]
    for s in srcs:
        lines.append(f"- **{s['name']}** — {s['holder']}. Licence: {s['license']} ({s['license_url']}). {s['url']}")
    lines += ["", "## Changes", "", CHANGES, ""]
    if any(s["key"] == "fsq" for s in srcs):
        lines += ["## Foursquare NOTICE", "", "The following notice is reproduced in full as Foursquare requires "
                  "(also in LICENSES/Foursquare-NOTICE.txt):", ""]
        with open(os.path.join(LIC, "Foursquare-NOTICE.txt"), encoding="utf-8") as f:
            lines += ["> " + ln if ln.strip() else ">" for ln in f.read().strip().splitlines()]
        lines.append("")
    with open(os.path.join(index_dir, "NOTICE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    att = {"version": version, "license": "ODbL-1.0", "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
           "sources": [{k: s[k] for k in ("key", "name", "holder", "license", "license_url", "url")} for s in srcs],
           "changes": CHANGES}
    with open(os.path.join(index_dir, "attribution.json"), "w", encoding="utf-8") as f:
        json.dump(att, f, ensure_ascii=False, indent=1)
    man["attribution"] = "attribution.json"
    man["notice"] = "NOTICE.md"
    with open(os.path.join(index_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    return att


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--version")
    a = ap.parse_args(argv)
    att = write(a.index, a.version)
    print("[notice]", ", ".join(s["key"] for s in att["sources"]))


if __name__ == "__main__":
    main()
