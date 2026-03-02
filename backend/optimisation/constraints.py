"""
optimisation/constraints.py — Business guardrails for price recommendations.
Validates each candidate price against margin, stock, elasticity, and business rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from config import settings


@dataclass
class ConstraintResult:
    is_valid: bool
    violations: List[str]
    notes: str = ""


def check_constraints(
    candidate_price: float,
    current_price: float,
    predicted_demand: float,
    unit_cost: float,
    stock_level: float,
    elasticity: Optional[float] = None,
) -> ConstraintResult:
    """
    Apply all business constraints to a candidate price.
    Returns ConstraintResult with validity and violation details.
    """
    violations: List[str] = []

    # ── 1. Minimum margin constraint ──────────────────────────────────────────
    if candidate_price > 0:
        margin_pct = (candidate_price - unit_cost) / candidate_price
        if margin_pct < settings.MIN_MARGIN_PCT:
            violations.append(
                f"Margin {margin_pct:.1%} below minimum {settings.MIN_MARGIN_PCT:.1%}"
            )
    else:
        violations.append("Candidate price must be positive")

    # ── 2. Stock availability constraint ─────────────────────────────────────
    max_demand = stock_level * settings.STOCK_SAFETY_FACTOR
    if predicted_demand > max_demand:
        violations.append(
            f"Predicted demand {predicted_demand:.0f} exceeds safe stock level {max_demand:.0f}"
        )

    # ── 3. Maximum daily price change ─────────────────────────────────────────
    if current_price > 0:
        change_pct = abs(candidate_price - current_price) / current_price
        if change_pct > settings.MAX_DAILY_PRICE_CHANGE:
            violations.append(
                f"Price change {change_pct:.1%} exceeds daily max {settings.MAX_DAILY_PRICE_CHANGE:.1%}"
            )

    # ── 4. Elasticity sanity bounds ───────────────────────────────────────────
    if elasticity is not None:
        if not (-10.0 <= elasticity <= 0.0):
            violations.append(
                f"Elasticity {elasticity:.2f} outside plausible range [-10, 0]"
            )

    # ── 5. Price bounds ───────────────────────────────────────────────────────
    if current_price > 0:
        lower = current_price * settings.PRICE_LOWER_BOUND
        upper = current_price * settings.PRICE_UPPER_BOUND
        if candidate_price < lower or candidate_price > upper:
            violations.append(
                f"Price {candidate_price:.2f} outside allowed range [{lower:.2f}, {upper:.2f}]"
            )

    notes = "; ".join(violations) if violations else "All constraints satisfied"
    return ConstraintResult(is_valid=len(violations) == 0, violations=violations, notes=notes)


def classify_elasticity(elasticity: float) -> str:
    """Classify price elasticity as Elastic, Inelastic, or Neutral."""
    abs_e = abs(elasticity)
    if abs_e > 1.05:
        return "Elastic"
    elif abs_e < 0.95:
        return "Inelastic"
    else:
        return "Neutral"
