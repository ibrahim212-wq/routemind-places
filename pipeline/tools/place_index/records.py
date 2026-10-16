"""The unified record every source adapter emits, and the small helpers they share.

A Record is ONE source's claim about ONE place (or area, or street). merge.py clusters the claims
about the same real place and decides, field by field, which claim wins.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import textnorm as tn

# Source codes, in the order merge.py trusts their GEOMETRY and their CATEGORY.
SRC_OSM = "osm"        # OpenStreetMap (Geofabrik extract, or the HOT export on desk runs)
SRC_ATP = "atp"        # AllThePlaces rows inside Overture (brand websites, CC0)
SRC_FSQ = "fsq"        # Foursquare OS Places (direct, or rows inside Overture)
SRC_MS = "ms"          # Microsoft rows inside Overture
SRC_META = "meta"      # Meta rows inside Overture (Facebook pages)
SRC_OVT_OTHER = "ovx"  # PinMeTo / DAC / … rows inside Overture
SRC_DIV = "div"        # Overture divisions (OSM-derived area names)
SRC_WD = "wd"          # Wikidata
SRC_GN = "gn"          # GeoNames
SOURCE_BITS = {SRC_OSM: 1, SRC_ATP: 2, SRC_FSQ: 4, SRC_MS: 8, SRC_META: 16, SRC_OVT_OTHER: 32,
               SRC_DIV: 64, SRC_WD: 128, SRC_GN: 256}


@dataclass
class Record:
    src: str                 # one of the SRC_* codes
    sid: str                 # the source's own id ("n123", GERS id, fsq id, Q-id …)
    kind: str                # "poi" | "area" | "street"
    cat: str                 # display category id (taxonomy.CATS)
    lat: float
    lng: float
    names: list[tuple[str, str]] = field(default_factory=list)  # (text, role) role ∈ primary|ar|en|alt|brand|old
    brand: str | None = None
    brand_wd: str | None = None
    conf: float = 0.5        # the source's own existence confidence, 0..1
    phone: str | None = None
    website: str | None = None
    social: str | None = None
    hours: str | None = None  # OSM opening_hours syntax
    addr: str | None = None   # freeform street address as the source wrote it
    street: str | None = None
    wd: str | None = None     # Wikidata QID
    extent_m: float = 0.0     # radius of the feature's footprint (polygons, areas, streets)
    population: int = 0
    closed: bool = False      # temporarily closed (permanently closed rows are dropped upstream)
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.src}:{self.sid}"


# ── names ────────────────────────────────────────────────────────────────────

_SPLIT = re.compile(r"\s+[-–—|/•·]\s+|\s*[|/•·]\s*|\s+-\s*|\s*\(\s*|\s*\)\s*")


def split_scripts(name: str) -> tuple[str | None, str | None]:
    """A Meta page name often carries both scripts: «ستار مول  star mool», «Ezz Lab - معامل عز».
    Returns (arabic part, latin part) — either may be None."""
    if not name:
        return None, None
    parts = [p.strip() for p in _SPLIT.split(name) if p and p.strip()]
    ar_parts, la_parts = [], []
    for p in parts:
        s = tn.script_of(tn.normalize(p))
        if s == "ar":
            ar_parts.append(p)
        elif s == "latin":
            la_parts.append(p)
        elif s == "mixed":
            # split a mixed run at the script boundary
            words = p.split()
            a = [w for w in words if tn.script_of(tn.normalize(w)) == "ar"]
            l = [w for w in words if tn.script_of(tn.normalize(w)) == "latin"]
            if a:
                ar_parts.append(" ".join(a))
            if l:
                la_parts.append(" ".join(l))
    ar = " ".join(ar_parts).strip() or None
    la = " ".join(la_parts).strip() or None
    return ar, la


_TITLE_KEEP_UPPER = re.compile(r"^[A-Z0-9&.\-]{2,5}$")


def tidy_name(name: str | None) -> str | None:
    """Display hygiene only (never applied to index tokens): collapse spaces, drop emoji and
    decoration, title-case an ALL-CAPS Latin name longer than an acronym."""
    if not name:
        return None
    s = "".join(ch for ch in name if not (0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF
                                          or ord(ch) in (0xFE0F, 0x200D)))
    s = " ".join(s.split()).strip(" -|_.,")
    if not s:
        return None
    letters = [c for c in s if c.isalpha() and c.isascii()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 6:
        s = " ".join(w if _TITLE_KEEP_UPPER.match(w) else w.capitalize() for w in s.split())
    return s


def phone_key(phone: str | None) -> str | None:
    """Last 9 digits — survives +20 / 0 prefixes and spacing."""
    if not phone:
        return None
    d = "".join(c for c in tn.normalize(phone) if c.isdigit())
    return d[-9:] if len(d) >= 8 else None


def clean_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    p = phone.split(";")[0].strip()
    d = "".join(c for c in tn.normalize(p) if c.isdigit() or c == "+")
    if len(d.replace("+", "")) < 5:
        return None
    if d.startswith("0020"):
        d = "+20" + d[4:]
    elif d.startswith("20") and len(d) >= 11:
        d = "+" + d
    elif d.startswith("0") and len(d) in (10, 11):
        d = "+20" + d[1:]
    return d


def clean_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.split(";")[0].strip()
    if not u or " " in u:
        return None
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


# ── geometry ─────────────────────────────────────────────────────────────────

EARTH_R = 6371008.8


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


# Egypt's working box (the Halaib triangle and the Sinai included); points outside are dropped,
# points inside are checked against the country polygon by the caller.
EG_BBOX = (24.6, 21.6, 37.0, 31.8)  # minx, miny, maxx, maxy
