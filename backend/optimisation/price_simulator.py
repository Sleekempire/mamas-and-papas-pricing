"""
optimisation/price_simulator.py — Price grid simulation and revenue/margin optimisation.
Simulates 0.8x–1.2x price range, predicts demand, applies constraints, selects optimal price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from config import settings
from models.demand_model import predict_demand
from optimisation.constraints import ConstraintResult, check_constraints, classify_elasticity


@dataclass
class PricePoint:
    price: float
    predicted_demand: float
    revenue: float
    margin: float
    margin_pct: float
    constraint: ConstraintResult
    objective_score: float = 0.0


@dataclass
class SimulationResult:
    sku: str
    current_price: float
    unit_cost: float
    recommended_price: float
    expected_demand: float
    expected_revenue: float
    expected_margin: float
    confidence_score: float
    elasticity: float
    elasticity_class: str
    price_grid: List[dict] = field(default_factory=list)
    constraint_notes: str = ""


def simulate_prices(
    pipeline: Pipeline,
    sku: str,
    current_price: float,
    unit_cost: float,
    stock_level: float,
    feature_row: pd.Series,
    feature_names: List[str],
    rl_multiplier: float = 1.0,
) -> SimulationResult:
    """
    Run the full price simulation for a single SKU row.
    Returns the optimal recommended price with all metrics.
    """
    n_points = settings.PRICE_GRID_POINTS
    lower = current_price * settings.PRICE_LOWER_BOUND
    upper = current_price * settings.PRICE_UPPER_BOUND
    price_grid = np.linspace(lower, upper, n_points)

    points: List[PricePoint] = []

    for candidate_price in price_grid:
        # Build feature row with candidate price substituted
        row_dict = feature_row.to_dict()
        row_dict["UnitPrice"] = candidate_price
        # Recompute margin_pct for the new price
        if candidate_price > 0:
            row_dict["margin_pct"] = (candidate_price - unit_cost) / candidate_price

        feat_df = pd.DataFrame([{k: row_dict.get(k, 0.0) for k in feature_names}])
        pred_demand = float(predict_demand(pipeline, feat_df)[0])

        revenue = candidate_price * pred_demand
        gross_margin = (candidate_price - unit_cost) * pred_demand
        margin_pct = (candidate_price - unit_cost) / candidate_price if candidate_price > 0 else 0.0

        # Compute point elasticity vs current price
        current_feat = pd.DataFrame([{k: feature_row.get(k, 0.0) for k in feature_names}])
        base_demand = float(predict_demand(pipeline, current_feat)[0])
        if base_demand > 0 and current_price > 0 and candidate_price != current_price:
            pct_demand_change = (pred_demand - base_demand) / base_demand
            pct_price_change = (candidate_price - current_price) / current_price
            elasticity = pct_demand_change / pct_price_change if pct_price_change != 0 else 0.0
        else:
            elasticity = -1.0  # Assume unit elastic as default

        constraint = check_constraints(
            candidate_price=candidate_price,
            current_price=current_price,
            predicted_demand=pred_demand,
            unit_cost=unit_cost,
            stock_level=stock_level,
            elasticity=elasticity,
        )

        # Objective: maximise revenue weighted with margin factor
        if constraint.is_valid:
            margin_factor = max(0.0, margin_pct / max(settings.MIN_MARGIN_PCT, 0.001))
            obj_score = revenue * min(margin_factor, 2.0)
        else:
            obj_score = -1.0

        points.append(PricePoint(
            price=round(candidate_price, 4),
            predicted_demand=round(pred_demand, 2),
            revenue=round(revenue, 2),
            margin=round(gross_margin, 2),
            margin_pct=round(margin_pct, 4),
            constraint=constraint,
            objective_score=round(obj_score, 4),
        ))

    # Apply RL multiplier adjustment — nudge the best valid price
    valid_points = [p for p in points if p.constraint.is_valid]

    if not valid_points:
        # No valid points — fall back to current price
        current_feat = pd.DataFrame([{k: feature_row.get(k, 0.0) for k in feature_names}])
        base_demand = float(predict_demand(pipeline, current_feat)[0])
        return SimulationResult(
            sku=sku,
            current_price=round(current_price, 4),
            unit_cost=round(unit_cost, 4),
            recommended_price=round(current_price, 4),
            expected_demand=round(base_demand, 2),
            expected_revenue=round(current_price * base_demand, 2),
            expected_margin=round((current_price - unit_cost) * base_demand, 2),
            confidence_score=0.1,
            elasticity=-1.0,
            elasticity_class="Neutral",
            price_grid=[],
            constraint_notes="No valid price found — held at current price",
        )

    # Select best valid point, applying RL nudge
    best = max(valid_points, key=lambda p: p.objective_score * rl_multiplier)

    # Compute final elasticity at recommended price
    current_feat = pd.DataFrame([{k: feature_row.get(k, 0.0) for k in feature_names}])
    base_demand = float(predict_demand(pipeline, current_feat)[0])
    if base_demand > 0 and current_price > 0 and best.price != current_price:
        pct_demand_change = (best.predicted_demand - base_demand) / base_demand
        pct_price_change = (best.price - current_price) / current_price
        final_elasticity = pct_demand_change / pct_price_change if pct_price_change != 0 else 0.0
    else:
        final_elasticity = -1.0

    # Confidence: based on proportion of valid grid points + model fit
    confidence = len(valid_points) / len(points)

    grid_out = [
        {
            "price": p.price,
            "demand": p.predicted_demand,
            "revenue": p.revenue,
            "margin": p.margin,
            "valid": p.constraint.is_valid,
        }
        for p in points
    ]

    return SimulationResult(
        sku=sku,
        current_price=round(current_price, 4),
        unit_cost=round(unit_cost, 4),
        recommended_price=round(best.price, 4),
        expected_demand=round(best.predicted_demand, 2),
        expected_revenue=round(best.revenue, 2),
        expected_margin=round(best.margin, 2),
        confidence_score=round(confidence, 4),
        elasticity=round(final_elasticity, 4),
        elasticity_class=classify_elasticity(final_elasticity),
        price_grid=grid_out,
        constraint_notes=best.constraint.notes,
    )
