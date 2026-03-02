"""
api/routers/recommendations.py
GET /recommendations          — Filtered list (all roles, max 500 rows)
GET /recommendations/{description}/explanation — Full SHAP-style explanation
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.connection import get_db
from database.models import CleanedDataRecord, ModelVersion, Recommendation
from data.feature_engineer import get_feature_matrix
from models.model_store import load_model
from optimisation.explainer import build_explanation
from security.audit import AuditEventType, write_audit_log
from security.auth import TokenData
from security.rbac import RequireAnyRole

router = APIRouter()

# ── Query anomaly tracking (in-memory, per-process) ───────────────────────────
_product_query_counter: defaultdict = defaultdict(int)


class RecommendationOut(BaseModel):
    description: str
    analyst_category: Optional[str]
    target_date: str
    current_price: float
    recommended_price: float
    price_change_pct: Optional[float]
    expected_demand: float
    expected_revenue: float
    expected_margin: float
    confidence_score: Optional[float]
    elasticity_class: Optional[str]


class RecommendationList(BaseModel):
    total: int
    results: List[RecommendationOut]


class ExplanationOut(BaseModel):
    description: str
    elasticity: float
    elasticity_class: str
    top_demand_drivers: list
    margin_sensitivity: dict
    stock_constraint: dict
    price_change_pct: float
    narrative: str


@router.get("/recommendations", response_model=RecommendationList)
async def get_recommendations(
    request: Request,
    target_date: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    description: Optional[str] = Query(None, description="Filter by product description"),
    limit: int = Query(50, ge=1, le=settings.MAX_RECOMMENDATION_ROWS),
    current_user: TokenData = Depends(RequireAnyRole),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"

    query = db.query(Recommendation)
    if target_date:
        query = query.filter(Recommendation.target_date == target_date)
    if category:
        query = query.filter(Recommendation.analyst_category.ilike(f"%{category}%"))
    if description:
        desc_upper = description.upper().strip()
        query = query.filter(Recommendation.description.ilike(f"%{desc_upper}%"))

    total = query.count()
    rows = query.order_by(Recommendation.created_at.desc()).limit(limit).all()

    write_audit_log(db, AuditEventType.RECOMMENDATION_ACCESS, current_user.user_id, current_user.role,
                    "/recommendations",
                    {"filters": {"date": target_date, "category": category, "description": description}, "count": len(rows)},
                    ip)

    return RecommendationList(
        total=total,
        results=[RecommendationOut(
            description=r.description,
            analyst_category=r.analyst_category,
            target_date=r.target_date,
            current_price=r.current_price,
            recommended_price=r.recommended_price,
            price_change_pct=r.price_change_pct,
            expected_demand=r.expected_demand,
            expected_revenue=r.expected_revenue,
            expected_margin=r.expected_margin,
            confidence_score=r.confidence_score,
            elasticity_class=r.elasticity_class,
        ) for r in rows],
    )


@router.get("/recommendations/explanation/{description:path}", response_model=ExplanationOut)
async def get_explanation(
    description: str,
    request: Request,
    target_date: Optional[str] = Query(None),
    current_user: TokenData = Depends(RequireAnyRole),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    desc_upper = description.upper().strip()

    # ── Anomaly detection: flag repeated rapid product queries ────────────────
    _product_query_counter[f"{current_user.user_id}:{desc_upper}"] += 1
    query_count = _product_query_counter[f"{current_user.user_id}:{desc_upper}"]
    if query_count > settings.SKU_QUERY_ANOMALY_THRESHOLD:
        write_audit_log(db, AuditEventType.ANOMALY_DETECTED, current_user.user_id, current_user.role,
                        f"/recommendations/{desc_upper}/explanation",
                        {"description": desc_upper, "query_count": query_count}, ip)

    # ── Load recommendation ───────────────────────────────────────────────────
    q = db.query(Recommendation).filter(Recommendation.description.ilike(f"%{desc_upper}%"))
    if target_date:
        q = q.filter(Recommendation.target_date == target_date)
    rec = q.order_by(Recommendation.created_at.desc()).first()

    if not rec:
        raise HTTPException(status_code=404, detail=f"No recommendation found for '{desc_upper}'")

    # ── Load active model ─────────────────────────────────────────────────────
    mv = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    if not mv:
        raise HTTPException(status_code=422, detail="No active model available")

    pipeline = load_model(mv.model_file_path)
    feature_names = mv.feature_names or []

    # ── Load product data for permutation importance ──────────────────────────
    product_records = db.query(CleanedDataRecord).filter(
        CleanedDataRecord.description == rec.description
    ).all()

    if len(product_records) < 3:
        return ExplanationOut(
            description=desc_upper,
            elasticity=rec.elasticity or -1.0,
            elasticity_class=rec.elasticity_class or "Neutral",
            top_demand_drivers=[{"feature": "ImpliedPrice", "importance": 1.0, "direction": "negative"}],
            margin_sensitivity={"price_range": {}, "margin_range": {}, "curve": []},
            stock_constraint={"current_stock": 0, "safe_stock_threshold": 0},
            price_change_pct=round((rec.price_change_pct or 0.0) * 100, 2),
            narrative="Insufficient product history for detailed explanation.",
        )

    df_prod = pd.DataFrame([{
        "ImpliedPrice": r.implied_price or 0.0,
        "Total NB Qty": r.nb_qty_total or 0.0,
        "PromoFlag": r.promo_flag or 0,
        "channel_mix_ratio": r.channel_mix_ratio or 0.0,
        "fiscal_quarter": r.fiscal_quarter or 1,
        "Lag_1": r.lag_1 or 0.0,
        "Lag_4": r.lag_4 or 0.0,
        "Rolling_Mean_4": r.rolling_mean_4 or 0.0,
        "Week_sin": np.sin(2 * np.pi * (r.fiscal_week_number or 1) / 52),
        "Week_cos": np.cos(2 * np.pi * (r.fiscal_week_number or 1) / 52),
    } for r in product_records])

    X_prod, y_prod, _ = get_feature_matrix(df_prod)
    feature_row = df_prod.iloc[-1]
    last_rec = product_records[-1]
    implied_cost = (last_rec.implied_price or 0.0) * 0.60

    explanation = build_explanation(
        pipeline=pipeline,
        sku=rec.description,
        feature_row=feature_row,
        feature_names=feature_names,
        X_sku=X_prod,
        y_sku=y_prod,
        current_price=rec.current_price,
        unit_cost=implied_cost,
        recommended_price=rec.recommended_price,
        elasticity=rec.elasticity or -1.0,
        stock_level=last_rec.nb_qty_total or 0.0,
    )

    write_audit_log(db, AuditEventType.EXPLANATION_ACCESS, current_user.user_id, current_user.role,
                    f"/recommendations/{desc_upper}/explanation",
                    {"description": desc_upper}, ip)

    return ExplanationOut(
        description=explanation["sku"],
        elasticity=explanation["elasticity"],
        elasticity_class=explanation["elasticity_class"],
        top_demand_drivers=explanation["top_demand_drivers"],
        margin_sensitivity=explanation["margin_sensitivity"],
        stock_constraint=explanation["stock_constraint"],
        price_change_pct=explanation["price_change_pct"],
        narrative=explanation["narrative"],
    )
