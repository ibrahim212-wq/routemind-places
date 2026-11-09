"""LiveGate — when the app asks a live place provider (docs/search-goal.md "Smart live fallback").

ONE rule, four copies: this reference ⇄ lib/features/search/domain/live_gate.dart (phone) ⇄
android/.../places/PlaceLiveGate.kt (Android Auto, Add Stop) ⇄ ios/Runner/Places/PlaceLive.swift `PlaceLiveGate` (CarPlay,
Add Stop). `python tool/place_live_gate_parity.py` holds the constants and replays fixtures/live_gate_cases.json here; the
Dart, JVM and Swift tests replay the same file.

The hosts call `decide` once the user has PAUSED typing for PAUSE_MS with the own answer for that text in hand, cancel any
call in flight on the next keystroke, and call `tap` when a row is picked. The gate answers whether to ask, and why:

  * never before MIN_CHARS typed characters, never twice for the same text in one session, never after a tap, and at most
    MAX_ASKS per session (a long typing run cannot spend the free quota on one search);
  * WEAK: the own answer is weak — nothing, no tiles around yet, a name match under WEAK_TEXT, or a kind / chain answer
    (no text score) with fewer than MIN_KIND_RESULTS places;
  * KEPT: a STRONG own answer was on screen at an earlier pause, the user did not tap it and kept typing at least
    KEPT_CHARS more characters on the same text (what they want is not in our list).
"""
from __future__ import annotations

MIN_CHARS = 3
PAUSE_MS = 500
KEPT_CHARS = 2
MAX_ASKS = 5
WEAK_TEXT = 0.75
MIN_KIND_RESULTS = 3
MEMORY_MAX_S = 600


def norm(q: str) -> str:
    return " ".join(q.strip().lower().split())


def weak(count: int, top_text: float, coverage: str) -> bool:
    """The own answer is weak (the PlaceLive rule, shared with the Apple Maps section)."""
    if count == 0 or coverage == "none":
        return True
    if top_text <= 0.0:
        return count < MIN_KIND_RESULTS
    return top_text < WEAK_TEXT or coverage != "full"


class LiveGate:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.strong_shown: str | None = None
        self.tapped = False
        self.asked: set[str] = set()

    def tap(self) -> None:
        self.tapped = True

    def decide(self, q: str, count: int, top_text: float, coverage: str) -> str | None:
        """'weak' / 'kept' = ask, with that reason; None = do not ask."""
        n = norm(q)
        if self.strong_shown is not None and not n.startswith(self.strong_shown):
            self.strong_shown = None  # the text was edited back: a new run
        is_weak = weak(count, top_text, coverage)
        reason = None
        if len(n) < MIN_CHARS or self.tapped or n in self.asked or len(self.asked) >= MAX_ASKS:
            reason = None
        elif is_weak:
            reason = "weak"
        elif self.strong_shown is not None and len(n) - len(self.strong_shown) >= KEPT_CHARS:
            reason = "kept"
        if reason is not None:
            self.asked.add(n)
        if not is_weak and (self.strong_shown is None or reason == "kept"):
            self.strong_shown = n
        return reason


# ── the fixture every copy replays (fixtures/live_gate_cases.json; also text_cases.json ["live_gate"] for RunnerTests) ──
def S(q: str, n: int, t: float, c: str) -> dict:
    return {"q": q, "n": n, "t": t, "c": c}


SESSIONS = [
    ('short text is never asked', [S('تو', 0, 0, 'full'), S('Tو', 0, 0, 'none')]),
    ('weak at the third character', [S('توم', 0, 0, 'full'), S('تومه', 0, 0, 'full')]),
    ('weak name match, partial tiles', [S('harrods', 2, 0.5, 'full'), S('harrods p', 3, 0.8, 'partial')]),
    ('kind answer: few places is weak, many is not', [S('سباك', 2, 0, 'full'), S('صيدلية', 9, 0, 'full')]),
    ('strong then kept typing two characters', [S('كشري', 8, 0.95, 'full'), S('كشري ت', 8, 0.9, 'full'), S('كشري تو', 8, 0.9, 'full'), S('كشري تومه', 8, 0.9, 'full')]),
    ('strong then one character is not enough', [S('مول', 9, 0.9, 'full'), S('مولا', 9, 0.9, 'full'), S('مولات', 9, 0.9, 'full')]),
    ('a tap ends the session', [S('كشري', 8, 0.95, 'full'), {"tap": True}, S('كشري تومه', 0, 0, 'full')]),
    ('same text twice is asked once', [S('بلبن', 0, 0, 'full'), S('بلبن ', 0, 0, 'full'), S('BLBN', 0, 0, 'full'), S('blbn', 0, 0, 'full')]),
    ('edited back starts a new run', [S('مطعم', 9, 0.9, 'full'), S('مطعم كب', 9, 0.9, 'full'), S('مطع', 9, 0.9, 'full'), S('مطعم س', 9, 0.9, 'full'), S('مطعم سم', 9, 0.9, 'full')]),
    ('cap on asks per session', [S('abc0x', 0, 0, 'full'), S('abc1x', 0, 0, 'full'), S('abc2x', 0, 0, 'full'), S('abc3x', 0, 0, 'full'), S('abc4x', 0, 0, 'full'), S('abc5x', 0, 0, 'full'), S('abc6x', 0, 0, 'full')]),
    ('coverage none is weak even with rows', [S('زمالك', 4, 0.99, 'none')]),
    ('weak then strong then kept', [S('سنتر', 1, 0.4, 'full'), S('سنتر ت', 6, 0.9, 'full'), S('سنتر تعل', 6, 0.9, 'full')]),
    ('reset clears the session', [S('تومه', 0, 0, 'full'), {"reset": True}, S('تومه', 0, 0, 'full')]),
]


def fixture() -> dict:
    """The sessions with the reference's answer to every step (re-stated ON PURPOSE by `--write`)."""
    out = []
    for name, steps in SESSIONS:
        g = LiveGate()
        rows = []
        for st in steps:
            if st.get("tap"):
                g.tap()
                rows.append({"tap": True})
            elif st.get("reset"):
                g.reset()
                rows.append({"reset": True})
            else:
                rows.append({**st, "want": g.decide(st["q"], st["n"], st["t"], st["c"])})
        out.append({"name": name, "steps": rows})
    consts = {k: globals()[k] for k in ("MIN_CHARS", "PAUSE_MS", "KEPT_CHARS", "MAX_ASKS", "WEAK_TEXT", "MIN_KIND_RESULTS",
                                        "MEMORY_MAX_S")}
    return {"constants": consts, "sessions": out}


if __name__ == "__main__":
    import json
    import os
    import sys
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    fx = fixture()
    if "--write" in sys.argv:
        with open(os.path.join(here, "live_gate_cases.json"), "w", encoding="utf-8") as f:
            json.dump(fx, f, ensure_ascii=False, indent=1)
        tc = os.path.join(here, "text_cases.json")
        with open(tc, encoding="utf-8") as f:
            d = json.load(f)
        d["live_gate"] = fx
        with open(tc, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print("[live_gate] wrote", sum(len(s["steps"]) for s in fx["sessions"]), "steps")
    else:
        with open(os.path.join(here, "live_gate_cases.json"), encoding="utf-8") as f:
            ok = json.load(f) == fx
        print("[live_gate]", "OK" if ok else "FIXTURE STALE (python -m tools.place_index.live_gate --write)")
        sys.exit(0 if ok else 1)
