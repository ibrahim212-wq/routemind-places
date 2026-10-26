#!/usr/bin/env python3
"""Website images for places that have a website but no open-data photo (docs/place-photos-2026-10.md §10).

The rules below are the Python MIRROR of lib/shared/services/website_preview_rules.dart (the phone's pure
parser + filters). Same constants, same order, same reject reasons: a change to one lands in the other and
`test/website_preview_test.dart` / `--selftest` are the two ends of the same canned cases.

    python tools/place_index/bench/website_photo_eval.py stats  --tiles <dir>            # how many places have a website
    python tools/place_index/bench/website_photo_eval.py sample --tiles <dir> --n 300 --out sample.json
    python tools/place_index/bench/website_photo_eval.py run    --sample sample.json --out results.json
    python tools/place_index/bench/website_photo_eval.py report --results results.json --stats stats.json
    python tools/place_index/bench/website_photo_eval.py --selftest

Polite by construction: at most 4 requests in flight, one host at a time per place, 5 s timeouts, ≤ 512 KB of
HTML, an image's first ≤ 256 KB (until its size is known), never a page the place did not name. The images are
not stored: only the verdict and the dimensions go to the results file.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import glob
import ipaddress
import json
import os
import random
import re
import socket
import sqlite3
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── constants (Dart: WebsiteRules) ────────────────────────────────────────────────────────────────────────────
FETCH_TIMEOUT_S = 5
MAX_HTML = 512 * 1024
MAX_REDIRECTS = 3
MAX_IMG_HEAD = 256 * 1024
MAX_IMG_LEN = 3 * 1024 * 1024  # a photo is read whole (its pixels are looked at); a bigger one is not worth the data
# A hero photo is not a logo / profile picture / banner (measured on 39 judged og:images: 19 of them were graphics):
SQUARE = (0.95, 1.05)          # near-square og:image = a logo or an avatar: tried as a logo, never as the hero
FLAT_TOP, FLAT_N90 = 0.5, 8     # on a 48×48 thumb of 3-bit colours: one colour ≥ 50 % of the pixels, or ≤ 8 colours make 90 %
THUMB = 48
PHOTO_MIN_W, PHOTO_MIN_H = 300, 200
PHOTO_ASPECT = (0.4, 2.8)
LOGO_MIN = 96
LOGO_ASPECT = (0.25, 4.0)
MAX_PHOTO_TRIES = 3
MAX_LOGO_TRIES = 3
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Mobile Safari/537.36")

# Hosts that are not the place's own site: social networks (they block scraping and carry their own page),
# link hubs, messengers, maps, shorteners, and aggregators (their photo is theirs, not the place's).
BLOCKED_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "fb.watch", "instagram.com", "linktr.ee", "linktree.com", "linkin.bio",
    "beacons.ai", "twitter.com", "x.com", "tiktok.com", "youtube.com", "youtu.be", "wa.me", "whatsapp.com",
    "t.me", "telegram.me", "telegram.org", "snapchat.com", "linkedin.com", "pinterest.com", "goo.gl",
    "g.page", "maps.app.goo.gl", "google.com", "maps.google.com", "bit.ly", "tinyurl.com", "cutt.ly",
    "booking.com", "tripadvisor.com", "agoda.com", "expedia.com", "foursquare.com", "yelp.com", "olx.com.eg",
    "wikipedia.org", "wikimedia.org", "wikidata.org",
)

# Default share images of platforms (data-driven: GENERIC_FROM_EVAL in the doc), matched on host + path.
GENERIC_URL = re.compile(
    r"(?:^|[./])(?:wix\.com/|s\.w\.org/|gravatar\.com/|wp\.com/i/|wordpress\.com/i/|"
    r"squarespace\.com/universal/|squarespace-cdn\.com/universal/|godaddy\.com/|wsimg\.com/isteam/ip/static/|"
    r"weebly\.com/images/|cdn\.shopify\.com/shopifycloud/|shopifycloud/|blogger\.com/img/|"
    r"google\.com/images/|gstatic\.com/images/|facebook\.com/images/|fbcdn\.net/rsrc|"
    r"w-logo|wp-content/plugins/|wp-includes/images/|themes/[^/]+/screenshot\.|dnom\.com/|hugedomains\.com/|sedo\.com/|dan\.com/|afternic\.com/)",
    re.I)
TRACKING_URL = re.compile(r"(?:1x1|\bpixel\b|spacer|blank\.(?:gif|png)|transparent\.(?:gif|png)|tracking|/beacon)", re.I)
PLACEHOLDER_URL = re.compile(
    r"(?:placeholder|no[-_]?image|noimage|default[-_]?(?:image|og|share|thumb|cover)|coming[-_]?soon|"
    r"image[-_]?not[-_]?found|dummy|not[-_]?available)", re.I)
LOGO_NAME = re.compile(r"(?:^|[^a-z])(?:logo|favicon|icon|brand|sprite|avatar|wordmark)(?:[^a-z]|$)", re.I)
# A page that is not the place any more (parked, for sale, hijacked for spam): nothing of it is shown.
SPAM_TEXT = re.compile(
    r"(?:gacor|togel|judi online|situs slot|slot online|slot gacor|casino|betting|1xbet|sportsbook|\bporn|\bxxx\b|viagra|"
    r"escort|domain (?:name )?(?:is |may be )?for sale|buy this domain|this domain is for sale|hugedomains|"
    r"sedo domain parking|domain parking)", re.I)
UNRENDERABLE_EXT = (".svg", ".ico", ".svgz", ".avif", ".heic")

# ── the pure parser ───────────────────────────────────────────────────────────────────────────────────────────
_ENT = {"&amp;": "&", "&quot;": '"', "&#39;": "'", "&#x27;": "'", "&apos;": "'", "&lt;": "<", "&gt;": ">",
        "&#x2f;": "/", "&#47;": "/"}
_ENT_RE = re.compile(r"&(?:amp|quot|apos|lt|gt|#39|#x27|#x2f|#47);", re.I)


def unescape(s: str) -> str:
    return _ENT_RE.sub(lambda m: _ENT[m.group(0).lower()], s)


_TAG = re.compile(r"<(meta|link)\b([^>]*)>", re.I)
_ATTR = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_LD = re.compile(r"<script\b[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>", re.I | re.S)


def attrs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR.finditer(raw):
        k = m.group(1).lower()
        v = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else (m.group(4) or ""))
        out.setdefault(k, unescape(v).strip())
    return out


def _walk_ld(node, key: str, out: list[str], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, list):
        for x in node[:20]:
            _walk_ld(x, key, out, depth + 1)
    elif isinstance(node, dict):
        v = node.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict) and isinstance(v.get("url"), str):
            out.append(v["url"])
        elif isinstance(v, list):
            for x in v[:5]:
                if isinstance(x, str):
                    out.append(x)
                elif isinstance(x, dict) and isinstance(x.get("url"), str):
                    out.append(x["url"])
        for k, x in node.items():
            if k != key and isinstance(x, (dict, list)):
                _walk_ld(x, key, out, depth + 1)


def _icon_size(sizes: str | None) -> int:
    m = re.search(r"(\d+)\s*x\s*(\d+)", sizes or "", re.I)
    return int(m.group(1)) if m else 0


def parse_html(html: str, base: str) -> dict:
    """{'photos': [url…], 'logos': [url…], 'icons': [url…], 'title': str|None} — absolute URLs, in priority order."""
    metas: list[tuple[str, str]] = []
    icons: list[tuple[int, int, str]] = []  # (is_apple, size, href)
    image_src: list[str] = []
    for m in _TAG.finditer(html):
        a = attrs(m.group(2))
        if m.group(1).lower() == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                metas.append((key, a["content"]))
        else:
            rel = (a.get("rel") or "").lower().split()
            href = a.get("href")
            if not href:
                continue
            if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
                icons.append((1, _icon_size(a.get("sizes")), href))
            elif "icon" in rel or "shortcut" in rel:
                icons.append((0, _icon_size(a.get("sizes")), href))
            elif "image_src" in rel:
                image_src.append(href)
    ld_img: list[str] = []
    ld_logo: list[str] = []
    for m in _LD.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        _walk_ld(data, "image", ld_img)
        _walk_ld(data, "logo", ld_logo)

    def pick(*keys: str) -> list[str]:
        return [c for k in keys for (mk, c) in metas if mk == k]

    photos_raw = (pick("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")
                  + image_src + ld_img[:2])
    logos_raw = pick("og:logo") + ld_logo[:2]
    icons.sort(key=lambda t: (-t[0], -t[1]))
    icon_urls = [h for (_, _, h) in icons]

    def absolutize(raw: list[str]) -> list[str]:
        seen, out = set(), []
        for r in raw:
            u = resolve(base, r)
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    title = next((c for (k, c) in metas if k in ("og:site_name",)), None)
    text = " ".join([c for (k, c) in metas if k in ("og:title", "og:description", "description", "og:site_name",
                                                    "twitter:title", "twitter:description")]
                    + [m.group(1) for m in _TITLE.finditer(html)][:1])
    return {"photos": absolutize(photos_raw), "logos": absolutize(logos_raw + icon_urls),
            "icons": absolutize(icon_urls), "title": title, "text": text}


def resolve(base: str, ref: str) -> str | None:
    ref = (ref or "").strip()
    if not ref or ref.lower().startswith(("data:", "javascript:", "blob:")):
        return None
    try:
        u = urllib.parse.urljoin(base, ref)
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    if p.scheme == "http":  # ATS / cleartext policy: an image is always asked for over https
        u = "https" + u[4:]
    u = u.split("#")[0]
    # percent-encode what is not ASCII (Dart's Uri does this by itself)
    return urllib.parse.quote(u, safe="/%:@!$&'()*+,;=~-._?#[]")


def page_uri(website: str | None) -> str | None:
    """The page to read, or None when the website is not one we may contact (reason in blocked_reason)."""
    return None if blocked_reason(website) else _normalize(website)


def _normalize(website: str | None) -> str | None:
    w = (website or "").strip()
    if not w:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", w, re.I):
        w = "https://" + w
    try:
        p = urllib.parse.urlsplit(w)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        return None
    return urllib.parse.urlunsplit(("https", p.netloc, p.path or "/", p.query, ""))


def blocked_reason(website: str | None) -> str | None:
    u = _normalize(website)
    if u is None:
        return "no_url"
    host = (urllib.parse.urlsplit(u).hostname or "").lower().rstrip(".")
    if "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".test", ".localhost")):
        return "bad_host"
    if not host.isascii():  # an IDN host: not asked for (the platforms' HTTP stacks differ on punycode)
        return "idn_host"
    try:
        ipaddress.ip_address(host)
        return "ip_host"
    except ValueError:
        pass
    for b in BLOCKED_HOSTS:
        if host == b or host.endswith("." + b):
            return "blocked_host"
    return None


def cache_key(website: str) -> str:
    u = _normalize(website) or website
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host + (p.path.rstrip("/") if p.path != "/" else "")


def domain_of(website: str) -> str:
    u = _normalize(website) or website
    host = (urllib.parse.urlsplit(u).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def url_reject(url: str, icons: list[str], photo_slot: bool) -> str | None:
    """Reasons an image URL is not worth fetching (before any request)."""
    low = url.lower()
    path = urllib.parse.urlsplit(low).path
    if path.endswith(UNRENDERABLE_EXT):
        return "unrenderable"
    hostpath = (urllib.parse.urlsplit(low).hostname or "") + path
    if GENERIC_URL.search(hostpath):
        return "generic_default"
    if TRACKING_URL.search(hostpath):
        return "tracking"
    if PLACEHOLDER_URL.search(path):
        return "placeholder"
    if photo_slot and (url in icons or re.search(r"/favicon\.[a-z]+$", path)):
        return "favicon_as_photo"
    return None


def is_logoish(url: str) -> bool:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    return bool(LOGO_NAME.search(name))


def judge_size(w: int, h: int, photo: bool) -> str | None:
    """None = acceptable; else the rule that refused it."""
    if w <= 0 or h <= 0:
        return "undecodable"
    asp = w / h
    if photo:
        if w < PHOTO_MIN_W or h < PHOTO_MIN_H:
            return "too_small"
        if not (PHOTO_ASPECT[0] <= asp <= PHOTO_ASPECT[1]):
            return "aspect"
    else:
        if min(w, h) < LOGO_MIN:
            return "too_small"
        if not (LOGO_ASPECT[0] <= asp <= LOGO_ASPECT[1]):
            return "aspect"
    return None


def graphic_verdict(thumb_rgb: list[tuple[int, int, int]]) -> str | None:
    """'graphic' when a THUMB×THUMB thumbnail (pixels composited on white) is mostly one flat colour: a logo,
    a banner or a flyer, not a photograph. Pixels are quantised to 3 bits a channel."""
    n = len(thumb_rgb)
    if n == 0:
        return "undecodable"
    q = collections.Counter((r >> 5, g >> 5, b >> 5) for (r, g, b) in thumb_rgb)
    ranked = q.most_common()
    if ranked[0][1] / n >= FLAT_TOP:
        return "graphic"
    acc = 0
    for i, (_, k) in enumerate(ranked, 1):
        acc += k
        if acc >= 0.9 * n:
            return "graphic" if i <= FLAT_N90 else None
    return None


def thumb_of(body: bytes) -> list[tuple[int, int, int]] | None:
    """The eval's stand-in for the phone's dart:ui decode: PIL, a BOX-resampled THUMB×THUMB on white."""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(body))
        im = im.convert("RGBA").resize((THUMB, THUMB), Image.BOX)
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        return list(Image.alpha_composite(bg, im).convert("RGB").getdata())
    except Exception:
        return None


def image_size(b: bytes) -> tuple[int, int] | None:
    """Pixel size from the header of a PNG / GIF / JPEG / WebP, or None (unknown, or not enough bytes yet)."""
    n = len(b)
    if n >= 24 and b[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", b[16:24])
    if n >= 10 and b[:4] == b"GIF8":
        return struct.unpack("<HH", b[6:10])
    if n >= 4 and b[0] == 0xFF and b[1] == 0xD8:
        i = 2
        while i + 9 < n:
            if b[i] != 0xFF:
                i += 1
                continue
            while i < n and b[i] == 0xFF:
                i += 1
            if i >= n:
                break
            mk = b[i]
            i += 1
            if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
                continue
            if i + 2 > n:
                break
            ln = (b[i] << 8) | b[i + 1]
            if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                if i + 7 > n:
                    break
                return ((b[i + 5] << 8) | b[i + 6], (b[i + 3] << 8) | b[i + 4])
            i += ln
        return None
    if n >= 30 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        t = b[12:16]
        if t == b"VP8 " and b[23:26] == b"\x9d\x01\x2a":
            return (b[26] | (b[27] << 8)) & 0x3FFF, (b[28] | (b[29] << 8)) & 0x3FFF
        if t == b"VP8L" and b[20] == 0x2F:
            v = b[21] | (b[22] << 8) | (b[23] << 16) | (b[24] << 24)
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if t == b"VP8X":
            return 1 + (b[24] | (b[25] << 8) | (b[26] << 16)), 1 + (b[27] | (b[28] << 8) | (b[29] << 16))
    return None


# ── fetching (polite) ─────────────────────────────────────────────────────────────────────────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_CTX = ssl.create_default_context()
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_CTX))


def _get(url: str, limit: int, accept: str, stop=None) -> tuple[int, str, str, bytes, str]:
    """(status, content-type, content-length, body ≤ limit, final url), following ≤ MAX_REDIRECTS (https only,
    never into a blocked host). Raises on network errors."""
    cur = url
    for hop in range(MAX_REDIRECTS + 1):
        req = urllib.request.Request(cur, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ar,en;q=0.8"})
        try:
            r = _OPENER.open(req, timeout=FETCH_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                nxt = resolve(cur, e.headers["Location"])
                if not nxt or blocked_reason(nxt) or hop == MAX_REDIRECTS:
                    return e.code, "", "", b"", cur
                cur = nxt
                continue
            return e.code, e.headers.get("Content-Type", ""), "", b"", cur
        ct = r.headers.get("Content-Type", "")
        cl = r.headers.get("Content-Length", "")
        body = b""
        deadline = time.time() + FETCH_TIMEOUT_S * 2
        while len(body) < limit and time.time() < deadline:
            chunk = r.read(min(16384, limit - len(body)))
            if not chunk:
                break
            body += chunk
            if stop and stop(body):
                break
        r.close()
        return r.status, ct, cl, body, cur
    return 0, "", "", b"", cur


def _charset(ct: str, body: bytes) -> str:
    m = re.search(r"charset=([\w-]+)", ct, re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    if m:
        v = m.group(1)
        return v.decode("ascii", "ignore") if isinstance(v, bytes) else v
    return "utf-8"


def check_image(url: str, photo: bool) -> dict:
    """Fetch one image and judge it. A photo is read whole (≤ MAX_IMG_LEN) and its pixels looked at; a logo only
    by its header. {'ok': bool, 'why': str, 'w','h', 'square'}"""
    try:
        if photo:
            st, ct, cl, body, _ = _get(url, MAX_IMG_LEN + 1, "image/avif,image/webp,image/*;q=0.8")
        else:
            st, ct, cl, body, _ = _get(url, MAX_IMG_HEAD, "image/avif,image/webp,image/*;q=0.8",
                                       stop=lambda b: image_size(b) is not None)
    except Exception as e:
        return {"ok": False, "why": "img_net:" + type(e).__name__}
    if st != 200:
        return {"ok": False, "why": "img_http"}
    if not ct.lower().startswith("image/") or "svg" in ct.lower() or "icon" in ct.lower():
        return {"ok": False, "why": "img_type"}
    if (cl.isdigit() and int(cl) > MAX_IMG_LEN) or len(body) > MAX_IMG_LEN:
        return {"ok": False, "why": "too_big"}
    sz = image_size(body)
    if sz is None:
        return {"ok": False, "why": "undecodable"}
    bad = judge_size(sz[0], sz[1], photo)
    if bad:
        return {"ok": False, "why": bad, "w": sz[0], "h": sz[1]}
    out = {"ok": True, "why": "ok", "w": sz[0], "h": sz[1], "square": SQUARE[0] <= sz[0] / sz[1] <= SQUARE[1]}
    if photo and not out["square"]:
        th = thumb_of(body)
        bad = graphic_verdict(th) if th else "undecodable"
        if bad:
            return {"ok": False, "why": bad, "w": sz[0], "h": sz[1]}
    return out


def preview(website: str) -> dict:
    """The phone's whole flow for one website. Always returns a dict with 'status'."""
    why = blocked_reason(website)
    if why:
        return {"status": "skipped", "why": why}
    start = page_uri(website)
    try:
        st, ct, _, body, final = _get(start, MAX_HTML, "text/html,application/xhtml+xml")
    except Exception as e:
        kind = type(e).__name__
        if isinstance(e, urllib.error.URLError) and isinstance(e.reason, (ssl.SSLError, ssl.CertificateError)):
            kind = "tls"
        elif isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e):
            kind = "timeout"
        elif isinstance(e, urllib.error.URLError):
            kind = "connect"
        return {"status": "fetch_failed", "why": kind}
    if st != 200:
        return {"status": "fetch_failed", "why": f"http_{st // 100}xx"}
    if "html" not in ct.lower() and ct:
        return {"status": "fetch_failed", "why": "not_html"}
    fh = (urllib.parse.urlsplit(final).hostname or "")
    if blocked_reason(final):
        return {"status": "skipped", "why": "redirect_blocked"}
    html = body.decode(_charset(ct, body), "replace")
    p = parse_html(html, final)
    if SPAM_TEXT.search(p["text"]):
        return {"status": "none", "why": "spam_page", "host": fh, "found": len(p["photos"]), "rejected": {}}
    rejected = collections.Counter()
    photo = None
    logos = list(p["logos"])
    tried = 0
    for u in p["photos"]:
        why = url_reject(u, p["icons"], True)
        if why is None and is_logoish(u):
            logos.insert(0, u)
            rejected["logoish_to_logo"] += 1
            continue
        if why:
            rejected[why] += 1
            continue
        if tried >= MAX_PHOTO_TRIES:
            break
        tried += 1
        r = check_image(u, True)
        if r["ok"] and r["square"]:  # a near-square og:image is the site's logo / avatar: a logo, not the hero
            logos.insert(0, u)
            rejected["square_to_logo"] += 1
            continue
        if r["ok"]:
            photo = {"url": u, "w": r["w"], "h": r["h"]}
            break
        rejected[r["why"]] += 1
    out = {"status": "ok" if photo else "none", "host": fh, "found": len(p["photos"]), "rejected": dict(rejected)}
    if photo:
        out["photo"] = photo
        return out
    ltried = 0
    for u in logos:
        why = url_reject(u, p["icons"], False)
        if why:
            rejected[why] += 1
            continue
        if ltried >= MAX_LOGO_TRIES:
            break
        ltried += 1
        r = check_image(u, False)
        if r["ok"]:
            out["status"] = "logo"
            out["logo"] = {"url": u, "w": r["w"], "h": r["h"]}
            break
        rejected["logo_" + r["why"]] += 1
    out["rejected"] = dict(rejected)
    if out["status"] == "none":
        out["why"] = "no_candidate" if not p["photos"] and not logos else "all_rejected"
    return out


