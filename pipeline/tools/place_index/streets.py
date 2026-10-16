"""Named OSM road segments → searchable streets.

OSM cuts a street into dozens of ways (every bridge, every lane change). Search wants the STREET:
segments with the same normalized name whose vertices come within JOIN_M of each other are one
street (union-find over a vertex grid). A street longer than PIECE_M is cut into pieces, each with
its own pin, so «الطريق الدائري» answers with the stretch near the user rather than a point 40 km
away; the pieces share a `grp` key and the engine shows only the nearest piece of a group.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import merge as M
from . import records as R
from . import sources as S
from . import textnorm as tn

JOIN_M = 120.0
PIECE_M = 2500.0


def _name_key(tags: dict) -> str:
    n = tags.get("name") or tags.get("name:ar") or tags.get("name:en") or ""
    return " ".join(tn.stems(t)[-1] for t in tn.tokens(n))


def _length(pts):
    return sum(R.haversine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1))


def build_streets(segments) -> list[M.Place]:
    groups: dict[str, list] = defaultdict(list)
    for sid, tags, pts in segments:
        cls = S.STREET_HIGHWAY.get(tags.get("highway", ""), "street")
        if cls is None:
            continue  # link roads carry the name of what they connect, not their own
        if tags.get("bridge") == "yes" or "كوبري" in (tags.get("name") or ""):
            cls = "bridge"
        k = _name_key(tags)
        if not k:
            continue
        groups[k].append((sid, tags, pts, cls))
    out: list[M.Place] = []
    cell = JOIN_M / 111000.0
    for k, segs in groups.items():
        parent = list(range(len(segs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        grid: dict[tuple[int, int], int] = {}
        for i, (_, _, pts, _) in enumerate(segs):
            for (la, ln) in pts:
                c = (int(la // cell), int(ln // cell))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        j = grid.get((c[0] + dx, c[1] + dy))
                        if j is not None:
                            ri, rj = find(i), find(j)
                            if ri != rj:
                                parent[ri] = rj
                grid[c] = i
        comps: dict[int, list[int]] = defaultdict(list)
        for i in range(len(segs)):
            comps[find(i)].append(i)
        for root, idxs in comps.items():
            members = [segs[i] for i in idxs]
            out.extend(_pieces(k, members))
    return out


_CLASS_RANK = {"highway": 3, "axis": 3, "road": 2, "bridge": 2, "street": 1}


def _pieces(key: str, members) -> list[M.Place]:
    # names: the most frequent of each language across the segments
    def most(tagkey):
        c: dict[str, int] = defaultdict(int)
        for _, tags, _, _ in members:
            v = tags.get(tagkey)
            if v:
                c[v] += 1
        return max(c, key=c.get) if c else None
    name = most("name")
    name_ar = most("name:ar") or (name if name and tn.script_of(tn.normalize(name)) == "ar" else None)
    name_en = most("name:en") or (name if name and tn.script_of(tn.normalize(name)) == "latin" else None)
    cls = max((m[3] for m in members), key=lambda c: _CLASS_RANK.get(c, 0))
    if name and ("محور" in name or "axis" in name.lower()):
        cls = "axis"
    # order every vertex along the street's main direction, then cut by length
    pts = [p for _, _, ps, _ in members for p in ps]
    total = sum(_length(ps) for _, _, ps, _ in members)
    lat0 = sum(p[0] for p in pts) / len(pts)
    lng0 = sum(p[1] for p in pts) / len(pts)
    # principal axis
    kx = math.cos(math.radians(lat0))
    sxx = sum(((p[1] - lng0) * kx) ** 2 for p in pts)
    syy = sum((p[0] - lat0) ** 2 for p in pts)
    sxy = sum(((p[1] - lng0) * kx) * (p[0] - lat0) for p in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(ang), math.sin(ang)
    proj = sorted(pts, key=lambda p: (p[1] - lng0) * kx * ux + (p[0] - lat0) * uy)
    n_pieces = max(1, int(math.ceil(total / PIECE_M))) if cls != "street" or total > 2 * PIECE_M else 1
    chunk = max(1, len(proj) // n_pieces)
    grp = "s" + members[0][0]
    out = []
    for i in range(n_pieces):
        part = proj[i * chunk:(i + 1) * chunk] if i < n_pieces - 1 else proj[i * chunk:]
        if not part:
            continue
        clat = sum(p[0] for p in part) / len(part)
        clng = sum(p[1] for p in part) / len(part)
        # the pin sits ON the street: the vertex nearest the piece's centroid
        pin = min(part, key=lambda p: (p[0] - clat) ** 2 + ((p[1] - clng) * kx) ** 2)
        ys = [p[0] for p in part]
        xs = [p[1] for p in part]
        ext = 0.5 * R.haversine(min(ys), min(xs), max(ys), max(xs))
        pid = "s" + members[0][0] + (f"#{i}" if n_pieces > 1 else "")
        out.append(M.Place(pid=pid, kind="street", cat=cls, lat=round(pin[0], 6), lng=round(pin[1], 6),
                           name_ar=R.tidy_name(name_ar), name_en=R.tidy_name(name_en),
                           alt=[x for x in {name} if x and x not in (name_ar, name_en)],
                           brand=None, phone=None, website=None, social=None, hours=None, addr=None, wd=None,
                           srcs=R.SOURCE_BITS[R.SRC_OSM], conf=0.9,
                           pop=min(1.0, 0.25 + 0.12 * _CLASS_RANK.get(cls, 1) + 0.1 * min(1.0, math.log10(max(total, 10)) / 4.5)),
                           extent_m=ext, population=0, members=[m[0] for m in members][:5], grp=grp if n_pieces > 1 else None))
    return out
