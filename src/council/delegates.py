"""The seats.

Each delegate wraps one analysis and translates its output into a citable
verdict. Every one of them has the same obligation it may not dodge: if it cannot
obtain the real inputs its analysis requires, it abstains and says why. It never
fills the gap with a default, an estimate, or a neutral value.

The three here are deliberately ordinary — momentum, risk, liquidity. What is
worth reading is not the arithmetic but the guard clauses at the top of each
`assess`, and in particular `LiquidityDelegate`, which is the seat that taught
this system the difference between a zero and a gap.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from .models import (
    ABSTAIN,
    BUY,
    EXIT,
    HOLD,
    REDUCE,
    STRUCTURAL,
    Citation,
    Verdict,
    abstain,
)

# Below this many observations, none of the windows these seats use are
# measurable. A shorter series does not give a weaker answer, it gives an
# arithmetically valid answer to a question nobody asked.
MIN_BARS = 60

# A volume series where this share of bars is exactly zero is far more likely to
# be missing data encoded as zero than a genuinely untraded instrument. See
# `LiquidityDelegate.assess`.
MAX_ZERO_VOLUME_SHARE = 0.20


class Delegate(Protocol):
    """The contract every seat implements."""

    seat: str

    def assess(self, symbol: str, bars: pd.DataFrame) -> Verdict:
        """Form a position on one symbol, or abstain and say why."""
        ...


def _insufficient(bars: pd.DataFrame, column: str = "close") -> str | None:
    """The guard every seat shares. Returns a reason, or None if the data is usable."""
    if column not in bars.columns:
        return f"no {column!r} column in the supplied data"
    series = bars[column].dropna()
    if len(series) < MIN_BARS:
        return f"{len(series)} usable bars, below the {MIN_BARS} needed for any window here"
    return None


class MomentumDelegate:
    """Trend, from the relationship between a fast and a slow moving average."""

    seat = "momentum"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow")
        self.fast = fast
        self.slow = slow

    def assess(self, symbol: str, bars: pd.DataFrame) -> Verdict:
        reason = _insufficient(bars)
        if reason:
            return abstain(self.seat, symbol, reason)

        close = bars["close"].dropna()
        fast = close.rolling(self.fast).mean().iloc[-1]
        slow = close.rolling(self.slow).mean().iloc[-1]

        if pd.isna(fast) or pd.isna(slow) or slow <= 0:
            return abstain(self.seat, symbol, "moving averages did not resolve to a number")

        # Ratio of the two averages, squashed into 0..1. A 10% spread either way
        # saturates: beyond that the sign is what matters, not the magnitude.
        spread = float(fast / slow - 1.0)
        raw = min(1.0, max(0.0, 0.5 + spread * 5.0))

        stance = BUY if raw >= 0.65 else EXIT if raw <= 0.35 else HOLD

        return Verdict(
            seat=self.seat,
            symbol=symbol,
            stance=stance,
            confidence=round(abs(raw - 0.5) * 2, 4),
            raw_score=round(raw, 4),
            rationale=[f"{self.fast}/{self.slow} moving average spread {spread:+.2%}"],
            citations=[
                Citation(
                    source="momentum",
                    kind="computed_metric",
                    detail=f"sma({self.fast})/sma({self.slow}) on close",
                    data_as_of=str(close.index[-1]),
                    rows_used=len(close),
                )
            ],
        )


class RiskDelegate:
    """Realised volatility and the depth of the worst drawdown in the window."""

    seat = "risk"

    def __init__(self, lookback: int = 60, vol_ceiling: float = 0.60) -> None:
        self.lookback = lookback
        self.vol_ceiling = vol_ceiling

    def assess(self, symbol: str, bars: pd.DataFrame) -> Verdict:
        reason = _insufficient(bars)
        if reason:
            return abstain(self.seat, symbol, reason)

        close = bars["close"].dropna().iloc[-self.lookback :]
        returns = close.pct_change().dropna()

        if returns.empty or returns.std() == 0:
            # A constant price is not a low-risk asset, it is a stalled feed.
            return abstain(
                self.seat, symbol,
                "returns have zero variance, which indicates a stalled feed rather than a calm market",
            )

        annualised_vol = float(returns.std() * (252**0.5))
        drawdown = float((close / close.cummax() - 1.0).min())

        # Lower volatility and a shallower drawdown both push the score up.
        vol_component = 1.0 - min(1.0, annualised_vol / self.vol_ceiling)
        drawdown_component = 1.0 - min(1.0, abs(drawdown) / 0.40)
        raw = 0.5 * vol_component + 0.5 * drawdown_component

        stance = BUY if raw >= 0.70 else REDUCE if raw <= 0.30 else HOLD

        return Verdict(
            seat=self.seat,
            symbol=symbol,
            stance=stance,
            confidence=round(min(1.0, len(returns) / self.lookback), 4),
            raw_score=round(raw, 4),
            rationale=[
                f"annualised volatility {annualised_vol:.1%}",
                f"max drawdown {drawdown:.1%} over {len(close)} bars",
            ],
            citations=[
                Citation(
                    source="risk",
                    kind="computed_metric",
                    detail=f"stdev and drawdown over the last {len(close)} bars",
                    data_as_of=str(close.index[-1]),
                    rows_used=len(close),
                )
            ],
        )


class LiquidityDelegate:
    """Traded volume, and the seat that has to distinguish a zero from a gap.

    A zero in a volume series is ambiguous in a way a zero in a price series is
    not. It can mean the instrument genuinely did not trade, or it can mean the
    provider had nothing for that bar and wrote a zero instead of a null. Those
    two readings support opposite conclusions: the first says illiquid, the second
    says unknown.

    Treating the second as the first is the specific failure this seat exists to
    avoid. It produces a confident, fully cited, completely wrong verdict of
    "illiquid, EXIT" on an instrument that trades normally, and because the
    citation is real, the verdict survives review.

    The zero check is scoped to the lookback window, not to the whole history,
    and that is deliberate: an instrument that did not trade last year is not
    illiquid today, so old zeros must not veto a current read.
    """

    seat = "liquidity"

    def __init__(self, lookback: int = 60, thin_threshold: float = 100_000) -> None:
        self.lookback = lookback
        self.thin_threshold = thin_threshold

    def assess(self, symbol: str, bars: pd.DataFrame) -> Verdict:
        if "volume" not in bars.columns:
            # Not a gap in today's data: this seat has no source wired at all, and
            # never will until someone configures one. It must not count against
            # a quorum on today's evidence.
            return abstain(
                self.seat, symbol,
                "no volume series is available from any configured source",
                kind=STRUCTURAL,
            )

        volume = bars["volume"].dropna().iloc[-self.lookback :]
        if len(volume) < MIN_BARS:
            return abstain(self.seat, symbol, f"{len(volume)} volume bars, below the {MIN_BARS} needed")

        zero_share = float((volume == 0).mean())
        if zero_share > MAX_ZERO_VOLUME_SHARE:
            return abstain(
                self.seat, symbol,
                f"{zero_share:.0%} of volume bars are exactly zero, which reads as "
                "missing data rather than an untraded instrument; the two support "
                "opposite conclusions and this seat cannot tell them apart",
            )

        median_volume = float(volume.median())
        raw = min(1.0, median_volume / (self.thin_threshold * 10))
        stance = BUY if raw >= 0.60 else REDUCE if raw <= 0.15 else HOLD

        return Verdict(
            seat=self.seat,
            symbol=symbol,
            stance=stance,
            confidence=round(1.0 - zero_share, 4),
            raw_score=round(raw, 4),
            rationale=[f"median volume {median_volume:,.0f} over {len(volume)} bars"],
            citations=[
                Citation(
                    source="liquidity",
                    kind="provider_data",
                    detail=f"median volume over {len(volume)} bars",
                    data_as_of=str(volume.index[-1]),
                    rows_used=len(volume),
                )
            ],
        )
