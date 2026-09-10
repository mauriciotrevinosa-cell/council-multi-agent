# council-multi-agent

Several independent analyses, combined into one ranking, where **a seat that
cannot get real inputs abstains instead of guessing** — and the abstention stays
visible in the result.

```python
from council import Council, MomentumDelegate, RiskDelegate, LiquidityDelegate

council = Council([MomentumDelegate(), RiskDelegate(), LiquidityDelegate()])
session = council.deliberate({"STRONG": bars_a, "GAPPY": bars_b, "NEW": bars_c})

print(session.summary())
# STRONG   score 0.827  confidence 0.497  (3 voting, 0 abstained)
# GAPPY    score 0.536  confidence 0.254  (2 voting, 1 abstained)
# NEW      UNRATED (no seat could form a view)
```

---

## About the scope of this repository

**This is a deliberately reduced version of one subsystem of a larger, private
system.** The full Council is part of **Atlas**, a proprietary quantitative
platform I build and maintain. There it seats a dozen engines — options flow,
market microstructure, macro regime, correlation structure, an event replay
engine — and its output feeds position sizing under real risk limits.

Three generic seats are here instead, on synthetic data. What survived the cut is
the part that is actually transferable: the contract a seat signs, the rules for
combining seats that disagree, and the handling of seats that stay silent.

What was removed on purpose:

- every real analytical engine and the data providers behind them
- position sizing, risk limits and anything touching execution
- the persistence layer and the decision audit store

---

## The idea

Ensembling analyses is easy until one of them has no data. At that moment there
are two options, and almost every system takes the wrong one.

The wrong one is to substitute a neutral value. It is *so* convenient: the
pipeline keeps running, the tally stays full, nothing crashes. But a fabricated
0.5 is byte-for-byte identical to a measured 0.5 downstream. Every audit trail in
the system is now worthless, because you can no longer tell which numbers were
observed and which were invented to keep the loop turning.

The right one is to abstain, and to make abstaining *easier* than guessing. If
refusing to answer takes more code than answering, the code will answer.

Everything else here follows from that.

### Five decisions worth pointing at

**1. A vote without a citation is rejected at construction.** Not logged, not
warned about — a `ValueError` from `Verdict.__post_init__`. A position that
cannot be traced cannot be audited, so it is not allowed to exist in the first
place.

**2. There are two kinds of silence, and conflating them breaks quorum.** A seat
with *no data source configured at all* is structurally empty: nobody filled it,
and it will stay silent until someone does. A seat whose source exists but
returned nothing today is silent *about today*. Counting the first against
participation makes the council permanently unable to reach a quorum, and the
symptom — a floor that always reads half-empty — points at the market when the
cause is in a config file.

**3. A zero is not a measurement.** A zero in a volume series can mean "did not
trade" or "the provider had nothing and wrote a zero instead of a null". Those
support opposite conclusions. Guessing produces a verdict of "illiquid, reduce"
that is confident, fully cited, arithmetically correct, and wrong — and because
the citation is real, nothing downstream can catch it. `LiquidityDelegate`
abstains above a threshold of exact zeros rather than pick a reading.

**4. The raw score survives the label.** Thresholds throw information away: 0.69
and 0.51 both become `HOLD`, so a ranking built from labels cannot tell them
apart. Worse, an engine whose output tops out below the `BUY` threshold can never
say `BUY` at all, and nobody notices, because the label it emits is an ordinary
`HOLD`. Every verdict keeps `raw_score` next to `stance`.

**5. Score and confidence are separate numbers.** The score is where the floor
landed. The confidence is how much they agreed and how sure each was. A high
score held with low confidence deserves a smaller position than the same score
held with high confidence, and collapsing them destroys exactly what a position
sizer needs.

---

## A flaw the example makes visible, on purpose

`examples/a_floor_that_admits_what_it_cannot_see.py` runs four symbols. One of
them, `WEAK`, falls at 0.4% a day with 3% daily volatility and still scores
**0.512** — barely below neutral. Its contributions say why:

```
  momentum   EXIT   score 0.342
  risk       REDUCE score 0.194
  liquidity  BUY    score 1.000
```

The liquidity seat saturates at 1.0 for anything that trades at all. Across a
universe of normally liquid names it returns the same number every time, and **a
constant cannot rank anything** — it can only drag every score toward its own
value, which is what it is doing to `WEAK` here.

The fix is not a better formula. It is a different role: liquidity belongs as a
**gate that excludes names**, not as a **vote that scores them**. It is left as a
seat in this repository because the failure is more instructive visible than
corrected. A seat can be correct, well-cited, and contribute nothing, and that is
much harder to notice than a seat that is wrong.

---

## Running it

```bash
pip install -e ".[dev]"
pytest -q
python examples/a_floor_that_admits_what_it_cannot_see.py
```

19 tests. Almost all of them assert that no number is produced:

| Situation | Correct behaviour |
|---|---|
| 40 bars when 60 are needed | abstain — a short series answers a different question |
| Price constant for 200 bars | abstain — that is a stalled feed, not a calm market |
| No volume column anywhere | abstain, *structurally* — and do not count against quorum |
| 75% of volume bars exactly zero | abstain — a zero and a gap support opposite conclusions |
| No seat could vote | unrated, and dropped from the ranking rather than sorted last |

That last row matters more than it looks. Sorting an unrated symbol last still
places it on the list, below a symbol three seats scored at 0.1. That reads as
"we assessed this and it came last", which is the opposite of what happened.

---

## How this repository was built

I want this stated plainly rather than left to be inferred.

**The system this came from is mine.** Atlas is a platform I have been building
and maintaining, and the engineering judgement in it — the architecture, the
decisions about what a component must refuse to do, the discipline this module
demonstrates — is work I did.

**This repository is not that code.** It was written with **Claude Code
(Anthropic)**, working from my Atlas source and my design decisions, to produce
a smaller self-contained version that can be read and judged in twenty minutes
without exposing the private system. Claude wrote most of the code here, wrote
the tests, ran them, and found several real bugs in the process — those are
named in the sections above. I decided what to extract, what to leave out, and
which properties the reduced version had to preserve. The commits carry
`Co-Authored-By: Claude Opus 5`.

**Why say so.** Two reasons. It is true, and I would rather be judged on what I
actually did than on an impression I allowed to stand. And it sets the right
expectation about how I work: I design systems, decide what they must guarantee,
and use the tools available to get them built and verified. I am not claiming to
have typed every line here unaided, and I would rather you know that before we
talk than after.

If you want to test the understanding rather than the authorship, ask me about
any decision documented above. Every one of them is a choice I can defend, and
the reasoning is in the code comments because that is where I wanted it.

---

## License

MIT, and it covers only the reduced code in this repository. The full Atlas
platform this subsystem was extracted from is proprietary and is not licensed
here.

## Author

Mauricio Gerardo Trevino Saldana
