"""Turning the floor's opinions into a ranking.

This was first built to answer "should we act?" — a gate whose default was
silence. That is the wrong question for a system whose job is to hold a
portfolio. An investor does not ask permission to be invested; they ask how the
money should be distributed, and holding cash is one of the answers rather than
what happens when nobody is sure.

So the seats produce a **score per symbol** instead of one verdict per session.
A score is a relative statement — this looks better than that — which is what an
allocator needs. Whether to hold cash then becomes an explicit decision about
conviction across the whole ranking, not a side effect of a quorum rule.

What did not change: every score traces to real analysis, a seat with no data
abstains rather than guessing, and the abstentions stay visible in the result.

**Score and confidence are separate numbers and mean different things.** The
score is where the floor landed. The confidence is how much they agreed and how
sure each of them was. A high score held with low confidence deserves a smaller
position than the same score held with high confidence, and collapsing the two
into one number destroys exactly the information a position sizer needs.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from .models import Verdict

# Below this many voting seats, a score is one or two opinions wearing the
# clothes of a committee.
DEFAULT_MIN_SEATS = 2


@dataclass
class Contribution:
    """One seat's input to one symbol's score."""

    seat: str
    stance: str
    confidence: float
    weight: float
    score: float
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SymbolScore:
    """How the floor rates one symbol, and who said what.

    `score` runs 0..1 on the stance scale: 1.0 is unanimous conviction to own it,
    0.0 unanimous conviction to be out, 0.5 neutral.
    """

    symbol: str
    score: float
    confidence: float
    seats_voting: int
    seats_abstained: int
    seats_unwired: int = 0
    contributions: list[Contribution] = field(default_factory=list)
    abstentions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rated(self) -> bool:
        """False when nobody could form a view, in which case it must not be ranked.

        An unrated symbol is not a symbol that scored 0.5. Ranking it as though it
        were puts a symbol nobody assessed in the middle of a list of symbols
        several people did, where it is indistinguishable from a genuine neutral.
        """
        return self.seats_voting > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contributions"] = [c.to_dict() for c in self.contributions]
        return payload


def score_symbol(
    symbol: str,
    verdicts: Sequence[Verdict],
    min_seats: int = DEFAULT_MIN_SEATS,
) -> SymbolScore:
    """Combine one symbol's verdicts into a score and a confidence."""
    voting = [v for v in verdicts if not v.abstained]
    abstained = [v for v in verdicts if v.abstained]
    unwired = [v for v in abstained if not v.counts_toward_quorum]

    notes: list[str] = []
    abstention_notes = [f"{v.seat}: {v.abstain_reason}" for v in abstained]

    if not voting:
        return SymbolScore(
            symbol=symbol,
            score=0.0,
            confidence=0.0,
            seats_voting=0,
            seats_abstained=len(abstained),
            seats_unwired=len(unwired),
            abstentions=abstention_notes,
            notes=["no seat could form a view; this symbol is unrated, not neutral"],
        )

    total_weight = sum(v.weight for v in voting)
    score = sum(v.directional_score * v.weight for v in voting) / total_weight

    # How much the floor agreed. Scores live in 0..1, so their standard deviation
    # is at most 0.5; doubling it maps total disagreement to 0.
    spread = statistics.pstdev([v.directional_score for v in voting]) if len(voting) > 1 else 0.0
    agreement = max(0.0, 1.0 - 2.0 * spread)

    average_conviction = sum(v.confidence * v.weight for v in voting) / total_weight

    # Seats that were configured but silent today dilute confidence. Seats that
    # were never wired at all do not: their silence says nothing about this
    # symbol, and counting it would make an unconfigured system look uncertain
    # rather than incomplete.
    eligible = [v for v in verdicts if v.counts_toward_quorum]
    participation = len(voting) / len(eligible) if eligible else 0.0

    confidence = agreement * average_conviction * participation

    if len(voting) < min_seats:
        notes.append(
            f"only {len(voting)} seat(s) voted, below the {min_seats} this ranking "
            "treats as a committee; read the score as one opinion"
        )
    if unwired:
        notes.append(
            f"{len(unwired)} seat(s) have no data source configured at all and were "
            "excluded from participation rather than counted as undecided"
        )

    return SymbolScore(
        symbol=symbol,
        score=round(score, 4),
        confidence=round(confidence, 4),
        seats_voting=len(voting),
        seats_abstained=len(abstained),
        seats_unwired=len(unwired),
        contributions=[
            Contribution(
                seat=v.seat,
                stance=v.stance,
                confidence=v.confidence,
                weight=v.weight,
                score=v.directional_score,
                rationale="; ".join(v.rationale),
            )
            for v in voting
        ],
        abstentions=abstention_notes,
        notes=notes,
    )


def rank(scores: Sequence[SymbolScore]) -> list[SymbolScore]:
    """Order rated symbols best first. Unrated ones are dropped, not sorted last.

    Sorting them last would still place them on the list, below a symbol scored
    0.1 by three seats. That reads as "we assessed this and it came last", which
    is the opposite of what happened.
    """
    rated = [s for s in scores if s.rated]
    return sorted(rated, key=lambda s: (-s.score, -s.confidence, s.symbol))
