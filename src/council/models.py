"""The data contracts, and the two rules that shape all of them.

**A delegate may only state a position it can cite.** Every verdict carries the
inputs that produced it and how fresh they were. This is not bookkeeping: in a
system where several independent analyses are combined into one number, the only
way to audit the number afterwards is to be able to take it apart.

**A delegate that cannot get real inputs abstains.** It does not substitute a
default, an estimate, or a neutral value. That sounds obvious and is routinely
violated, because abstaining is inconvenient: it leaves a hole in the tally, and
filling the hole with 0.5 makes the pipeline run. But a fabricated 0.5 is
indistinguishable from a measured 0.5 downstream, and the whole apparatus of
citation is worthless the moment one seat is allowed to make its number up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# The positions a delegate may take. ABSTAIN is a first-class outcome, not a
# failure mode: "I cannot tell" is a real and useful thing for an analyst to say.
BUY = "BUY"
HOLD = "HOLD"
REDUCE = "REDUCE"
EXIT = "EXIT"
ABSTAIN = "ABSTAIN"

VOTING_STANCES = (BUY, HOLD, REDUCE, EXIT)

# Directional value of each stance, deliberately coarse. The fine-grained signal
# lives in `Verdict.raw_score`; this is only for readability.
STANCE_SCORE: dict[str, float] = {BUY: 1.0, HOLD: 0.5, REDUCE: 0.25, EXIT: 0.0}

# Why a seat could not vote. The distinction is not cosmetic, see `Verdict`.
STRUCTURAL = "structural"
SITUATIONAL = "situational"


@dataclass(frozen=True)
class Citation:
    """Where one claim came from.

    `data_as_of` is the timestamp of the newest underlying observation, not the
    time the analysis ran. Those differ whenever a cache is involved, and
    reporting the second as the first is how a stale answer comes to look fresh.
    """

    source: str
    kind: str  # computed_metric | provider_data | stored_state
    detail: str
    data_as_of: str = ""
    rows_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    """One seat's position on one symbol, with its evidence."""

    seat: str
    symbol: str
    stance: str
    confidence: float = 0.0
    rationale: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    abstain_reason: str = ""

    # Why this seat is silent, when it is.
    #
    # STRUCTURAL means the seat has no data source wired at all, so it can never
    # vote until someone configures one. SITUATIONAL means the source exists but
    # today's data was missing or too thin.
    #
    # Counting the two the same way is a bug with consequences. A permanently
    # unwired seat is not an abstention on today's evidence, it is a seat nobody
    # filled, and letting it count against quorum makes the council structurally
    # unable to ever reach one. It reads as a hung floor forever, and the cause
    # is in the config rather than in the market.
    abstain_kind: str = SITUATIONAL

    # The engine's own composite, before it was flattened into a stance label.
    #
    # Thresholds throw information away. A momentum score of 0.69 and one of 0.51
    # both become HOLD, so a ranking built from labels cannot tell them apart.
    # Worse, an engine whose observed output tops out below the BUY threshold can
    # never say BUY at all, and nobody notices, because the label it emits is a
    # perfectly ordinary HOLD. Keeping the raw number is what lets an allocator
    # rank things and what lets that failure be seen.
    raw_score: float | None = None

    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.stance not in VOTING_STANCES and self.stance != ABSTAIN:
            raise ValueError(f"unknown stance: {self.stance}")
        if self.stance == ABSTAIN and not self.abstain_reason:
            raise ValueError("an abstention must say why; that is the whole point of it")
        if self.stance != ABSTAIN and not self.citations:
            raise ValueError(
                f"seat {self.seat!r} voted {self.stance} without citing anything; "
                "a position that cannot be traced cannot be audited"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")

    @property
    def abstained(self) -> bool:
        return self.stance == ABSTAIN

    @property
    def counts_toward_quorum(self) -> bool:
        """A structurally empty seat is not a participant in today's decision."""
        return not (self.abstained and self.abstain_kind == STRUCTURAL)

    @property
    def directional_score(self) -> float:
        """The seat's position on a 0..1 scale, raw if available, label if not."""
        if self.raw_score is not None:
            return float(self.raw_score)
        return STANCE_SCORE[self.stance]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["citations"] = [c.to_dict() for c in self.citations]
        return payload


def abstain(
    seat: str,
    symbol: str,
    reason: str,
    kind: str = SITUATIONAL,
) -> Verdict:
    """Build an abstention. A helper because it should be the easiest thing to do.

    If refusing to guess is more work than guessing, the code will guess.
    """
    return Verdict(
        seat=seat,
        symbol=symbol,
        stance=ABSTAIN,
        confidence=0.0,
        abstain_reason=reason,
        abstain_kind=kind,
    )
