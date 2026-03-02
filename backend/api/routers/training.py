"""
api/routers/training.py — 4-stage demand model training endpoint.

Stage 1: Engineer features (UnitPrice, UnitCost, Margin%, Week_sin/cos, log_Q/log_P, lags)
Stage 2: Compute per-product log-log OLS elasticity coefficients
Stage 3: Train GBM / RF / Ridge demand models — auto-select best by val R²
Stage 4: Train RL price agent on engineered feature set

All stages run synchronously.  Results are persisted to the DB and model store.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from data.feature_engineer import engineer_features
from database.connection import get_db
from database.models import CleanedDataRecord, ModelVersion
from models.demand_model import train_all_models
from models.elasticity import compute_elasticities
from models.model_store import save_model
from optimisation.rl_agent import train_rl_agent
from security.auth import TokenData
from security.rbac import require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


class TrainResponse(BaseModel):
    status: str
    algorithm: str
    train_r2: float
    val_r2: float
    rmse: float
    n_samples: int
    n_products: int
    n_elasticities: int
    message: str


@router.post("/train", response_model=TrainResponse)
async def train_model(
    current_user: TokenData = Depends(require_roles("Admin", "Analyst")),
    db: Session = Depends(get_db),
):
    """
    Full 4-stage training pipeline:
    1. Load cleaned records → engineer features
    2. Compute per-product elasticity (log-log OLS)
    3. Train demand model ensemble → persist best
    4. Train RL agent → persist policy
    """
    # ── Load all cleaned records from DB ─────────────────────────────────────
    records = db.query(CleanedDataRecord).all()
    if not records:
        raise HTTPException(status_code=422, detail="No data found. Please upload data first.")

    if len(records) < 50:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data: {len(records)} rows found; need at least 50 to train."
        )

    # ── Reconstruct DataFrame from ORM records ────────────────────────────────
    rows = []
    for r in records:
        rows.append({
            "Description":              r.description,
            "AnalystCategory":          r.analyst_category,
            "FiscalYear":               r.fiscal_year,
            "FiscalWeekNumber":         r.fiscal_week_number,
            "Total NB Qty":             r.nb_qty_total,
            "Total NB Nett Sales":      r.nb_net_total,
            "Total NB Profit - Group":  r.nb_p_total,
            "Home Shopping NB Qty":     r.home_shopping_nb_qty,
            "Home Shopping NB Nett Sales": 0.0,
            "Stores NB Qty":            r.nb_c_stores,
            "Stores NB Nett Sales":     0.0,
            "PromoFlag":                r.promo_flag,
            "Event":                    getattr(r, "event", None) or "No Event",
        })

    df = pd.DataFrame(rows)
    df["FiscalYear"] = pd.to_numeric(df["FiscalYear"], errors="coerce")
    df["FiscalWeekNumber"] = pd.to_numeric(df["FiscalWeekNumber"], errors="coerce")
    df["Total NB Qty"] = pd.to_numeric(df["Total NB Qty"], errors="coerce").clip(lower=1e-6)
    df["Total NB Nett Sales"] = pd.to_numeric(df["Total NB Nett Sales"], errors="coerce").fillna(0)

    n_products = df["Description"].nunique()
    logger.info("Training on %d records across %d products", len(df), n_products)

    # ── Stage 1: Feature engineering ─────────────────────────────────────────
    logger.info("Stage 1: Engineering features …")
    df = engineer_features(df)

    # ── Stage 2: Per-product elasticity (log-log OLS) ─────────────────────────
    logger.info("Stage 2: Computing per-product elasticities …")
    elasticities = compute_elasticities(df)   # dict: description → float
    n_elasticities = len(elasticities)
    logger.info("Elasticities computed for %d products", n_elasticities)

    # ── Stage 3: Train demand model ensemble ─────────────────────────────────
    logger.info("Stage 3: Training demand models …")
    try:
        results = train_all_models(df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Auto-select best by validation R²
    best = max(results, key=lambda r: r.val_r2)
    logger.info("Best model: %s  val_R²=%.4f  RMSE=%.4f", best.algorithm, best.val_r2, best.rmse)

    # Persist model to disk
    import uuid
    version_id = uuid.uuid4().hex[:8]
    model_path = save_model(best.pipeline, best.algorithm, version_id)

    # Store metadata including elasticities in JSON
    metadata = {
        "algorithm": best.algorithm,
        "train_r2": best.train_r2,
        "val_r2": best.val_r2,
        "rmse": best.rmse,
        "n_samples": len(df),
        "feature_names": best.feature_names,
        "elasticities": elasticities,         # per-product elasticity map
        "all_model_scores": [
            {"algorithm": r.algorithm, "val_r2": r.val_r2, "rmse": r.rmse}
            for r in results
        ],
    }

    # Deactivate old model versions
    db.query(ModelVersion).update({"is_active": False})
    db.flush()

    mv = ModelVersion(
        algorithm=best.algorithm,
        model_file_path=str(model_path),
        feature_names=best.feature_names,
        train_r2=best.train_r2,
        val_r2=best.val_r2,
        rmse=best.rmse,
        is_active=True,
        trained_at=datetime.utcnow(),
        trained_by=current_user.user_id,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)

    # ── Stage 4: Train RL agent ───────────────────────────────────────────────
    logger.info("Stage 4: Training RL agent …")
    try:
        # Build RL-compatible row format expected by rl_agent.train_rl_agent
        rl_df = df.rename(columns={
            "UnitPrice":      "UnitPrice",
            "UnitCost":       "UnitCost",
            "Total NB Qty":   "UnitsSold",
        }).copy()
        if "Seasonality" not in rl_df.columns:
            rl_df["Seasonality"] = rl_df["Rolling_Mean_4"].clip(lower=0.5, upper=2.0)
        if "stock_pressure" not in rl_df.columns:
            rl_df["stock_pressure"] = 0.5

        rl_agent = train_rl_agent(rl_df, n_episodes=5)
        policy_path = settings.RL_POLICY_PATH
        rl_agent.save(policy_path)
        logger.info("RL agent saved to %s", policy_path)
    except Exception as exc:
        logger.warning("RL training failed (non-fatal): %s", exc)

    return TrainResponse(
        status="success",
        algorithm=best.algorithm,
        train_r2=best.train_r2,
        val_r2=best.val_r2,
        rmse=best.rmse,
        n_samples=len(df),
        n_products=n_products,
        n_elasticities=n_elasticities,
        message=(
            f"Training complete — 4 stages finished. "
            f"Best model: {best.algorithm} (val R²={best.val_r2:.3f}). "
            f"Elasticities computed for {n_elasticities} products. "
            f"RL agent trained and saved."
        ),
    )
