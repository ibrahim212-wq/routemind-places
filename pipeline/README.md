# pipeline/ — a generated copy. Do not edit here.

This directory is a byte-exact copy of the place-index pipeline from the RouteMind app repository
(`cairoWay/tools/place_index`, `cairoWay/tools/__init__.py`, `cairoWay/assets/search/egypt_lexicon.json`).
`SOURCE.json` names the app commit it came from and every file's sha256. The weekly workflow
(`.github/workflows/place-index.yml`) refreshes it from the app repository before every build, and
`python tools/place_index/mirror.py push` in the app repository does the same after a change.

    cd pipeline
    pip install -r tools/place_index/requirements.txt
    python -m tools.place_index.weekly --work /tmp/place-index            # build + gate (no publish)

Licence of the code: the same terms as this repository's README. The data: ODbL 1.0 (each release's NOTICE.md).
