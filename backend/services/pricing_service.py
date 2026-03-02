"""
services/pricing_service.py — Production-safe pricing orchestration.

Sequential pipeline per the spec:
  1. Baseline demand modelling    (models/baseline.py → demand_model)
  2. Price elasticity estimation  (models/elasticity.py)
  3. Price optimisation           (models/optimizer.py → price_simulator)
  4. RL adaptive price nudge      (optimisation/rl_agent.py)

Returns the standard API contract per SKU:
  {
    sku_id, current_price, recommended_price, price_change_percentage,
    expected_demand, expected_revenue, expected_margin, uplift_vs_baseline
  }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from models.elasticity import classify_elasticity, compute_elasticities
from optimisation.price_simulator import simulate_prices
from optimisation.rl_agent import RLPriceAgent, get_rl_multiplier

logger = logging.getLogger(__name__)


# ── Standard API contract output ─────────────────────────────────────────────

@dataclass
class PricingResult:
    sku_id: str
    current_price: float
    recommended_price: float
    price_change_percentage: float
    expected_demand: float
    expected_revenue: float
    expected_margin: float
    uplift_vs_baseline: float
    elasticity: float
    elasticity_class: str
    confidence_score: float
    constraint_notes: str

    def to_dict(self) -> dict:
        return {
            "sku_id": self.sku_id,
            "current_price": self.current_price,
            "recommended_price": self.recommended_price,
            "price_change_percentage": self.price_change_percentage,
            "expected_demand": self.expected_demand,
            "expected_revenue": self.expected_revenue,
            "expected_margin": self.expected_margin,
            "uplift_vs_baseline": self.uplift_vs_baseline,
            "elasticity": self.elasticity,
            "elasticity_class": self.elasticity_class,
            "confidence_score": self.confidence_score,
            "constraint_notes": self.constraint_notes,
        }


# ── Core orchestration ────────────────────────────────────────────────────────

def run_pricing_for_sku(
    pipeline: Pipeline,
    sku: str,
    current_price: float,
    unit_cost: float,
    stock_level: float,
    feature_row: pd.Series,
    feature_names: List[str],
    elasticities: Optional[Dict[str, float]] = None,
    rl_agent: Optional[RLPriceAgent] = None,
) -> PricingResult:
    """
    Run the full 4-step pricing pipeline for a single SKU.

    Steps:
    1. Baseline: predict demand at current price
    2. Elasticity: retrieve/compute price elasticity for this SKU
    3. Optimise: simulate price grid, select revenue-maximising valid price
    4. RL nudge: apply adaptive multiplier from trained Q-table
    """
    # ── Step 1: Baseline demand at current price ───────────────────────────────
    try:
        base_feat = pd.DataFrame([{k: feature_row.get(k, 0.0) for k in feature_names}])
        base_demand = float(pipeline.predict(base_feat.fillna(0.0))[0])
        base_demand = max(base_demand, 0.0)
    except Exception:
        logger.warning("Baseline prediction failed for SKU %s", sku)
        base_demand = 0.0

    baseline_revenue = current_price * base_demand

    # ── Step 2: Elasticity ────────────────────────────────────────────────────
    sku_key = str(sku).strip().upper()
    elasticity = (elasticities or {}).get(sku_key, -1.0)
    elast_class = classify_elasticity(elasticity)

    # ── Step 3: RL multiplier ─────────────────────────────────────────────────
    rl_mult = 1.0
    if rl_agent is not None:
        try:
            rl_mult = get_rl_multiplier(rl_agent, feature_row)
        except Exception:
            logger.warning("RL multiplier failed for SKU %s — using 1.0", sku)

    # ── Step 4 (3+4 combined): Price optimisation with RL nudge ──────────────
    try:
        sim = simulate_prices(
            pipeline=pipeline,
            sku=sku,
            current_price=current_price,
            unit_cost=unit_cost,
            stock_level=stock_level,
            feature_row=feature_row,
            feature_names=feature_names,
            rl_multiplier=rl_mult,
        )
    except Exception as exc:
        logger.error("Simulation failed for SKU %s: %s", sku, exc)
        return PricingResult(
            sku_id=sku,
            current_price=round(current_price, 4),
            recommended_price=round(current_price, 4),
            price_change_percentage=0.0,
            expected_demand=round(base_demand, 2),
            expected_revenue=round(baseline_revenue, 2),
            expected_margin=round((current_price - unit_cost) * base_demand, 2),
            uplift_vs_baseline=0.0,
            elasticity=round(elasticity, 4),
            elasticity_class=elast_class,
            confidence_score=0.0,
            constraint_notes=f"Simulation error: {exc}",
        )

    # ── Compute uplift vs baseline ─────────────────────────────────────────────
    uplift = 0.0
    if baseline_revenue > 0:
        uplift = (sim.expected_revenue - baseline_revenue) / baseline_revenue
    uplift = round(uplift, 4)

    # ── Price change % ────────────────────────────────────────────────────────
    pcp = 0.0
    if current_price > 0:
        pcp = (sim.recommended_price - current_price) / current_price
    pcp = round(pcp, 4)

    return PricingResult(
        sku_id=sku,
        current_price=round(current_price, 4),
        recommended_price=sim.recommended_price,
        price_change_percentage=pcp,
        expected_demand=sim.expected_demand,
        expected_revenue=sim.expected_revenue,
        expected_margin=sim.expected_margin,
        uplift_vs_baseline=uplift,
        elasticity=round(elasticity, 4),
        elasticity_class=elast_class,
        confidence_score=sim.confidence_score,
        constraint_notes=sim.constraint_notes,
    )


def run_batch_pricing(
    pipeline: Pipeline,
    df: pd.DataFrame,
    feature_names: List[str],
    rl_agent: Optional[RLPriceAgent] = None,
) -> List[PricingResult]:
    """
    Vectorised batch pricing for all SKUs in df.

    df must contain at minimum:
      Description, ImpliedPrice, ImpliedCost, Total NB Qty, + feature columns.

    No per-SKU looping — elasticities are computed once for the full batch.
    """
    if df.empty:
        return []

    # ── Step 1+2: Compute elasticities for the full dataset at once ────────────
    try:
        elasticities = compute_elasticities(df)
    except Exception:
        logger.warning("Batch elasticity computation failed — using global fallback")
        elasticities = {}

    # ── Step 3+4: Per-SKU simulation (unavoidable for price grid) ─────────────
    latest_df = (
        df.sort_values(
            [c for c in ["FiscalYear", "FiscalWeekNumber"] if c in df.columns],
            ascending=False,
        )
        .groupby("Description", as_index=False)
        .first()
    )

    results: List[PricingResult] = []
    for _, row in latest_df.iterrows():
        sku = str(row.get("Description", "UNKNOWN"))
        current_price = float(row.get("ImpliedPrice", row.get("UnitPrice", 1.0)))
        unit_cost = float(row.get("ImpliedCost", row.get("UnitCost", current_price * 0.6)))
        stock_level = float(row.get("Total NB Qty", row.get("Total_Qty", 100.0)))

        if current_price <= 0:
            current_price = max(float(row.get("UnitPrice", 1.0)), 0.01)
        unit_cost = max(unit_cost, 0.0)

        result = run_pricing_for_sku(
            pipeline=pipeline,
            sku=sku,
            current_price=current_price,
            unit_cost=unit_cost,
            stock_level=stock_level,
            feature_row=row,
            feature_names=feature_names,
            elasticities=elasticities,
            rl_agent=rl_agent,
        )
        results.append(result)

    logger.info("Batch pricing complete: %d SKUs processed", len(results))
    return results
