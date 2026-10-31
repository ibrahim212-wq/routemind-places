"""The NAME ROUTER — which tile holds a word (docs/place-search-2026-10.md §6b).

The phone keeps the tiles around the user (PlaceStore: 3 km on mobile data, 12 km on Wi-Fi) and the
engine searches only the files on the phone, so a place the index HAS was unfindable as soon as its
tile was elsewhere: a small restaurant across Cairo, a shop in another city, «كشري في مدينة نصر»
typed in Alexandria. The national file holds the prominent places only (42k of 650k).

`router.bin` (one more file in the manifest, `router`) holds, for every tile, a BLOOM FILTER of its
vocabulary — the very index tokens `tiles.py` writes into `vocab` (word, stem, skeleton, joined
pair) — and one filter of the COMMON tokens (in more than ROUTER_MAX_TILES tiles: «مطعم», «شارع»
are everywhere and route nothing; the words around them decide). An exact token → tiles table was
measured at 4.1 MB gzipped (2026-10-19 release, 625,517 tokens); the filters are ≈ 2.3 MB at a
false hit of ≈ 5.6e-4 per tile and form, and need no string table on the phone.

A query's name words (the engine's parse: the residual, and the category words of a category +
name query) each give the tiles whose filter holds one of their OWN forms (the word, its stems),
else — only then — one of their skeletons; a word that is common, or held nowhere, routes nothing.
The tiles that hold EVERY routing word are the candidates, nearest the anchor first. The phone
searches the ones it has whatever their distance (≤ ROUTE_OPEN_MAX) and, when the words are
distinctive (≤ ROUTE_DISTINCT_MAX tiles), fetches at most ROUTE_FETCH_MAX it lacks — a few hundred
KB, once. A partly typed word routes nothing (no prefix: a filter cannot complete a word, and a
download per keystroke would spend the user's data).

FILE (little-endian):
  "RMWR"  u8 version  u8 k  u16 0  |  u8 n, n bytes: the release version (UTF-8)
  u32 T (tiles)  |  u32 m0 (bits, a prime), (m0 + 7) / 8 bytes: the common filter
  T × [ u8 n, n bytes: tile id (ASCII) | 4 × f64 bbox minLng, minLat, maxLng, maxLat | u32 m, (m + 7) / 8 bytes ]
HASH: h = fmix64(FNV-1a 64 over the token's UTF-8); h1 = low 32 bits, h2 = (high 32 bits) | 1; bit j
of k = (h1 + j·h2) mod m (m prime); bit b lives in byte b >> 3, mask 1 << (b & 7).

`Router` below is the reference; PlaceRouter.kt ⇄ PlaceSearch.swift (PlaceRouter) transcribe it
(fixtures/router_cases.json; tool/place_search_parity.py checks the constants).
"""
from __future__ import annotations

import gzip
import hashlib
import math
import sqlite3
import struct

from . import textnorm as tn

ROUTER_MAX_TILES = 64      # a token in more tiles than this is common: it routes nothing (24 left half the
                           # names unroutable — «الفارس», "Trust Code": two common words, one tile)
ROUTE_DISTINCT_MAX = 8     # the words are distinctive when together they name ≤ this many tiles
ROUTE_NEAR_M = 25000.0     # words that are not: only their tiles this near the anchor are fetched
ROUTE_FETCH_MAX = 3        # tiles the phone fetches for one set of words, nearest first (Wi-Fi)
ROUTE_FETCH_METERED = 2    # … on mobile data
ROUTE_OPEN_MAX = 6         # routed tiles already on the phone searched beyond the anchor's ring
BLOOM_BITS = 15.6          # bits per token
BLOOM_K = 11               # → (1 − e^(−k/bits))^k ≈ 5.6e-4
BLOOM_MIN_BITS = 1024      # the smallest filter (a near-empty desert tile)
MAGIC = b"RMWR"
VERSION = 1

_FNV_OFFSET = 0xcbf29ce484222325
_FNV_PRIME = 0x100000001b3
_MASK64 = (1 << 64) - 1


def fnv1a64(s: str) -> int:
    h = _FNV_OFFSET
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & _MASK64
    return h


