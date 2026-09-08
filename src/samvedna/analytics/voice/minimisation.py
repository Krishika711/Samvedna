"""Detecting the register in which people say they are fine.

Personnel minimise. *"I'm managing."* *"It's nothing, sir."* Sometimes that is
simply true, and most of the time it is. The point of detecting the register is
not to disbelieve it — it is to know **which sentence to look at the voice
underneath**, so that the acoustic measurement is anchored to a claim rather
than floating free over a whole conversation.

Lexical, not neural, and deliberately so. A sentence-transformer would catch
paraphrase better and would also mean that "why was this flagged?" answers with
a cosine distance nobody can interrogate. Here the answer is "you said 'I'm
fine' and that is in the cue bank", which a person can argue with. The seam is a
Protocol, so a semantic matcher drops in behind it for anybody willing to own
the calibration.

Negation is handled, because "I'm **not** fine" is the opposite of a
minimisation and scoring it as one would be worse than missing it entirely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["CueMatch", "detect", "CUES", "HEDGES", "NEGATORS"]

# Weight is how strongly the phrase signals the minimising register, not how
# worried anybody should be. "I'm fine" is a stronger register marker than
# "it's alright" because it is more often a deflection than a description.
CUES: tuple[tuple[str, str, float], ...] = (
    (r"\bi'?m fine\b", "wellbeing", 0.80),
    (r"\bi'?m ok(ay)?\b", "wellbeing", 0.70),
    (r"\bi'?m alright\b", "wellbeing", 0.70),
    (r"\bnothing (to worry|serious|much)\b", "dismissal", 0.75),
    (r"\bit'?s nothing\b", "dismissal", 0.75),
    (r"\bno (problem|issue)s?\b", "dismissal", 0.65),
    (r"\bi'?m managing\b", "coping", 0.70),
    (r"\bi'?ll (manage|cope|be fine)\b", "coping", 0.70),
    (r"\bgetting (by|on with it)\b", "coping", 0.72),
    (r"\bused to it\b", "normalising", 0.68),
    (r"\bpart of the job\b", "normalising", 0.72),
    (r"\bevery(one|body) (has|goes through)\b", "normalising", 0.65),
    (r"\bjust (tired|a bit tired|stress)\b", "attribution", 0.66),
    (r"\bnot (a )?big deal\b", "dismissal", 0.70),
    (r"\bdon'?t (worry|make a fuss)\b", "deflection", 0.72),
    (r"\bi'?ll (be )?(sort|sorted) it\b", "coping", 0.62),
)

# A hedge *raises* confidence that the claim is a register move rather than a
# report: "I'm fine, mostly" is doing more work than "I'm fine".
HEDGES: tuple[str, ...] = (
    "mostly", "more or less", "i suppose", "i think", "kind of", "sort of",
    "mainly", "generally", "usually", "on the whole", "i guess",
)
# Comparatives and contrasts do the same.
CONTRASTS: tuple[str, ...] = ("but", "though", "although", "even if", "apart from")
# ...and these cancel it outright.
NEGATORS: tuple[str, ...] = ("not", "n't", "hardly", "never", "far from", "anything but")

HEDGE_BONUS = 0.10
CONTRAST_BONUS = 0.08
MIN_CONFIDENCE = 0.50


@dataclass(frozen=True, slots=True)
class CueMatch:
    """One minimising claim, with the span that produced it.

    `quote` is kept so an officer or clinician can see the actual sentence. It
    is *not* written to the audit ledger — Workflow D is explicit that the
    content of a welfare conversation is never stored, and a transcript line is
    content.
    """

    phrase: str
    kind: str
    confidence: float
    quote: str
    start_char: int

    @property
    def strong(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE


# Negation scope ends at a clause boundary, and a contrast conjunction is one.
# Without this, "I haven't slept but I'll manage" reads as negated and the
# minimisation is missed — yet that sentence is a textbook minimisation, and the
# "but" is precisely what makes it one. Splitting only on sentence punctuation
# let "haven't" reach across the clause and cancel a cue it has nothing to do with.
CLAUSE_BREAK = re.compile(r"[.!?;,]|\b(?:but|though|although|however|still|yet)\b")


def _negated(text: str, start: int) -> bool:
    """Is the cue inside the scope of a negation?

    Looks back to the nearest clause boundary, then over the six words before
    the cue — enough for "I'm not really fine", and not enough to reach into an
    unrelated clause.
    """
    before = text[:start].lower()
    clause = CLAUSE_BREAK.split(before)[-1] or ""
    tail = " ".join(clause.split()[-6:])
    return any(neg in tail for neg in NEGATORS)


def detect(utterance: str) -> tuple[CueMatch, ...]:
    """Every minimising claim in one utterance, negation removed."""
    if not utterance or not utterance.strip():
        return ()
    lowered = utterance.lower()
    out: list[CueMatch] = []

    for pattern, kind, base in CUES:
        for match in re.finditer(pattern, lowered):
            if _negated(lowered, match.start()):
                continue
            confidence = base
            if any(h in lowered for h in HEDGES):
                confidence += HEDGE_BONUS
            if any(f" {c} " in f" {lowered} " for c in CONTRASTS):
                confidence += CONTRAST_BONUS
            out.append(
                CueMatch(
                    phrase=match.group(0),
                    kind=kind,
                    confidence=round(min(1.0, confidence), 3),
                    quote=utterance.strip(),
                    start_char=match.start(),
                )
            )

    # One finding per utterance: the strongest cue. Several cues in one sentence
    # are one claim said several ways, not several claims.
    if not out:
        return ()
    best = max(out, key=lambda c: c.confidence)
    return (best,)