# ── the tiles: stats, sample ──────────────────────────────────────────────────────────────────────────────────
GROUPS = {
    "food": {"restaurant", "grill", "seafood", "koshary", "fast_food", "chicken", "shawarma", "foul_taameya", "food_court",
             "pizza", "burger", "bakery", "sweets", "juice_bar", "ice_cream"},
    "cafe": {"cafe", "coffee_shop", "ahwa", "lounge"},
    "health": {"hospital", "pharmacy", "clinic", "dentist", "dental_clinic", "doctor", "eye_clinic", "medical_center",
               "health_unit", "medical_lab", "radiology", "veterinary"},
    "shopping": {"mall", "supermarket", "hypermarket", "grocery", "convenience", "kiosk", "market", "cold_store", "butcher",
                 "bookshop", "florist", "mobile_shop"},
    "hotel": {"hotel"},
    "worship": {"mosque", "church"},
    "edu": {"school", "university"},
    "fuel": {"gas_station"},
    "bank": {"bank", "atm", "exchange"},
    "auto": {"car_repair", "transmission_repair", "body_shop", "oil_change", "tyre_shop", "battery_shop", "car_wash",
             "roadside_assistance"},
    "gov": {"government_office", "government", "townhall", "ministry", "police", "courthouse", "post_office",
            "civil_registry", "traffic_department"},
    "culture": {"museum", "historic_site", "monument", "attraction", "park"},
}
CAT_GROUP = {c: g for g, cs in GROUPS.items() for c in cs}


