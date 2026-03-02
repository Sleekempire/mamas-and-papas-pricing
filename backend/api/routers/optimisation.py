"""
api/routers/optimisation.py — POST /run-optimisation
Vectorised batch price optimisation using new M&P channel-based schema.
Runs 10 batch ML predictions across all products simultaneously instead of
per-product loop — completes in seconds rather than hours.
Requires: Admin, Analyst, or Merchandiser role.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.connection import get_db
from database.models import CleanedDataRecord, ModelVersion, OptimisationRun, Recommendation
from models.model_store import load_model
from optimisation.rl_agent import load_or_create_agent, get_rl_multiplier
from security.audit import AuditEventType, write_audit_log
from security.auth import TokenData
from security.rbac import RequireMerchandiserOrAbove

router = APIRouter()


class OptimisationResponse(BaseModel):
    run_id: str
    sku_count: int
    target_date: str
    status: str
    message: str


def _classify_elasticity(e: float) -> str:
    if e < -1.5:
        return "Highly Elastic"
    if e < -0.5:
        return "Elastic"
    if e < 0.5:
        return "Inelastic"
    return "Neutral"


@router.post("/run-optimisation", response_model=OptimisationResponse)
async def run_optimisation(
    request: Request,
    target_date: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    current_user: TokenData = Depends(RequireMerchandiserOrAbove),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    run_id = str(uuid.uuid4())
    td = target_date or date.today().isoformat()

    # ── Load active model ─────────────────────────────────────────────────────
    active_mv: Optional[ModelVersion] = db.query(ModelVersion).filter(
        ModelVersion.is_active == True
    ).first()
    if not active_mv:
        raise HTTPException(status_code=422, detail="No trained model found. Run /train-model first.")

    try:
        pipeline = load_model(active_mv.model_file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Model file missing: {e}")

    feature_names = active_mv.feature_names or [
        "ImpliedPrice", "PromoFlag", "fiscal_quarter",
        "channel_mix_ratio", "Lag_1", "Lag_4", "Rolling_Mean_4"
    ]

    # ── Load cleaned data ─────────────────────────────────────────────────────
    query = db.query(CleanedDataRecord)
    if category:
        query = query.filter(CleanedDataRecord.analyst_category.ilike(f"%{category}%"))
    records = query.all()

    if not records:
        raise HTTPException(status_code=422, detail="No cleaned data available for optimisation.")

    # Build DataFrame from stored records
    df = pd.DataFrame([{
        "Description": r.description or "",
        "AnalystCategory": r.analyst_category or "",
        "ImpliedPrice": r.implied_price or 0.0,
        "Total NB Qty": r.nb_qty_total or 0.0,
        "Total NB Nett Sales": r.nb_net_total or 0.0,
        "PromoFlag": r.promo_flag or 0,
        "channel_mix_ratio": r.channel_mix_ratio or 0.0,
        "fiscal_quarter": r.fiscal_quarter or 1,
        "Lag_1": r.lag_1 or 0.0,
        "Lag_4": r.lag_4 or 0.0,
        "Rolling_Mean_4": r.rolling_mean_4 or 0.0,
        "FiscalYear": r.fiscal_year or 0,
        "FiscalWeekNumber": r.fiscal_week_number or 0,
    } for r in records])

    # ── Get most recent row per product ───────────────────────────────────────
    latest_df = (
        df.sort_values(["FiscalYear", "FiscalWeekNumber"], ascending=False)
        .groupby("Description").first().reset_index()
    )

    # Calculate historical median price (excluding zero/promo anomalies) per SKU
    valid_prices = df[df["ImpliedPrice"] > 0.01]
    median_prices = valid_prices.groupby("Description")["ImpliedPrice"].median()
    
    # Map the median fallback to the latest_df
    latest_df["MedianPrice"] = latest_df["Description"].map(median_prices)
    # If the product actually only has zero prices (rare), fallback to an arbitrary small bound
    latest_df["MedianPrice"] = latest_df["MedianPrice"].fillna(10.00)

    # Use the median fallback if the current ImpliedPrice is effectively zero
    invalid_price_mask = latest_df["ImpliedPrice"] <= 0.05
    latest_df.loc[invalid_price_mask, "ImpliedPrice"] = latest_df.loc[invalid_price_mask, "MedianPrice"]

    # Ensure ImpliedPrice > 0 as an absolute failsafe
    latest_df["ImpliedPrice"] = latest_df["ImpliedPrice"].clip(lower=0.01)
    # Use 60% cost assumption
    latest_df["ImpliedCost"] = latest_df["ImpliedPrice"] * 0.60

    # ── Vectorised batch price simulation ─────────────────────────────────────
    # Instead of per-product loop, run batch predictions for each price multiplier
    N = len(latest_df)
    n_points = getattr(settings, "PRICE_GRID_POINTS", 10)
    lower = getattr(settings, "PRICE_LOWER_BOUND", 0.80)
    upper = getattr(settings, "PRICE_UPPER_BOUND", 1.20)
    multipliers = np.linspace(lower, upper, n_points)

    # Base demand prediction at current price (batch)
    base_features = latest_df[[f for f in feature_names if f in latest_df.columns]].copy()
    for f in feature_names:
        if f not in base_features.columns:
            base_features[f] = 0.0
    base_features = base_features[feature_names].fillna(0.0)
    base_demand = pipeline.predict(base_features)  # shape (N,)

    # Prepare price grid results arrays
    best_prices = latest_df["ImpliedPrice"].values.copy()
    best_revenue = np.zeros(N)
    best_margin = np.zeros(N)
    best_demand = base_demand.copy()
    best_elasticity = np.full(N, -1.0)
    best_obj = np.full(N, -np.inf)
    confidence = np.zeros(N)

    min_margin_pct = getattr(settings, "MIN_MARGIN_PCT", 0.10)

    for mult in multipliers:
        candidate_prices = latest_df["ImpliedPrice"].values * mult

        # Build feature batch with candidate price substituted into ImpliedPrice
        feat_batch = base_features.copy()
        if "ImpliedPrice" in feature_names:
            feat_batch["ImpliedPrice"] = candidate_prices

        pred_demand = pipeline.predict(feat_batch.fillna(0.0))  # shape (N,)
        pred_demand = np.maximum(pred_demand, 0.0)

        revenue = candidate_prices * pred_demand
        cost_arr = latest_df["ImpliedCost"].values
        gross_margin = (candidate_prices - cost_arr) * pred_demand
        margin_pct = np.where(
            candidate_prices > 0,
            (candidate_prices - cost_arr) / candidate_prices,
            0.0
        )

        # Elasticity at this multiplier
        base_d = np.maximum(base_demand, 1e-9)
        pct_demand_chg = (pred_demand - base_d) / base_d
        pct_price_chg = mult - 1.0
        elasticity = np.where(pct_price_chg != 0, pct_demand_chg / pct_price_chg, -1.0)

        # Constraint checks: margin >= 10%, candidate price > cost
        valid = (margin_pct >= min_margin_pct) & (candidate_prices > cost_arr)

        # Objective: revenue × margin factor, invalid points get -inf
        margin_factor = np.clip(margin_pct / max(min_margin_pct, 0.001), 0.0, 2.0)
        obj_score = np.where(valid, revenue * margin_factor, -np.inf)

        # Update best where this multiplier beats previous best
        improved = obj_score > best_obj
        best_prices = np.where(improved, candidate_prices, best_prices)
        best_revenue = np.where(improved, revenue, best_revenue)
        best_margin = np.where(improved, gross_margin, best_margin)
        best_demand = np.where(improved, pred_demand, best_demand)
        best_elasticity = np.where(improved, elasticity, best_elasticity)
        best_obj = np.where(improved, obj_score, best_obj)
        confidence += valid.astype(float)

    # ── Apply RL Multiplier Nudge ─────────────────────────────────────────────
    rl_agent = load_or_create_agent(settings.RL_POLICY_PATH)
    rl_multiplier = np.ones(N)
    for i in range(N):
        row_series = latest_df.iloc[i]
        # the agent returns a mult (e.g. 1.05) to push price towards higher margin if RL policy suggests It
        rl_multiplier[i] = get_rl_multiplier(rl_agent, row_series)
        
    # Scale best prices by RL nudge (capping between overall bounds)
    best_prices = best_prices * rl_multiplier
    best_prices = np.clip(best_prices, latest_df["ImpliedPrice"].values * lower, latest_df["ImpliedPrice"].values * upper)

    # Normalise confidence to 0-1
    confidence = confidence / n_points

    # Fall back to current price where no valid point found
    no_valid = best_obj == -np.inf
    best_prices = np.where(no_valid, latest_df["ImpliedPrice"].values, best_prices)
    best_demand = np.where(no_valid, base_demand, best_demand)
    best_revenue = np.where(no_valid, latest_df["ImpliedPrice"].values * base_demand, best_revenue)
    best_margin = np.where(no_valid, 0.0, best_margin)
    confidence = np.where(no_valid, 0.1, confidence)

    price_change_pct = np.where(
        latest_df["ImpliedPrice"].values > 0,
        (best_prices - latest_df["ImpliedPrice"].values) / latest_df["ImpliedPrice"].values,
        0.0
    )

    # ── Create optimisation run record ────────────────────────────────────────
    opt_run = OptimisationRun(
        id=run_id,
        model_version_id=active_mv.id,
        target_date=td,
        run_by=current_user.user_id,
        status="running",
    )
    db.add(opt_run)
    db.flush()

    # ── Build Recommendation objects ──────────────────────────────────────────
    recommendations = []
    for i, (_, row) in enumerate(latest_df.iterrows()):
        constraint_notes = "No valid price — held at current" if no_valid[i] else ""
        rec = Recommendation(
            optimisation_run_id=run_id,
            model_version_id=active_mv.id,
            description=str(row["Description"]),
            analyst_category=str(row.get("AnalystCategory", "")),
            target_date=td,
            current_price=round(float(row["ImpliedPrice"]), 4),
            recommended_price=round(float(best_prices[i]), 4),
            price_change_pct=round(float(price_change_pct[i]), 4),
            expected_demand=round(float(best_demand[i]), 2),
            expected_revenue=round(float(best_revenue[i]), 2),
            expected_margin=round(float(best_margin[i]), 2),
            confidence_score=round(float(confidence[i]), 4),
            elasticity=round(float(best_elasticity[i]), 4),
            elasticity_class=_classify_elasticity(float(best_elasticity[i])),
            top_drivers=None,
            constraint_notes=constraint_notes,
        )
        recommendations.append(rec)

    db.bulk_save_objects(recommendations)
    opt_run.sku_count = len(recommendations)
    opt_run.status = "complete"
    db.commit()

    write_audit_log(db, AuditEventType.OPTIMISATION_RUN, current_user.user_id, current_user.role,
                    "/run-optimisation",
                    {"run_id": run_id, "product_count": len(recommendations), "target_date": td},
                    ip)

    return OptimisationResponse(
        run_id=run_id,
        sku_count=len(recommendations),
        target_date=td,
        status="complete",
        message=f"Generated {len(recommendations)} price recommendations for {td}.",
    )
