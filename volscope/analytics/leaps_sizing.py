"""
LEAPS position-sizing engine.

Maps a user budget plus a ``LeapsSuggestion`` into a concrete trade plan:
how many contracts, how much capital actually deployed (whole-contract
rounding leaves a residual), max loss, breakeven, and a personalised
payoff ladder denominated in dollars rather than per-cent return.

Pure analytics — no DB, no UI. The Streamlit sizing widget is a thin
adapter on top of these dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from volscope.analytics.leaps_convergence import LeapsSuggestion


# ── Public dataclasses ───────────────────────────────────────────────────

@dataclass(frozen=True)
class SizingPlan:
    """Concrete trade plan for one ``LeapsSuggestion`` at one budget."""

    ticker:           str
    budget:           float                 # user-supplied $ budget
    contract_size:    int                   # always 100 in US listed equity options
    contracts:        int                   # whole, non-negative
    capital_deployed: float                 # contracts × premium × 100
    capital_residual: float                 # budget − deployed
    max_loss:         float                 # equals capital_deployed for long calls
    breakeven_spot:   float
    payoff:           list["DollarPayoff"]  # personalised ladder
    rationale:        str = ""

    @property
    def is_undersized(self) -> bool:
        """True if the budget is too small to buy a single contract."""
        return self.contracts == 0


@dataclass(frozen=True)
class DollarPayoff:
    """One row in the personalised payoff ladder."""

    spot_at_expiry: float
    intrinsic_per_share: float
    profit_dollars: float        # signed P&L on the *whole position*
    return_pct: float            # vs capital deployed (not budget)


# ── Sizing rules ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SizingRule:
    """One named rule for translating a portfolio into a per-trade budget."""

    name:        str
    description: str

    def budget_from_book(self, book_value: float) -> float:
        raise NotImplementedError


@dataclass(frozen=True)
class FixedDollarRule(SizingRule):
    dollars: float = 0.0

    def budget_from_book(self, book_value: float) -> float:  # noqa: ARG002
        return max(0.0, float(self.dollars))


@dataclass(frozen=True)
class FractionOfBookRule(SizingRule):
    fraction: float = 0.05

    def budget_from_book(self, book_value: float) -> float:
        return max(0.0, float(book_value) * float(self.fraction))


# Stock public registry — surfaces in the UI as a dropdown.
SIZING_RULES: tuple[SizingRule, ...] = (
    FixedDollarRule(
        name="Fixed $300",
        description="Two-pizza convexity bet — hard cap on max loss.",
        dollars=300.0,
    ),
    FixedDollarRule(
        name="Fixed $1,000",
        description="One-rung up — still small enough to lose without grief.",
        dollars=1_000.0,
    ),
    FixedDollarRule(
        name="Fixed $3,000",
        description="The 10-contract size from the PYPL deck.",
        dollars=3_000.0,
    ),
    FractionOfBookRule(
        name="2% of book",
        description="Conservative Kelly-style allocation.",
        fraction=0.02,
    ),
    FractionOfBookRule(
        name="5% of book",
        description="Mid-conviction sizing.",
        fraction=0.05,
    ),
    FractionOfBookRule(
        name="10% of book",
        description="High-conviction maximum — the deck's upper bound.",
        fraction=0.10,
    ),
)


# ── Core sizing function ─────────────────────────────────────────────────

US_EQUITY_CONTRACT_SIZE = 100


def size_position(
    suggestion: LeapsSuggestion,
    budget: float,
    contract_size: int = US_EQUITY_CONTRACT_SIZE,
    payoff_levels: Optional[list[float]] = None,
) -> SizingPlan:
    """Translate a budget into a whole-contract LEAPS plan.

    Whole-contract rounding always rounds *down* — never spend more than
    the user authorised. Residual cash is reported separately so the UI
    can suggest "lift to N+1 contracts requires +$X".

    Parameters
    ----------
    suggestion
        The deep-OTM call output from
        :func:`volscope.analytics.leaps_convergence.suggest_leaps`.
    budget
        User-supplied $ budget for this position.
    contract_size
        Per-contract share count. 100 for US listed equity options.
    payoff_levels
        Optional override for the ladder. Defaults reproduce the milestone
        anchors from the suggestion's payoff (spot, +30 %, strike,
        breakeven, +20, +40, +70, +120).
    """
    if suggestion is None:
        raise ValueError("suggestion must not be None")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if contract_size <= 0:
        raise ValueError("contract_size must be positive")

    premium = float(suggestion.est_premium)
    cost_per_contract = premium * contract_size
    if cost_per_contract <= 0:
        # Defensive — would otherwise produce inf contracts.
        return SizingPlan(
            ticker=suggestion.ticker,
            budget=budget,
            contract_size=contract_size,
            contracts=0,
            capital_deployed=0.0,
            capital_residual=budget,
            max_loss=0.0,
            breakeven_spot=suggestion.breakeven,
            payoff=[],
            rationale="degenerate premium — sizing not computed",
        )

    contracts = int(budget // cost_per_contract)
    capital_deployed = round(contracts * cost_per_contract, 2)
    capital_residual = round(budget - capital_deployed, 2)

    levels = payoff_levels or [p[0] for p in suggestion.payoff]
    payoff = [
        _dollar_payoff(level, suggestion, contracts, contract_size, capital_deployed)
        for level in sorted(set(levels))
    ]

    if contracts == 0:
        rationale = (
            f"budget ${budget:,.0f} too small for one contract at "
            f"${cost_per_contract:,.0f} per contract — lift budget or pick a "
            f"closer-to-money strike"
        )
    else:
        rationale = (
            f"{contracts} contract{'s' if contracts != 1 else ''} × "
            f"${premium:.2f} premium = ${capital_deployed:,.0f} deployed "
            f"(${capital_residual:,.0f} residual). Max loss capped at "
            f"deployed capital — no margin call possible on a long call."
        )

    return SizingPlan(
        ticker=suggestion.ticker,
        budget=float(budget),
        contract_size=contract_size,
        contracts=contracts,
        capital_deployed=capital_deployed,
        capital_residual=capital_residual,
        max_loss=capital_deployed,
        breakeven_spot=suggestion.breakeven,
        payoff=payoff,
        rationale=rationale,
    )


def _dollar_payoff(
    spot_at_expiry: float,
    suggestion: LeapsSuggestion,
    contracts: int,
    contract_size: int,
    capital_deployed: float,
) -> DollarPayoff:
    intrinsic_per_share = max(0.0, float(spot_at_expiry) - float(suggestion.strike))
    intrinsic_dollars = intrinsic_per_share * contracts * contract_size
    profit_dollars = round(intrinsic_dollars - capital_deployed, 2)
    if capital_deployed <= 0:
        ret_pct = 0.0
    else:
        ret_pct = round(profit_dollars / capital_deployed * 100.0, 1)
    return DollarPayoff(
        spot_at_expiry=round(float(spot_at_expiry), 2),
        intrinsic_per_share=round(intrinsic_per_share, 2),
        profit_dollars=profit_dollars,
        return_pct=ret_pct,
    )


# ── Convenience helpers ──────────────────────────────────────────────────

def lift_to_next_contract_cost(plan: SizingPlan, suggestion: LeapsSuggestion) -> float:
    """Extra dollars needed to add exactly one more contract to ``plan``.

    Useful for the UI's "you're $42 short of 4 contracts" hint.
    """
    cost_per_contract = float(suggestion.est_premium) * plan.contract_size
    return round(max(0.0, cost_per_contract - plan.capital_residual), 2)