def _tiles(d: str):
    for f in sorted(glob.glob(os.path.join(d, "t*.sqlite"))):
        yield f


def read_places(tiles_dir: str) -> dict:
    """pid → {website, cat, gov, photo(bool), logo(bool), name}, POIs only (kind 0), de-duplicated by pid."""
    out: dict = {}
    for f in _tiles(tiles_dir):
        c = sqlite3.connect(f)
        has_media = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        photo_ids = set(r[0] for r in c.execute("select distinct id from photo")) if "photo" in has_media else set()
        media = {}
        if "media" in has_media:
            media = {r[0]: (bool(r[1]), bool(r[2])) for r in c.execute("select id, img, logo from media")}
        for (i, pid, cat, scat, gov, web, nm, ne, lat, lng) in c.execute(
                "select id, pid, cat, scat, gov, website, name_ar, name_en, lat, lng from place where kind = 0"):
            m = media.get(i, (False, False))
            has_photo = i in photo_ids or m[0]
            has_logo = m[1]
            r = out.get(pid)
            rec = {"pid": pid, "website": web, "cat": scat or cat, "gov": gov, "photo": has_photo, "logo": has_logo,
                   "name": ne or nm}
            if r is None:
                out[pid] = rec
            else:  # the same place in two tiles: keep what either knows
                r["photo"] |= has_photo
                r["logo"] |= has_logo
                r["website"] = r["website"] or web
        c.close()
    return out


