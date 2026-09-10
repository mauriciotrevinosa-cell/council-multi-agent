"""The discipline these tests exist to enforce is refusal, not arithmetic.

Almost every test below is about a case where the correct behaviour is to
produce no number at all.
"""

import numpy as np
import pandas as pd
import pytest

from council import (
    ABSTAIN,
    BUY,
    STRUCTURAL,
    Citation,
    Council,
    LiquidityDelegate,
    MomentumDelegate,
    RiskDelegate,
    Verdict,
    abstain,
    rank,
    score_symbol,
)


def bars(n=250, trend=0.0004, vol=0.01, seed=0, volume=1_000_000):
    """A synthetic price series with a known drift."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(trend, vol, n)
    close = 100 * np.exp(np.cumsum(returns))
    index = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame({"close": close}, index=index)
    if volume is not None:
        frame["volume"] = volume
    return frame


# --- the contract on a verdict -----------------------------------------------


def test_a_vote_without_a_citation_is_rejected_at_construction():
    """A position that cannot be traced cannot be audited, so it cannot exist."""
    with pytest.raises(ValueError, match="without citing anything"):
        Verdict(seat="momentum", symbol="AAA", stance=BUY, confidence=0.8)


def test_an_abstention_must_say_why():
    with pytest.raises(ValueError, match="must say why"):
        Verdict(seat="risk", symbol="AAA", stance=ABSTAIN)


def test_the_raw_score_survives_the_stance_label():
    """0.69 and 0.51 both read HOLD; only the raw number can rank them."""
    citation = [Citation(source="s", kind="computed_metric", detail="d")]
    strong = Verdict(seat="a", symbol="X", stance="HOLD", raw_score=0.69, citations=citation)
    weak = Verdict(seat="b", symbol="X", stance="HOLD", raw_score=0.51, citations=citation)

    assert strong.stance == weak.stance
    assert strong.directional_score > weak.directional_score


# --- the seats refuse -------------------------------------------------------


def test_a_short_series_produces_an_abstention_not_a_weak_signal():
    """40 bars does not give a worse answer, it gives an answer to another question."""
    verdict = MomentumDelegate().assess("AAA", bars(n=40))

    assert verdict.abstained
    assert "below the 60 needed" in verdict.abstain_reason


def test_a_flat_price_series_is_read_as_a_stalled_feed_not_a_calm_market():
    frame = pd.DataFrame(
        {"close": [100.0] * 200},
        index=pd.date_range("2024-01-01", periods=200, freq="D"),
    )
    verdict = RiskDelegate().assess("AAA", frame)

    assert verdict.abstained
    assert "stalled feed" in verdict.abstain_reason


def test_a_missing_volume_source_abstains_structurally_not_situationally():
    """Nobody wired this seat. That is not an opinion about today's market."""
    verdict = LiquidityDelegate().assess("AAA", bars(volume=None))

    assert verdict.abstained
    assert verdict.abstain_kind == STRUCTURAL
    assert verdict.counts_toward_quorum is False


def test_mostly_zero_volume_abstains_because_a_zero_is_not_a_measurement():
    """The seat this whole repository is really about.

    Zeros in a volume series can mean "did not trade" or "the provider had
    nothing and wrote a zero". Those support opposite conclusions, and guessing
    produces a confident, fully cited, completely wrong verdict of illiquid.
    """
    frame = bars()
    # Zeros must fall inside the seat's lookback window to be seen at all; the
    # guard is scoped to the bars it actually reads, not to the whole history.
    frame.loc[frame.index[-40:], "volume"] = 0

    verdict = LiquidityDelegate().assess("AAA", frame)

    assert verdict.abstained
    assert "missing data" in verdict.abstain_reason
    assert verdict.abstain_kind != STRUCTURAL, "the source exists; today's data is unusable"


def test_old_zero_volume_outside_the_window_does_not_block_a_current_read():
    """The guard is scoped to the lookback window, and that is the right scope:
    an instrument that did not trade last year is not illiquid today."""
    frame = bars()
    frame.loc[frame.index[:150], "volume"] = 0

    verdict = LiquidityDelegate().assess("AAA", frame)

    assert not verdict.abstained


def test_a_few_zero_volume_bars_are_tolerated():
    """Holidays exist. The rule is a threshold, not a prohibition on zeros."""
    frame = bars()
    frame.loc[frame.index[-5:], "volume"] = 0

    verdict = LiquidityDelegate().assess("AAA", frame)

    assert not verdict.abstained


def test_a_seat_that_can_measure_does_vote_and_cites_its_window():
    verdict = MomentumDelegate().assess("AAA", bars(trend=0.005, vol=0.005))

    assert not verdict.abstained
    assert verdict.stance == BUY
    assert verdict.citations[0].rows_used >= 60
    assert verdict.citations[0].data_as_of, "a citation must carry the age of its data"


