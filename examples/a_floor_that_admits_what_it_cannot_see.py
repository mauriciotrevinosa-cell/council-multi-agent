"""Four symbols, three seats, and four different reasons the floor can be silent.

The interesting output is not the ranking. It is the last two symbols, where the
council produces no score at all and says precisely why, instead of returning a
neutral 0.5 that would be indistinguishable from a measured one.

Run:  python examples/a_floor_that_admits_what_it_cannot_see.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from council import Council, LiquidityDelegate, MomentumDelegate, RiskDelegate


def series(n=250, trend=0.0004, vol=0.01, seed=0, volume=1_000_000):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(trend, vol, n)))
    frame = pd.DataFrame(
        {"close": close}, index=pd.date_range("2024-01-01", periods=n, freq="D")
    )
    if volume is not None:
        frame["volume"] = volume
    return frame


def main() -> None:
    data = {
        # Trending up, liquid, calm. Everything measurable.
        "STRONG": series(trend=0.004, vol=0.008, seed=1),
        # Trending down, and violently.
        "WEAK": series(trend=-0.004, vol=0.03, seed=2),
        # Fine prices, but the provider writes zeros where it has no volume.
        "GAPPY": series(seed=3),
        # Listed three weeks ago. Nothing here is measurable yet.
        "NEW": series(n=21, seed=4),
    }
    data["GAPPY"].loc[data["GAPPY"].index[-45:], "volume"] = 0

    council = Council([MomentumDelegate(), RiskDelegate(), LiquidityDelegate()])
    session = council.deliberate(data)

    print("RANKING")
    print("-" * 78)
    print(session.summary())

    print()
    print("WHY EACH SEAT WAS SILENT, WHERE IT WAS")
    print("-" * 78)
    for symbol, verdicts in session.verdicts.items():
        silent = [v for v in verdicts if v.abstained]
        if not silent:
            continue
        print(f"\n{symbol}")
        for verdict in silent:
            print(f"  {verdict.seat:<10} [{verdict.abstain_kind}] {verdict.abstain_reason}")

    print()
    print("-" * 78)
    print("GAPPY is the case worth looking at twice. Its prices are fine, so two")
    print("seats vote and it gets a score. Only the liquidity seat refuses, and")
    print("it refuses on data that would have produced a perfectly citable")
    print("verdict of 'illiquid, reduce'. That verdict would have been wrong, and")
    print("nothing downstream could have caught it: the citation would be real,")
    print("the arithmetic correct, the conclusion false.")
    print()
    print("NEW is the easy case. Nobody can measure a 21-bar series, so the")
    print("council returns no score rather than a weak one, and the symbol is")
    print("dropped from the ranking instead of being placed in the middle of it.")

    print()
    print("-" * 78)
    print("AND A FLAW THE OUTPUT MAKES VISIBLE")
    print("-" * 78)
    weak = next(s for s in session.scores if s.symbol == "WEAK")
    print(f"WEAK falls at 0.4% a day with 3% daily volatility, and still scores")
    print(f"{weak.score:.3f} -- barely below neutral. Look at its contributions:")
    print()
    for contribution in weak.contributions:
        print(f"  {contribution.seat:<10} {contribution.stance:<6} score {contribution.score:.3f}")
    print()
    print("The liquidity seat saturates at 1.0 for anything that trades at all,")
    print("so across a universe of normally liquid names it returns the same")
    print("number every time. A constant cannot rank anything. It can only drag")
    print("every score toward its own value, which is exactly what it is doing")
    print("to WEAK here.")
    print()
    print("The fix is not a better formula, it is a different role: liquidity")
    print("belongs as a gate that excludes names, not as a vote that scores")
    print("them. It is left as a seat in this repository because the failure is")
    print("more instructive visible than corrected -- a seat can be correct,")
    print("cited, and still contribute nothing.")


if __name__ == "__main__":
    main()
