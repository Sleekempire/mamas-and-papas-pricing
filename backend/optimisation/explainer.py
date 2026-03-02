"""
optimisation/explainer.py — SHAP-style permutation feature importance.
Computes per-SKU feature importances and demand driver explanations.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from models.demand_model import predict_demand
from optimisation.constraints import classify_elasticity


def compute_permutation_importance(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    n_repeats: int = 5,
) -> List[Dict]:
    """
    Compute permutation importance for each feature.
    Returns list of {feature, importance, direction} sorted by importance desc.
    """
    baseline_pred = predict_demand(pipeline, X)
    baseline_mse = float(np.mean((y.values - baseline_pred) ** 2))

    importances: Dict[str, float] = {}
    directions: Dict[str, str] = {}

    for col in X.columns:
        scores = []
        for _ in range(n_repeats):
            X_perm = X.copy()
            X_perm[col] = np.random.permutation(X_perm[col].values)
            perm_pred = predict_demand(pipeline, X_perm)
            perm_mse = float(np.mean((y.values - perm_pred) ** 2))
            scores.append(perm_mse - baseline_mse)
        importances[col] = float(np.mean(scores))

        # Directionality: positive correlation → higher = more demand
        corr = float(np.corrcoef(X[col].values, y.values)[0, 1])
        directions[col] = "positive" if corr >= 0 else "negative"

    # Normalise importances to [0, 1]
    max_imp = max(importances.values()) if importances else 1.0
    if max_imp > 0:
        norm_imps = {k: v / max_imp for k, v in importances.items()}
    else:
        norm_imps = importances

    sorted_features = sorted(norm_imps.items(), key=lambda x: x[1], reverse=True)

    return [
        {
            "feature": feat,
            "importance": round(max(0.0, imp), 4),
            "direction": directions.get(feat, "unknown"),
        }
        for feat, imp in sorted_features[:8]  # Return top 8 features
    ]


def compute_margin_sensitivity(
    pipeline: Pipeline,
    feature_row: pd.Series,
    feature_names: List[str],
    current_price: float,
    unit_cost: float,
) -> Dict:
    """Assess how margin changes across the simulated price range."""
    from config import settings
    prices = np.linspace(
        current_price * settings.PRICE_LOWER_BOUND,
        current_price * settings.PRICE_UPPER_BOUND,
        10,
    )
    rows = []
    for p in prices:
        r = feature_row.copy()
        r["UnitPrice"] = p
        if p > 0:
            r["margin_pct"] = (p - unit_cost) / p
        rows.append({k: r.get(k, 0.0) for k in feature_names})

    feat_df = pd.DataFrame(rows)
    demands = predict_demand(pipeline, feat_df)
    margins = [(p - unit_cost) * d for p, d in zip(prices, demands)]

    return {
        "price_range": {"min": round(float(prices[0]), 2), "max": round(float(prices[-1]), 2)},
        "margin_range": {
            "min": round(float(min(margins)), 2),
            "max": round(float(max(margins)), 2),
        },
        "peak_margin_price": round(float(prices[int(np.argmax(margins))]), 2),
        "curve": [
            {"price": round(float(p), 2), "margin": round(float(m), 2)}
            for p, m in zip(prices, margins)
        ],
    }


def build_explanation(
    pipeline: Pipeline,
    sku: str,
    feature_row: pd.Series,
    feature_names: List[str],
    X_sku: pd.DataFrame,
    y_sku: pd.Series,
    current_price: float,
    unit_cost: float,
    recommended_price: float,
    elasticity: float,
    stock_level: float,
) -> Dict:
    """
    Build a full SHAP-style explanation for a SKU recommendation.
    """
    top_drivers = compute_permutation_importance(pipeline, X_sku, y_sku)
    margin_sensitivity = compute_margin_sensitivity(
        pipeline, feature_row, feature_names, current_price, unit_cost
    )

    return {
        "sku": sku,
        "elasticity": round(elasticity, 4),
        "elasticity_class": classify_elasticity(elasticity),
        "top_demand_drivers": top_drivers,
        "margin_sensitivity": margin_sensitivity,
        "stock_constraint": {
            "current_stock": round(float(stock_level), 0),
            "safe_stock_threshold": round(float(stock_level * 0.9), 0),
        },
        "price_change_pct": round(
            (recommended_price - current_price) / current_price * 100, 2
        ) if current_price > 0 else 0.0,
        "narrative": _build_narrative(top_drivers, elasticity, margin_sensitivity),
    }


def _build_narrative(top_drivers: List[Dict], elasticity: float, margin_sense: Dict) -> str:
    """Generate a plain-English explanation of the pricing recommendation."""
    if not top_drivers:
        return "Insufficient data for explanation."

    top_feat = top_drivers[0]["feature"] if top_drivers else "UnitPrice"
    elast_class = classify_elasticity(elasticity)
    peak_price = margin_sense.get("peak_margin_price", "N/A")

    lines = [
        f"The primary demand driver is '{top_feat}' (importance: {top_drivers[0]['importance']:.2f}).",
        f"Demand is {elast_class.lower()} with an elasticity of {elasticity:.2f}.",
        f"Peak margin is achieved at a price of £{peak_price}.",
    ]
    if len(top_drivers) > 1:
        lines.append(
            f"Secondary drivers include: {', '.join(d['feature'] for d in top_drivers[1:4])}."
        )
    return " ".join(lines)