def fmix64(h: int) -> int:
    """MurmurHash3's finalizer: FNV-1a's high 32 bits barely move for short tokens (the double-hash step
    of «الحكمه» walked onto a 12-token filter's bits in the fixture) — every bit of the input reaches
    every bit of the output before the hash is split."""
    h ^= h >> 33
    h = (h * 0xff51afd7ed558ccd) & _MASK64
    h ^= h >> 33
    h = (h * 0xc4ceb9fe1a85ec53) & _MASK64
    h ^= h >> 33
    return h


def _bits(token: str, m: int) -> list[int]:
    h = fmix64(fnv1a64(token))
    h1 = h & 0xFFFFFFFF
    h2 = (h >> 32) | 1
    return [(h1 + j * h2) % m for j in range(BLOOM_K)]


def _prime_at_least(n: int) -> int:
    def prime(x):
        if x < 2 or x % 2 == 0:
            return x == 2
        i = 3
        while i * i <= x:
            if x % i == 0:
                return False
            i += 2
        return True
    while not prime(n):
        n += 1
    return n


def _filter(tokens: list[str]) -> tuple[int, bytearray]:
    """m is a PRIME ≥ 1024 bits: double hashing walks every bit of a prime modulus (a 96-bit filter of six
    tokens gave «حلواني» a false hit in the fixture), stored in (m + 7) // 8 bytes."""
    m = _prime_at_least(max(BLOOM_MIN_BITS, int(math.ceil(len(tokens) * BLOOM_BITS))))
    buf = bytearray((m + 7) // 8)
    for t in tokens:
        for b in _bits(t, m):
            buf[b >> 3] |= 1 << (b & 7)
    return m, buf


def _has(m: int, buf, token: str) -> bool:
    for b in _bits(token, m):
        if not buf[b >> 3] & (1 << (b & 7)):
            return False
    return True


def build_router(tiles: list[tuple[str, list[float], str]], out_path: str, version: str) -> dict:
    """tiles = [(tile id, bbox, raw sqlite path)] in manifest order. Returns the stats the build logs."""
    entries = []
    for tid, bbox, path in tiles:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        entries.append((tid, bbox, [r[0] for r in con.execute("SELECT t FROM vocab ORDER BY t")]))
        con.close()
    data, stats = encode_router(entries, version)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return stats


def encode_router(entries: list[tuple[str, list[float], list[str]]], version: str,
                  max_tiles: int = ROUTER_MAX_TILES) -> tuple[bytes, dict]:
    """entries = [(tile id, bbox, the tile's tokens)] → the file's bytes (FILE above) + stats. The readers
    never see `max_tiles` (common is what the file's common filter holds): the fixture lowers it."""
    vocab = [toks for _t, _b, toks in entries]
    tiles = [(t, b, None) for t, b, _toks in entries]
    count: dict[str, int] = {}
    for toks in vocab:
        for t in set(toks):
            count[t] = count.get(t, 0) + 1
    common = sorted(t for t, n in count.items() if n > max_tiles)
    out = bytearray(MAGIC)
    out += struct.pack("<BBH", VERSION, BLOOM_K, 0)
    vb = (version or "").encode("utf-8")[:255]
    out += struct.pack("<B", len(vb)) + vb
    out += struct.pack("<I", len(tiles))
    m0, f0 = _filter(common)
    out += struct.pack("<I", m0) + f0
    routable = 0
    for (tid, bbox, _p), toks in zip(tiles, vocab):
        keep = sorted({t for t in toks if count[t] <= max_tiles})
        routable += len(keep)
        m, f = _filter(keep)
        ib = tid.encode("ascii")
        out += struct.pack("<B", len(ib)) + ib
        out += struct.pack("<4d", *[float(x) for x in bbox])
        out += struct.pack("<I", m) + f
    return bytes(out), {"tiles": len(tiles), "tokens": len(count), "common": len(common), "routable_postings": routable,
                        "bytes": len(out)}


def gzip_router(raw: str, dst: str) -> tuple[int, str]:
    with open(raw, "rb") as f:
        data = f.read()
    gz = gzip.compress(data, compresslevel=9, mtime=0)
    with open(dst, "wb") as f:
        f.write(gz)
    return len(gz), hashlib.sha256(gz).hexdigest()


# ── the lookup (the phone's; PlaceRouter.kt ⇄ PlaceSearch.swift) ────────────────

def own_forms(q: str) -> list[str]:
    """engine.Engine._index_forms without the skeletons: the word and its stems."""
    return [q] + tn.stems(q)[1:]


def skel_forms(q: str) -> list[str]:
    return ["~" + sk for sk in tn.skeletons(q)[:2] if len(sk) >= 2 and not sk.isdigit()]


class Router:
    def __init__(self, path: str | None = None, data: bytes | None = None):
        if data is None:
            with open(path, "rb") as f:
                data = f.read()
        d = data
        if d[:2] == b"\x1f\x8b":
            d = gzip.decompress(d)
        if d[:4] != MAGIC or d[4] != VERSION:
            raise ValueError("router: not a version-1 router file")
        self.k = d[5]
        o = 8
        n = d[o]
        self.version = d[o + 1:o + 1 + n].decode("utf-8")
        o += 1 + n
        (count,) = struct.unpack_from("<I", d, o)
        o += 4
        (self.m0,) = struct.unpack_from("<I", d, o)
        o += 4
        self.f0 = d[o:o + (self.m0 + 7) // 8]
        o += (self.m0 + 7) // 8
        self.ids: list[str] = []
        self.bbox: list[tuple[float, float, float, float]] = []
        self.m: list[int] = []
        self.f: list[bytes] = []
        for _ in range(count):
            n = d[o]
            self.ids.append(d[o + 1:o + 1 + n].decode("ascii"))
            o += 1 + n
            self.bbox.append(struct.unpack_from("<4d", d, o))
            o += 32
            (m,) = struct.unpack_from("<I", d, o)
            o += 4
            self.m.append(m)
            self.f.append(d[o:o + (m + 7) // 8])
            o += (m + 7) // 8

    def word_tiles(self, q: str) -> list[int] | None:
        """The tiles one whole word may be in; None = the word routes nothing (common, or held nowhere).
        Its own forms first; its skeleton only when no own form is held — a skeleton is never rarer
        than the word, so it must not veto a rare spelling."""
        for group in (own_forms(q), skel_forms(q)):
            if any(_has(self.m0, self.f0, f) for f in group):
                return None
            hit = [i for i in range(len(self.ids)) if any(_has(self.m[i], self.f[i], f) for f in group)]
            if hit:
                return hit
        return None

    def route_tiles(self, words: list[str], lat: float, lng: float) -> list[tuple[str, float]]:
        """Every tile that holds all the routing words with its distance from the anchor, nearest first
        (ties by id); [] when no word routes or the words share no tile."""
        sets = []
        for w in words:
            if not w or tn.is_stopword(w):
                continue
            s = self.word_tiles(w)
            if s is not None:
                sets.append(set(s))
        if not sets:
            return []
        inter = set.intersection(*sets)
        out = sorted((box_distance(lat, lng, self.bbox[i]), self.ids[i]) for i in inter)
        return [(t, d) for d, t in out]


def plan(routed: list[tuple[str, float]], have: set[str], metered: bool) -> tuple[list[str], list[str]]:
    """(open, fetch) for one query: the routed tiles on the phone to search now, and the ones to download.
    Distinctive words (≤ ROUTE_DISTINCT_MAX tiles) fetch their nearest tiles wherever they are; common
    ones only those within ROUTE_NEAR_M of the anchor."""
    open_ = [t for t, _ in routed if t in have][:ROUTE_OPEN_MAX]
    missing = [(t, d) for t, d in routed if t not in have]
    if len(routed) > ROUTE_DISTINCT_MAX:
        missing = [(t, d) for t, d in missing if d <= ROUTE_NEAR_M]
    cap = ROUTE_FETCH_METERED if metered else ROUTE_FETCH_MAX
    return open_, [t for t, _ in missing[:cap]]


def box_distance(lat: float, lng: float, b) -> float:
    """Metres from a point to the nearest point of a box (minLng, minLat, maxLng, maxLat); 0 inside."""
    cx = min(max(lng, b[0]), b[2])
    cy = min(max(lat, b[1]), b[3])
    r = math.pi / 180
    p1, p2 = lat * r, cy * r
    dp, dl = p2 - p1, (cx - lng) * r
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def query_words(p) -> list[str]:
    """The words a parsed query routes on (engine.Parsed): a name or a category + name; never a bare
    category, a chain (every branch is in the national file) or an area (the national file)."""
    if p.kind == "name":
        return list(p.residual)
    if p.kind == "cat_name":
        return list(p.cat_words) + list(p.residual)
    return []