def cmd_stats(a) -> dict:
    places = read_places(a.tiles)
    n = len(places)
    web = [p for p in places.values() if p["website"]]
    skipped = collections.Counter(blocked_reason(p["website"]) or "contactable" for p in web)
    cand = [p for p in web if not blocked_reason(p["website"]) and not p["photo"]]
    st = {"pois": n, "with_photo": sum(p["photo"] for p in places.values()), "with_website": len(web),
          "website_by_status": dict(skipped), "website_contactable": skipped.get("contactable", 0),
          "website_no_photo": len(cand), "website_no_photo_or_logo": sum(1 for p in cand if not p["logo"]),
          "by_group": {g: sum(1 for p in cand if CAT_GROUP.get(p["cat"], "other") == g) for g in [*GROUPS, "other"]}}
    json.dump(st, open(a.out, "w"), indent=1) if a.out else None
    print(json.dumps(st, indent=1))
    return st


def cmd_sample(a) -> None:
    places = read_places(a.tiles)
    cand = [p for p in places.values() if p["website"] and not blocked_reason(p["website"]) and not p["photo"]]
    rnd = random.Random(a.seed)
    # stratify on (group, governorate): round-robin over shuffled strata so no category or governorate dominates
    strata: dict = collections.defaultdict(list)
    for p in cand:
        strata[(CAT_GROUP.get(p["cat"], "other"), p["gov"] or "")].append(p)
    for v in strata.values():
        rnd.shuffle(v)
    keys = sorted(strata)
    rnd.shuffle(keys)
    pick, seen_hosts = [], set()
    while len(pick) < a.n and keys:
        for k in list(keys):
            while strata[k]:
                p = strata[k].pop()
                h = domain_of(p["website"])
                if h in seen_hosts:  # one place per site: chains share a site and would count it many times
                    continue
                seen_hosts.add(h)
                pick.append(p)
                break
            if not strata[k]:
                keys.remove(k)
            if len(pick) >= a.n:
                break
    json.dump(pick, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"sampled {len(pick)} of {len(cand)} candidates; groups:",
          dict(collections.Counter(CAT_GROUP.get(p['cat'], 'other') for p in pick)))


