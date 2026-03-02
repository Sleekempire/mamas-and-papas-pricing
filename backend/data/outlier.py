"""
data/outlier.py — IQR-based outlier detection and quarantine handling.
Targets the Mamas & Papas channel qty schema.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd
import numpy as np


OUTLIER_COLUMNS = [
    "NB Qty Total",
    "NB Net Total",
    "ImpliedPrice",
    "Home Shopping NB Qty",
    "Home Shop NB Qty",
]
DEFAULT_IQR_MULTIPLIER = 3.0


def detect_outliers(
    df: pd.DataFrame,
    columns: List[str] = OUTLIER_COLUMNS,
    iqr_multiplier: float = DEFAULT_IQR_MULTIPLIER,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, dict]]:
    """
    Detect and quarantine outliers using the IQR method per column.

    Returns:
        (clean_df, quarantined_df, stats)
        - clean_df: DataFrame with outlier rows removed
        - quarantined_df: DataFrame of outlier rows with 'quarantine_reason' column
        - stats: Dict mapping column → {q1, q3, iqr, lower_fence, upper_fence, count}
    """
    outlier_mask = pd.Series(False, index=df.index)
    quarantine_reasons: Dict[int, List[str]] = {i: [] for i in df.index}
    stats: Dict[str, dict] = {}

    for col in columns:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) < 10:
            # Not enough data for IQR analysis on this column
            continue

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_fence = q1 - iqr_multiplier * iqr
        upper_fence = q3 + iqr_multiplier * iqr

        stats[col] = {
            "q1": round(float(q1), 4),
            "q3": round(float(q3), 4),
            "iqr": round(float(iqr), 4),
            "lower_fence": round(float(lower_fence), 4),
            "upper_fence": round(float(upper_fence), 4),
        }

        col_vals = pd.to_numeric(df[col], errors="coerce")
        low_mask = (col_vals < lower_fence) & df.index.isin(series.index)
        high_mask = (col_vals > upper_fence) & df.index.isin(series.index)

        col_mask = low_mask | high_mask
        stats[col]["count"] = int(col_mask.sum())
        outlier_mask = outlier_mask | col_mask

        for idx in df.index[col_mask]:
            val = df.at[idx, col]
            if low_mask.at[idx]:
                quarantine_reasons[idx].append(
                    f"{col}={val:.2f} below lower fence {lower_fence:.2f}"
                )
            else:
                quarantine_reasons[idx].append(
                    f"{col}={val:.2f} above upper fence {upper_fence:.2f}"
                )

    clean_df = df[~outlier_mask].copy().reset_index(drop=True)

    quarantined_df = df[outlier_mask].copy()
    quarantined_df["quarantine_reason"] = [
        "; ".join(quarantine_reasons[i]) for i in quarantined_df.index
    ]
    quarantined_df = quarantined_df.reset_index(drop=True)

    return clean_df, quarantined_df, stats