# --- combining them ---------------------------------------------------------


def test_a_symbol_nobody_could_assess_is_unrated_not_neutral():
    """0.5 from three analyses and 0.5 from none are not the same claim."""
    verdicts = [abstain(seat, "AAA", "no data") for seat in ("momentum", "risk", "liquidity")]
    result = score_symbol("AAA", verdicts)

    assert result.rated is False
    assert result.seats_voting == 0
    assert "unrated, not neutral" in result.notes[0]


def test_unrated_symbols_are_dropped_from_the_ranking_not_sorted_last():
    """Sorting them last still says 'we looked and it came last'."""
    assessed = score_symbol("GOOD", [
        Verdict(seat="a", symbol="GOOD", stance=BUY, confidence=0.9, raw_score=0.9,
                citations=[Citation("s", "computed_metric", "d")]),
        Verdict(seat="b", symbol="GOOD", stance="EXIT", confidence=0.5, raw_score=0.1,
                citations=[Citation("s", "computed_metric", "d")]),
    ])
    unassessed = score_symbol("DARK", [abstain("a", "DARK", "no data")])

    ordered = rank([assessed, unassessed])

    assert [s.symbol for s in ordered] == ["GOOD"]


def test_an_unwired_seat_does_not_dilute_confidence():
    """An unconfigured system should look incomplete, not uncertain."""
    citations = [Citation("s", "computed_metric", "d")]
    votes = [
        Verdict(seat="a", symbol="X", stance=BUY, confidence=1.0, raw_score=0.9, citations=citations),
        Verdict(seat="b", symbol="X", stance=BUY, confidence=1.0, raw_score=0.9, citations=citations),
    ]

    without = score_symbol("X", votes)
    with_unwired = score_symbol("X", votes + [abstain("c", "X", "never configured", kind=STRUCTURAL)])

    assert with_unwired.confidence == without.confidence
    assert with_unwired.seats_unwired == 1
    assert any("excluded from participation" in note for note in with_unwired.notes)


def test_a_seat_silent_today_does_dilute_confidence():
    """This one is a real gap in today's evidence, and it should show."""
    citations = [Citation("s", "computed_metric", "d")]
    votes = [
        Verdict(seat="a", symbol="X", stance=BUY, confidence=1.0, raw_score=0.9, citations=citations),
        Verdict(seat="b", symbol="X", stance=BUY, confidence=1.0, raw_score=0.9, citations=citations),
    ]

    without = score_symbol("X", votes)
    with_gap = score_symbol("X", votes + [abstain("c", "X", "provider returned nothing today")])

    assert with_gap.confidence < without.confidence


def test_disagreement_lowers_confidence_without_moving_the_score():
    """Score is where they landed; confidence is how much they agreed."""
    citations = [Citation("s", "computed_metric", "d")]
    agreed = score_symbol("X", [
        Verdict(seat="a", symbol="X", stance="HOLD", confidence=1.0, raw_score=0.5, citations=citations),
        Verdict(seat="b", symbol="X", stance="HOLD", confidence=1.0, raw_score=0.5, citations=citations),
    ])
    split = score_symbol("X", [
        Verdict(seat="a", symbol="X", stance=BUY, confidence=1.0, raw_score=1.0, citations=citations),
        Verdict(seat="b", symbol="X", stance="EXIT", confidence=1.0, raw_score=0.0, citations=citations),
    ])

    assert split.score == agreed.score == 0.5
    assert split.confidence < agreed.confidence


def test_a_single_voting_seat_is_flagged_as_one_opinion():
    result = score_symbol("X", [
        Verdict(seat="a", symbol="X", stance=BUY, confidence=0.9, raw_score=0.9,
                citations=[Citation("s", "computed_metric", "d")]),
        abstain("b", "X", "no data today"),
    ], min_seats=2)

    assert result.rated
    assert any("one opinion" in note for note in result.notes)


# --- the whole floor --------------------------------------------------------


def test_a_full_session_ranks_what_it_can_and_names_what_it_cannot():
    council = Council([MomentumDelegate(), RiskDelegate(), LiquidityDelegate()])

    session = council.deliberate({
        "RISER": bars(trend=0.002, seed=1),
        "FALLER": bars(trend=-0.002, seed=2),
        "DARK": bars(n=30, seed=3),  # too short for every seat
    })

    ranking = [s.symbol for s in session.ranking]
    assert ranking[0] == "RISER"
    assert "DARK" not in ranking
    assert session.unrated == ["DARK"]
    assert "UNRATED" in session.summary()


def test_duplicate_seats_are_refused_because_they_would_double_count():
    with pytest.raises(ValueError, match="double-counted"):
        Council([MomentumDelegate(), MomentumDelegate()])


def test_an_empty_council_is_refused():
    with pytest.raises(ValueError, match="at least one seat"):
        Council([])
