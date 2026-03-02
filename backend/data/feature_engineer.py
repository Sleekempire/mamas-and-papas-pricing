"""
data/feature_engineer.py — Feature engineering for Mamas & Papas demand modelling.

Implements the exact feature set from the MAMASANDPAPAS PRICE MARKDOWN notebook:
  UnitPrice, UnitCost, Margin_%,
  Week_sin, Week_cos  (cyclical seasonality),
  log_Q, log_P        (log transforms for elasticity),
  Lag_1, Lag_4, Rolling_Mean_4  (temporal demand features),
  channel_mix_ratio, fiscal_quarter, PromoFlag.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd


# ── Target and feature definitions ───────────────────────────────────────────
TARGET_COLUMN = "Total NB Qty"   # Total demand across all channels

# Core ML features used by the demand model
MODEL_FEATURES: List[str] = [
    "ImpliedPrice",       # = UnitPrice: Total_Sales / Total_Qty
    "PromoFlag",
    "fiscal_quarter",
    "channel_mix_ratio",
    "Week_sin",           # NEW: cyclical week encoding
    "Week_cos",           # NEW: cyclical week encoding
    "Lag_1",
    "Lag_4",
    "Rolling_Mean_4",
]

# Additional derived columns needed for elasticity & RL (not used as ML features)
DERIVED_COLUMNS: List[str] = [
    "UnitPrice",
    "UnitCost",
    "Margin_%",
    "log_Q",
    "log_P",
]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add engineered features to the cleaned DataFrame.
    Input df must already be type-enforced by cleaner.py.
    """
    df = df.copy()

    # ── 1. Implied average selling price (= UnitPrice) ────────────────────────
    qty = pd.to_numeric(df["Total NB Qty"], errors="coerce").replace(0, np.nan)
    net = pd.to_numeric(df["Total NB Nett Sales"], errors="coerce")
    df["ImpliedPrice"] = (net / qty).fillna(0.0).clip(lower=0.0)
    df["UnitPrice"] = df["ImpliedPrice"]   # alias — notebook calls it UnitPrice

    # ── 2. Estimated Unit Cost ────────────────────────────────────────────────
    # UnitCost = (Total_Sales - Total_Profit) / Total_Qty  (proxy for COGS)
    profit_col = "Total NB Profit - Group"
    if profit_col in df.columns:
        profit = pd.to_numeric(df[profit_col], errors="coerce").fillna(0)
        df["UnitCost"] = ((net.fillna(0) - profit) / qty).fillna(0.0).clip(lower=0.0)
    else:
        df["UnitCost"] = df["UnitPrice"] * 0.50   # 50% cost fallback

    # ── 3. Gross Margin % ─────────────────────────────────────────────────────
    price_nonzero = df["UnitPrice"].replace(0, np.nan)
    df["Margin_%"] = ((df["UnitPrice"] - df["UnitCost"]) / price_nonzero).fillna(0.0).clip(-1.0, 1.0)

    # ── 4. PromoFlag — ensure numeric 0/1 ────────────────────────────────────
    if "PromoFlag" in df.columns:
        df["PromoFlag"] = pd.to_numeric(df["PromoFlag"], errors="coerce").fillna(0).clip(0, 1)
    else:
        df["PromoFlag"] = 0.0

    # ── 5. Fiscal quarter from FiscalWeekNumber ───────────────────────────────
    fw = pd.to_numeric(df.get("FiscalWeekNumber", pd.Series(dtype=float)), errors="coerce").fillna(1)
    df["fiscal_quarter"] = pd.cut(
        fw,
        bins=[0, 13, 26, 39, 53],
        labels=[1, 2, 3, 4],
        right=True,
    ).astype(float).fillna(1.0)

    # ── 6. Cyclical week seasonality (sin/cos) ────────────────────────────────
    # Matches: Week_sin = sin(2π * FiscalWeekNumber / 52)
    df["Week_sin"] = np.sin(2 * np.pi * fw / 52)
    df["Week_cos"] = np.cos(2 * np.pi * fw / 52)

    # ── 7. Channel mix ratio: home shopping / total ───────────────────────────
    hs_qty = pd.to_numeric(df.get("Home Shopping NB Qty", 0), errors="coerce").fillna(0)
    total_qty = pd.to_numeric(df["Total NB Qty"], errors="coerce").replace(0, np.nan)
    df["channel_mix_ratio"] = (hs_qty / total_qty).fillna(0.0).clip(0.0, 1.0)

    # ── 8. Lag and rolling features per Description (product) ────────────────
    sort_cols = ["Description", "FiscalYear", "FiscalWeekNumber"]
    available_sorts = [c for c in sort_cols if c in df.columns]
    df = df.sort_values(available_sorts).reset_index(drop=True)

    grp = df.groupby("Description")["Total NB Qty"]
    df["Lag_1"] = grp.shift(1).fillna(0.0)
    df["Lag_4"] = grp.shift(4).fillna(0.0)
    df["Rolling_Mean_4"] = (
        grp.transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    ).fillna(0.0)

    # ── 9. Log transforms for elasticity modelling ────────────────────────────
    # log_Q = log(Total_Qty),  log_P = log(UnitPrice)
    # We use log1p-style clipping to avoid log(0)
    qty_pos = df["Total NB Qty"].clip(lower=1e-6)
    price_pos = df["UnitPrice"].clip(lower=1e-6)
    df["log_Q"] = np.log(qty_pos)
    df["log_P"] = np.log(price_pos)

    return df


def get_feature_matrix(df: pd.DataFrame):
    """Return X (features) and y (target) arrays for model training."""
    available_features = [f for f in MODEL_FEATURES if f in df.columns]
    X = df[available_features].fillna(0.0)
    y = df[TARGET_COLUMN].fillna(0.0)
    return X, y, available_features