def cmd_run(a) -> None:
    sample = json.load(open(a.sample, encoding="utf-8"))
    done: dict = {}
    if a.resume and os.path.exists(a.out):
        done = {r["pid"]: r for r in json.load(open(a.out, encoding="utf-8"))}
    todo = [p for p in sample if p["pid"] not in done]
    res = list(done.values())
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=min(4, a.workers)) as ex:
        futs = {ex.submit(preview, p["website"]): p for p in todo}
        for n, f in enumerate(cf.as_completed(futs), 1):
            p = futs[f]
            try:
                r = f.result()
            except Exception as e:  # never let one site stop the run
                r = {"status": "fetch_failed", "why": "crash:" + type(e).__name__}
            res.append({**p, **r})
            if n % 25 == 0:
                print(f"{n}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
                json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("done", len(res))


def cmd_report(a) -> None:
    res = json.load(open(a.results, encoding="utf-8"))
    stats = json.load(open(a.stats)) if a.stats else None
    n = len(res)
    c = collections.Counter(r["status"] for r in res)
    fetched = n - c["fetch_failed"] - c["skipped"]
    why_f = collections.Counter(r.get("why") for r in res if r["status"] == "fetch_failed")
    rej = collections.Counter()
    for r in res:
        for k, v in (r.get("rejected") or {}).items():
            rej[k] += v
    print(f"sample {n}: fetched {fetched} ({fetched / n:.1%}); photo {c['ok']} ({c['ok'] / n:.1%}); "
          f"logo only {c['logo']} ({c['logo'] / n:.1%}); nothing {c['none']} ({c['none'] / n:.1%}); "
          f"fetch failed {c['fetch_failed']} ({c['fetch_failed'] / n:.1%}); skipped {c['skipped']}")
    print("fetch failures:", dict(why_f))
    print("rejected candidates by rule:", dict(rej.most_common()))
    print("nothing, by cause:", dict(collections.Counter(r.get("why") for r in res if r["status"] == "none")))
    by = collections.defaultdict(lambda: [0, 0])
    for r in res:
        g = CAT_GROUP.get(r["cat"], "other")
        by[g][0] += 1
        by[g][1] += r["status"] == "ok"
    print("photo yield by group:", {g: f"{b}/{a_}" for g, (a_, b) in sorted(by.items())})
    # photos shared by several sites are platform defaults: candidates for GENERIC_URL
    share = collections.defaultdict(set)
    for r in res:
        if r["status"] == "ok":
            u = r["photo"]["url"].split("?")[0]
            share[u].add(r.get("host"))
    dup = {u: len(h) for u, h in share.items() if len(h) >= 2}
    print("photo URLs on >= 2 sites (generic defaults?):", dup)
    if stats:
        base = stats["website_no_photo"]
        # the sample is stratified (≈ equal per group); the population is not (61 % "other"): weight each group
        pop = stats["by_group"]
        gain_photo = gain_logo = 0.0
        for g, k in pop.items():
            rows = [r for r in res if CAT_GROUP.get(r["cat"], "other") == g]
            if not rows:
                continue
            gain_photo += k * sum(r["status"] == "ok" for r in rows) / len(rows)
            gain_logo += k * sum(r["status"] == "logo" for r in rows) / len(rows)
        print(f"places with website, contactable, no photo: {base}")
        print(f"extrapolated (group-weighted): +{round(gain_photo)} places gain a photo ({gain_photo / base:.1%}); "
              f"+{round(gain_logo)} a logo only; {round(gain_photo + gain_logo)} a photo or a logo")
        print(f"  unweighted: +{round(base * c['ok'] / n)} photos")
        print(f"  = {gain_photo / stats['pois']:.2%} of all {stats['pois']} POIs gain a photo "
              f"(today {stats['with_photo'] / stats['pois']:.2%})")


# ── selftest: the canned cases test/website_preview_test.dart holds the same values for ───────────────────────
CANNED = """<!doctype html><html><head>
<meta charset="utf-8">
<meta property="og:title" content="Cafe Ahwa &amp; Co">
<meta property="og:image" content="/img/hero.jpg?v=2&amp;w=1200">
<meta property="og:image:secure_url" content="https://cdn.example.com/hero-secure.jpg">
<meta name="twitter:image" content='//static.example.com/tw.png'>
<link rel="icon" href="/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/i32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-180.png">
<link rel="apple-touch-icon" sizes="57x57" href="/apple-57.png">
<script type="application/ld+json">{"@type":"Restaurant","logo":{"@type":"ImageObject","url":"/brand/logo.png"},"image":["https://example.com/ld1.jpg"]}</script>
</head><body></body></html>"""


def selftest() -> None:
    p = parse_html(CANNED, "https://example.com/menu/")
    assert p["photos"] == ["https://cdn.example.com/hero-secure.jpg", "https://example.com/img/hero.jpg?v=2&w=1200",
                           "https://static.example.com/tw.png", "https://example.com/ld1.jpg"], p["photos"]
    assert p["logos"] == ["https://example.com/brand/logo.png", "https://example.com/apple-180.png",
                          "https://example.com/apple-57.png", "https://example.com/i32.png",
                          "https://example.com/favicon.ico"], p["logos"]
    assert p["title"] == "Cafe Ahwa & Co" or p["title"] is None
    assert blocked_reason("facebook.com/x") == "blocked_host" and blocked_reason("linktr.ee/a") == "blocked_host"
    assert blocked_reason("https://مطعم.eg/") == "idn_host"
    assert blocked_reason("http://192.168.1.4/x") == "ip_host" and blocked_reason("localhost") == "bad_host"
    assert blocked_reason("example.com") is None and page_uri("example.com/a") == "https://example.com/a"
    assert cache_key("https://www.Example.com/a/") == "example.com/a"
    assert judge_size(1200, 630, True) is None and judge_size(299, 400, True) == "too_small"
    assert judge_size(1000, 200, True) == "aspect" and judge_size(120, 120, False) is None
    assert judge_size(64, 64, False) == "too_small"
    png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 640, 480) + b"\0" * 8
    assert image_size(png) == (640, 480)
    assert url_reject("https://x.com/a/favicon.png", [], True) == "favicon_as_photo"
    assert url_reject("https://x.com/a/pixel.gif", [], True) == "tracking"
    assert url_reject("https://x.com/a.svg", [], False) == "unrenderable"
    assert graphic_verdict([(250, 250, 250)] * 80 + [(10, 10, 10)] * 20) == "graphic"
    noise = [((i * 37) % 256, (i * 91) % 256, (i * 53) % 256) for i in range(THUMB * THUMB)]
    assert graphic_verdict(noise) is None
    assert SPAM_TEXT.search("Situs Slot Gacor Online") and SPAM_TEXT.search("Buy this domain today")
    assert not SPAM_TEXT.search("Cafe Ahwa - best coffee and time slot booking")
    assert url_reject("https://cdn.dnom.com/x.png", [], True) == "generic_default"
    print("selftest ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("stats"); s.add_argument("--tiles", required=True); s.add_argument("--out")
    s = sub.add_parser("sample"); s.add_argument("--tiles", required=True); s.add_argument("--n", type=int, default=300)
    s.add_argument("--seed", type=int, default=7); s.add_argument("--out", required=True)
    s = sub.add_parser("run"); s.add_argument("--sample", required=True); s.add_argument("--out", required=True)
    s.add_argument("--workers", type=int, default=4); s.add_argument("--resume", action="store_true")
    s = sub.add_parser("report"); s.add_argument("--results", required=True); s.add_argument("--stats")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.cmd == "stats":
        cmd_stats(a)
    elif a.cmd == "sample":
        cmd_sample(a)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "report":
        cmd_report(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
