# RouteMind place index

Open place data for Egypt — shops, services, landmarks, areas and streets — built every week from
OpenStreetMap, Overture Maps, Foursquare OS Places, Wikidata and GeoNames, and published as the
static SQLite tiles the [RouteMind](https://github.com/ibrahim212-wq) app searches on the phone.

## Where the data is

Every build is a **release** of this repository (tag `places-<YYYY-MM-DD>`). The newest one is always at

    https://github.com/ibrahim212-wq/routemind-places/releases/latest/download/manifest.json

`manifest.json` lists every file with its bounding box, place count and sha256, and `base` — the
release's own download prefix. Each release holds:

| File | What |
|---|---|
| `national.sqlite.gz` | every area, every prominent place and every branch of a chain (searchable from anywhere) |
| `t*.sqlite.gz` | the tiles of an adaptive quadtree (≤ 7,000 places each) |
| `manifest.json` | the index of the release (uploaded last: a phone never sees a manifest whose files are missing) |
| `NOTICE.md`, `attribution.json`, `LICENSE-*` | the licence bundle |
| `bench.json`, `build_report.json` | the 334-query benchmark of this build and the build's numbers |

The newest three releases are kept.

## Licence

The index is a database under the **Open Database License (ODbL) 1.0**; each release's `NOTICE.md`
lists every source, its licence and what was changed. © OpenStreetMap contributors; Overture Maps
Foundation (CDLA-Permissive-2.0); Foursquare OS Places (Apache-2.0); Wikidata (CC0); GeoNames (CC BY 4.0).

## How it is built

`.github/workflows/place-index.yml` runs every Monday at 02:17 UTC on GitHub's free runners:
fetch (streamed, cut to Egypt) → merge and deduplicate → tiles → licence bundle → **release gate**
(the build is published only if the benchmark is not worse than the previous release) → release.
`builds.jsonl` has one line per run.

`pipeline/` is the code that does it — a generated, byte-exact copy of the pipeline in the RouteMind
app repository (see `pipeline/README.md`; `pipeline/SOURCE.json` names the commit). To build it yourself:

    cd pipeline
    pip install -r tools/place_index/requirements.txt
    python -m tools.place_index.weekly --work /tmp/place-index
