"""RouteMind's own place index (docs/place-search-2026-10.md).

The pipeline that turns open place data (Overture Places, OpenStreetMap, Foursquare OS Places,
Wikidata, GeoNames) into the static SQLite tiles the phone searches, and the reference copy of the
on-device search engine that reads them. The engine is mirrored line for line in
android/.../places/PlaceSearch*.kt and ios/Runner/Places/PlaceSearch*.swift and held to this copy by
tool/place_search_parity.py.

    python -m tools.place_index.build --out <dir>        # the whole pipeline
    python -m tools.place_index.bench.run --index <dir>  # the 150+ query benchmark + review sheet
"""
