"""
models/elasticity.py — Per-product log-log OLS price elasticity estimation.

Method (from MAMASANDPAPAS PRICE MARKDOWN notebook):
    log(Total_Qty) ~ β0 + β1 * log(UnitPrice) + β2 * PromoFlag
                   + β3 * Week_sin + β4 * Week_cos

β1 is the price elasticity coefficient.  Theoretically it should be ≤ 0.
A value of -1 means 1% price rise → 1% demand fall (unit elastic).

Products with fewer than MIN_OBS observations fall back to their
AnalystCategory-level elasticity, which in turn falls back to GLOBAL_FALLBACK.
"""
from __future__ import annotations

import warnings
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# Minimum observations needed to compute a reliable per-product elasticity
MIN_OBS = 10
# Global fallback elasticity if we have nothing
GLOBAL_FALLBACK = -1.0


def _ols_elasticity(sub: pd.DataFrame) -> Optional[float]:
    """
    Fit log-log OLS on a sub-DataFrame for a single product or category.
    Returns the price elasticity coefficient (β1), or None if fitting fails.
    """
    try:
        required = ["log_P", "log_Q"]
        if not all(c in sub.columns for c in required):
            return None
        mask = sub["log_Q"].notna() & sub["log_P"].notna() & np.isfinite(sub["log_Q"]) & np.isfinite(sub["log_P"])
        sub = sub[mask]
        if len(sub) < 3:
            return None

        # Build feature matrix
        feature_cols = ["log_P"]
        optional_cols = ["PromoFlag", "Week_sin", "Week_cos"]
        for c in optional_cols:
            if c in sub.columns and sub[c].notna().any():
                feature_cols.append(c)

        X = sub[feature_cols].fillna(0.0).values
        y = sub["log_Q"].values

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reg = LinearRegression()
            reg.fit(X, y)

        # Coefficient on log_P is at index 0 (first feature)
        elasticity = float(reg.coef_[0])
        # Sanity clip: elasticities beyond ±10 are numerical artefacts
        return float(np.clip(elasticity, -10.0, 2.0))
    except Exception:
        return None


def compute_elasticities(df: pd.DataFrame) -> Dict[str, float]:
    """
    Compute a price elasticity per Description using log-log OLS.
    Also computes category-level and global fallbacks.

    Returns a dict mapping description (upper-case) → elasticity float.
    """
    result: Dict[str, float] = {}

    if "log_P" not in df.columns or "log_Q" not in df.columns:
        return result

    # ── Global fallback ───────────────────────────────────────────────────────
    global_elast = _ols_elasticity(df) or GLOBAL_FALLBACK

    # ── Category-level elasticities ───────────────────────────────────────────
    cat_col = "AnalystCategory" if "AnalystCategory" in df.columns else None
    category_elast: Dict[str, float] = {}
    if cat_col:
        for cat, grp in df.groupby(cat_col):
            e = _ols_elasticity(grp)
            if e is not None:
                category_elast[str(cat)] = e

    # ── Per-product elasticities ──────────────────────────────────────────────
    if "Description" not in df.columns:
        return result

    for desc, grp in df.groupby("Description"):
        desc_key = str(desc).strip().upper()

        if len(grp) >= MIN_OBS:
            elast = _ols_elasticity(grp)
        else:
            elast = None

        if elast is None:
            # Fallback to category
            cat_val = grp[cat_col].iloc[0] if cat_col else None
            elast = category_elast.get(str(cat_val), global_elast) if cat_val else global_elast

        result[desc_key] = round(elast, 4)

    return result


def classify_elasticity(elasticity: float) -> str:
    """
    Map an elasticity coefficient to a human-readable class.
    Matches the notebook's classification scheme.
    """
    if elasticity < -2.0:
        return "Highly Elastic"
    elif elasticity < -1.0:
        return "Elastic"
    elif elasticity < -0.5:
        return "Inelastic"
    else:
        return "Highly Inelastic"
