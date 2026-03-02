"""
data/cleaner.py — Data cleaning and type enforcement for Mamas & Papas retail channel schema.
After cleaning, enriches Event and PromoFlag using the hard-coded event calendar.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from data.validator import NUMERIC_COLUMNS, STRING_COLUMNS, REQUIRED_COLUMNS
from data.event_calendar import enrich_events


def clean_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Clean and type-enforce a validated DataFrame.
    Returns (cleaned_df, messages).
    """
    messages: List[str] = []
    original_len = len(df)

    # 1. Coerce numeric columns
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 2. Drop rows missing required values
    required_numeric = [c for c in REQUIRED_COLUMNS if c in NUMERIC_COLUMNS and c in df.columns]
    null_mask = df[required_numeric].isnull().any(axis=1)
    dropped_null = null_mask.sum()
    if dropped_null > 0:
        messages.append(f"Dropped {dropped_null} rows with null values in required columns")
        df = df[~null_mask].copy()

    # 3. Drop rows where total quantity is zero or negative (no sales activity)
    qty_col = "Total NB Qty"
    if qty_col in df.columns:
        bad_qty = df[qty_col] <= 0
        if bad_qty.sum() > 0:
            messages.append(f"Dropped {bad_qty.sum()} rows with zero/negative Total NB Qty")
            df = df[~bad_qty].copy()

    # 4. Floor all quantity/revenue columns at 0
    floor_cols = [
        "Total NB Qty", "Total NB Nett Sales", "Total NB Profit - Group",
        "Home Shopping NB Qty", "Home Shopping NB Nett Sales",
        "Stores NB Qty", "Stores NB Nett Sales",
    ]
    for col in floor_cols:
        if col in df.columns:
            neg_count = (df[col] < 0).sum()
            if neg_count > 0:
                messages.append(f"Floored {neg_count} negative values in '{col}' to 0")
                df[col] = df[col].clip(lower=0.0)

    # 5. Clean string columns: strip whitespace
    for col in STRING_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # 6. Normalise Description (product identity)
    if "Description" in df.columns:
        df["Description"] = df["Description"].str.strip().str.upper()

    # 7. Enforce integer-like FiscalYear / FiscalWeekNumber
    for col in ["FiscalYear", "FiscalWeekNumber"]:
        if col in df.columns:
            df[col] = df[col].round(0).astype("Int64")

    # 8. Normalise PromoFlag to 0/1 from CSV (will be overridden by calendar below)
    if "PromoFlag" in df.columns:
        df["PromoFlag"] = pd.to_numeric(df["PromoFlag"], errors="coerce").fillna(0).clip(0, 1).astype(int)

    # 9. Enrich Event and PromoFlag from the hard-coded calendar (2021-2025)
    #    This overrides whatever was in the CSV with the authoritative event schedule.
    enrich_events(df)
    messages.append("Event and PromoFlag enriched from Mamas & Papas event calendar (2021–2025)")

    # 10. Reset index
    df = df.reset_index(drop=True)

    messages.append(
        f"Cleaning complete: {len(df)} clean rows from {original_len} original rows "
        f"({original_len - len(df)} removed)"
    )
    return df, messages
