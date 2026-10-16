"""Freely licensed photos for places (docs/place-ugc-2026-10.md §4).

A place gets ONE Wikimedia Commons photo when the open data names one:
  * OSM's `wikimedia_commons=File:…` (or an `image=` pointing at a Commons file) on any merged member;
  * else Wikidata's P18 (image) of the place's Wikidata item (OSM `wikidata=` tag or the Wikidata source).
Every chosen file is then looked up on Commons for what its licence requires us to show — the author
(`Artist`) and the licence (`LicenseShortName`, `LicenseUrl`). A file whose licence or author Commons
does not state is dropped: no photo without its credit. Nothing is downloaded; the phone shows Commons'
own thumbnails.

    collect(places, osm_commons) → {pid: Media}

Network: SPARQL (P18 for the QIDs, 400 per query) and the Commons API (50 titles per call), both with
the pipeline's User-Agent and retries. Any failure leaves the photos out — never the build.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import fetch as F

FREE = re.compile(r"^(cc[ -]?by|cc0|cc[ -]?zero|public domain|pd|gfdl|attribution|copyrighted free use|fal|ogl)", re.I)


@dataclass
class Media:
    wd: str | None
    img: str | None = None
    by: str | None = None
    lic: str | None = None
    lic_url: str | None = None


def log(*a):
    print("[media]", *a, flush=True)


def _get_json(url: str, accept: str = "application/json") -> dict:
    def once():
        req = urllib.request.Request(url, headers={"User-Agent": F.UA, "Accept": accept})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    return F._retry(url[:60], once, tries=3)


def file_name(v: str | None) -> str | None:
    """«File:Al-Azhar 2.jpg», a Commons URL or Special:FilePath URL → «Al-Azhar 2.jpg»."""
    if not v:
        return None
    v = v.strip()
    m = re.search(r"(?:commons\.wikimedia\.org/wiki/(?:Special:FilePath/|File:)|^File:)(.+)$", v, re.I)
    if not m:
        return None
    name = urllib.parse.unquote(m.group(1)).replace("_", " ").split("?")[0].strip()
    return name if re.search(r"\.(jpe?g|png|webp|tiff?|gif)$", name, re.I) else None


def p18(qids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(qids), 400):
        chunk = qids[i:i + 400]
        q = "SELECT ?item ?img WHERE { VALUES ?item { %s } ?item wdt:P18 ?img }" % " ".join("wd:" + x for x in chunk)
        try:
            res = _get_json("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q),
                            "application/sparql-results+json")
        except OSError as e:
            log("P18 batch skipped:", str(e)[:120])
            continue
        for b in res["results"]["bindings"]:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            name = file_name(b["img"]["value"])
            if name and qid not in out:
                out[qid] = name
        time.sleep(1)
    return out


def _plain(v: str | None) -> str | None:
    if not v:
        return None
    t = re.sub(r"<[^>]+>", "", html.unescape(v))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:120] or None


def credits(files: list[str]) -> dict[str, tuple[str, str, str | None]]:
    """file → (author, licence, licence URL) for files Commons states a free licence and an author for."""
    out = {}
    for i in range(0, len(files), 50):
        chunk = files[i:i + 50]
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=extmetadata"
               "&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|Credit&maxlag=5&titles="
               + urllib.parse.quote("|".join("File:" + f for f in chunk)))
        try:
            res = _get_json(url)
        except OSError as e:
            log("Commons batch skipped:", str(e)[:120])
            continue
        norm = {n["to"]: n["from"] for n in res.get("query", {}).get("normalized", [])}
        for page in res.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
            lic = _plain(info.get("LicenseShortName", {}).get("value"))
            who = _plain(info.get("Artist", {}).get("value")) or _plain(info.get("Credit", {}).get("value"))
            if not lic or not who or not FREE.match(lic):
                continue
            title = norm.get(page.get("title", ""), page.get("title", ""))
            name = title[5:] if title.startswith("File:") else title
            lurl = info.get("LicenseUrl", {}).get("value")
            out[name] = (who, lic, lurl if lurl and lurl.startswith("http") else None)
        time.sleep(0.5)
    return out


def collect(places, osm_commons: dict[str, str]) -> dict[str, Media]:
    """`osm_commons`: place pid → a Commons file named by OSM on one of its members."""
    t0 = time.time()
    media = {p.pid: Media(wd=p.wd) for p in places if p.wd}
    want = sorted({p.wd for p in places if p.wd and p.pid not in osm_commons})
    from_wd = p18(want) if want else {}
    for p in places:
        img = osm_commons.get(p.pid) or (from_wd.get(p.wd) if p.wd else None)
        if img:
            media.setdefault(p.pid, Media(wd=p.wd)).img = img
    files = sorted({m.img for m in media.values() if m.img})
    cr = credits(files)
    kept = 0
    for m in media.values():
        if m.img and m.img in cr:
            m.by, m.lic, m.lic_url = cr[m.img]
            kept += 1
        else:
            m.img = None
    log(f"{len(media)} places with a Wikidata item or a Commons file, {len(files)} files, "
        f"{kept} with a stated free licence and author ({time.time() - t0:.0f}s)")
    return {k: v for k, v in media.items() if v.wd or v.img}
