"""A multi-agent decision council where abstention is a first-class outcome.

Reduced showcase extract. See README.md for what was left out and why.
"""

from .delegates import Delegate, LiquidityDelegate, MomentumDelegate, RiskDelegate
from .models import (
    ABSTAIN,
    BUY,
    EXIT,
    HOLD,
    REDUCE,
    SITUATIONAL,
    STRUCTURAL,
    Citation,
    Verdict,
    abstain,
)
from .scoring import Contribution, SymbolScore, rank, score_symbol
from .session import Council, Session

__all__ = [
    "Council", "Session",
    "Delegate", "MomentumDelegate", "RiskDelegate", "LiquidityDelegate",
    "Verdict", "Citation", "abstain",
    "BUY", "HOLD", "REDUCE", "EXIT", "ABSTAIN", "STRUCTURAL", "SITUATIONAL",
    "SymbolScore", "Contribution", "score_symbol", "rank",
]

__version__ = "0.1.0"
