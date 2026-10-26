# -*- coding: utf-8 -*-
"""The bench's CHAIN queries re-typed the way people type (bench/parity.py's groups) → a fixture the Dart search layer
is measured on (`test/search_chain_typing_test.dart`): the app's own chain row comes from the lexicon in Dart while the
user types, not from the engine, so the engine bench alone under-reports what the driver sees.

    python -m tools.place_index.bench.chain_typing_export [--out test/fixtures/search_chain_typing.json]

Deterministic: the same derivation as the parity run (parity.derive), no index needed.
"""
import argparse
import io
import json
import os

from tools.place_index.bench import parity as P
from tools.place_index.bench import queries as Q

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def others():
    """Every non-chain query as written (places, categories): a typo-tolerant chain row must not answer these."""
    return [{"q": q["q"], "lat": Q.ANCHORS[q["at"]][0], "lng": Q.ANCHORS[q["at"]][1]}
            for q in Q.Q if "brand" not in q]


def rows():
    out = []
    for gi, q in enumerate(Q.Q):
        if "brand" not in q:
            continue
        lat, lng, _ = Q.ANCHORS[q["at"]]
        for grp, text in P.derive(q, gi):
            if text.strip():
                out.append({"group": grp, "q": text, "orig": q["q"], "names": q["brand"]["names"],
                            "lat": lat, "lng": lng})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(APP, "test", "fixtures", "search_chain_typing.json"))
    a = ap.parse_args(argv)
    rs, ot = rows(), others()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    io.open(a.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"chains": rs, "others": ot}, ensure_ascii=False, indent=0) + "\n")
    print("%d chain rows, %d other queries -> %s" % (len(rs), len(ot), a.out))


if __name__ == "__main__":
    main()
