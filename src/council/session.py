"""Running the floor over a set of symbols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import pandas as pd

from .delegates import Delegate
from .models import Verdict
from .scoring import DEFAULT_MIN_SEATS, SymbolScore, rank, score_symbol


@dataclass
class Session:
    """One deliberation: every seat assessed every symbol, and what came of it."""

    scores: list[SymbolScore]
    verdicts: dict[str, list[Verdict]] = field(default_factory=dict)

    @property
    def ranking(self) -> list[SymbolScore]:
        """Rated symbols, best first."""
        return rank(self.scores)

    @property
    def unrated(self) -> list[str]:
        """Symbols no seat could assess. Reported, never silently dropped."""
        return sorted(s.symbol for s in self.scores if not s.rated)

    def summary(self) -> str:
        """A readable account of what the floor decided, and what it could not."""
        lines: list[str] = []
        for entry in self.ranking:
            lines.append(
                f"{entry.symbol:<8} score {entry.score:.3f}  confidence {entry.confidence:.3f}  "
                f"({entry.seats_voting} voting, {entry.seats_abstained} abstained)"
            )
            for note in entry.notes:
                lines.append(f"         note: {note}")
        for symbol in self.unrated:
            lines.append(f"{symbol:<8} UNRATED (no seat could form a view)")
        return "\n".join(lines)


class Council:
    """A set of seats, run over a set of symbols.

    The council does not adjudicate between seats and it does not overrule one.
    It collects positions, and the scoring combines them by a fixed rule. There
    is no step where a narrative layer gets to adjust a number: text may explain
    a decision, never change it.
    """

    def __init__(self, delegates: Sequence[Delegate], min_seats: int = DEFAULT_MIN_SEATS) -> None:
        if not delegates:
            raise ValueError("a council needs at least one seat")
        seats = [d.seat for d in delegates]
        if len(set(seats)) != len(seats):
            raise ValueError(f"duplicate seats would be double-counted: {seats}")
        self.delegates = list(delegates)
        self.min_seats = min_seats

    def deliberate(self, data: Mapping[str, pd.DataFrame]) -> Session:
        """Assess every symbol with every seat."""
        scores: list[SymbolScore] = []
        all_verdicts: dict[str, list[Verdict]] = {}

        for symbol, bars in data.items():
            verdicts = [delegate.assess(symbol, bars) for delegate in self.delegates]
            all_verdicts[symbol] = verdicts
            scores.append(score_symbol(symbol, verdicts, min_seats=self.min_seats))

        return Session(scores=scores, verdicts=all_verdicts)
