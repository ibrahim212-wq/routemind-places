"""Generated names: an Arabic form for a place known only by its Latin name, and a Latin form for one known only in
Arabic — so «كافيه سترلا» finds "Strella Cafe" and "el shabrawy" finds «الشبراوي» where the cross-script consonant
skeleton alone does not (docs/place-search-2026-10.md §11c).

No model and no network: the dictionary is LEARNED from the index itself, from the ~200k places that carry both an
Arabic and a Latin name (OSM name:ar + name:en, Wikidata labels, bilingual Facebook pages). A Latin word and an
Arabic word are each other's form when they keep appearing in the same place's two names: ≥ MIN_PAIRS places, and
each is the other's dominant partner (≥ MIN_SHARE of the places either word appears in with a partner). That pairs
transliterations the skeleton misses ("cilantro" ⇄ «سيلانترو», "gad" ⇄ «جاد»), Egyptian spellings ("abou" ⇄
«ابو») and plain translations ("pyramids" ⇄ «الاهرامات», "pharmacy" ⇄ «صيدليه») — whatever the data agrees on.

A generated name holds only the words the dictionary knows (in the name's order) and is kept apart from the real
alternative names (`Place.gen_alt`, written after a "\x1e" in the tile's `alt`): the engine reads it at f_alt × f_gen and
as a FALLBACK match class, so a generated match never outranks a real one, and the app never displays it. It is
generated only when it adds a word the place's own names do not already match (a different word AND a different
skeleton)."""
from __future__ import annotations

from collections import Counter, defaultdict

from . import textnorm as tn

MIN_PAIRS = 4       # places a word pair must share
MIN_SHARE = 0.5     # …and each word's share of its partnered appearances that go to the other
MIN_LEN = 2         # shorter words (initials, "el") pair with everything


def _words(text: str | None, script: str) -> list[str]:
    out = []
    for t in tn.tokens(text or ""):
        if tn.is_stopword(t) or t.isdigit() or len(t) < MIN_LEN:
            continue
        if (script == "ar") != tn.is_arabic_token(t):
            continue
        out.append(t)
    return out


def _key(t: str) -> str:
    return tn.stems(t)[-1]


class Dictionary:
    def __init__(self, ar2la: dict[str, str], la2ar: dict[str, str]):
        self.ar2la, self.la2ar = ar2la, la2ar

    @classmethod
    def learn(cls, pairs) -> "Dictionary":
        """`pairs`: (Arabic name, Latin name) of the same place."""
        co: Counter = Counter()
        n_ar: Counter = Counter()
        n_la: Counter = Counter()
        for ar, la in pairs:
            A = {_key(t) for t in _words(ar, "ar")}
            L = {_key(t) for t in _words(la, "la")}
            if not A or not L or len(A) > 6 or len(L) > 6:
                continue
            for a in A:
                n_ar[a] += 1
            for b in L:
                n_la[b] += 1
            for a in A:
                for b in L:
                    co[(a, b)] += 1
        best_a: dict[str, tuple[int, str]] = {}
        best_b: dict[str, tuple[int, str]] = {}
        for (a, b), n in co.items():
            if n < MIN_PAIRS:
                continue
            if n > best_a.get(a, (0, ""))[0] or (n == best_a[a][0] and b < best_a[a][1]):
                best_a[a] = (n, b)
            if n > best_b.get(b, (0, ""))[0] or (n == best_b[b][0] and a < best_b[b][1]):
                best_b[b] = (n, a)
        ar2la, la2ar = {}, {}
        for a, (n, b) in best_a.items():
            if best_b.get(b, (0, ""))[1] != a:
                continue  # not mutual
            if n / n_ar[a] < MIN_SHARE or n / n_la[b] < MIN_SHARE:
                continue
            ar2la[a], la2ar[b] = b, a
        return cls(ar2la, la2ar)

    def generate(self, name: str | None, script: str, own: list[str]) -> str | None:
        """The other script's form of `name` (script = the name's own: 'ar' | 'la'), or None when it adds nothing
        to the place's `own` names."""
        table = self.ar2la if script == "ar" else self.la2ar
        out = []
        for t in _words(name, script):
            g = table.get(_key(t))
            if g and g not in out:
                out.append(g)
        if not out:
            return None
        have = {_key(t) for n in own for t in tn.tokens(n)}
        have_sk = {s for n in own for t in tn.tokens(n) for s in tn.skeletons(t) if len(s) >= 2}
        if all(g in have or (set(s for s in tn.skeletons(g) if len(s) >= 2) & have_sk) for g in out):
            return None
        return " ".join(out)


def generate_all(places, report: dict) -> None:
    """Learn the dictionary from the merged POIs that carry both names, then give every POI with only one script
    an alternative name in the other."""
    pois = [p for p in places if p.kind == "poi"]
    d = Dictionary.learn((p.name_ar, p.name_en) for p in pois if p.name_ar and p.name_en)
    made: Counter = Counter()
    for p in pois:
        if p.name_ar and p.name_en:
            continue
        own = [x for x in (p.name_ar, p.name_en, *p.alt) if x]
        g = d.generate(p.name_ar, "ar", own) if p.name_ar else d.generate(p.name_en, "la", own)
        if g:
            # kept apart from the real alternative names: the tile writes them after a "\x1e" and the engine reads
            # a match on them as a fallback (match class 1), never as the place's real name
            p.gen_alt = list(p.gen_alt) + [g]
            made["latin_for_arabic_only" if p.name_ar else "arabic_for_latin_only"] += 1
    report["generated_names"] = {"dictionary": len(d.ar2la), **made,
                                 "pois_without_arabic": sum(1 for p in pois if not p.name_ar),
                                 "pois_without_latin": sum(1 for p in pois if not p.name_en)}
