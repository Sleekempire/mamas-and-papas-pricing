"""
data/validator.py — Strict schema validation and column allowlisting.
Accepts the Mamas & Papas retail channel-based data format.
Actual column names from MamasAndPapas_Final_Pricing_Dataset.csv
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd


# ── Approved column schema ────────────────────────────────────────────────────
REQUIRED_COLUMNS: List[str] = [
    "FiscalYear",
    "FiscalWeekNumber",
    "AnalystCategory",
    "Description",
    "Total NB Qty",
    "Total NB Nett Sales",
]

OPTIONAL_COLUMNS: List[str] = [
    "DayOfWeek",
    "Group",
    "SubGroup",
    "Home Shopping NB Qty",
    "Home Shopping NB Nett Sales",
    "Home Shopping NB Profit - Group",
    "Stores NB Qty",
    "Stores NB Nett Sales",
    "Stores NB Profit - Group",
    "Total NB Profit - Group",
    "Event",
    "PromoFlag",
]

ALLOWED_COLUMNS: List[str] = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# Columns expected to be numeric
NUMERIC_COLUMNS: List[str] = [
    "FiscalYear",
    "FiscalWeekNumber",
    "Total NB Qty",
    "Total NB Nett Sales",
    "Home Shopping NB Qty",
    "Home Shopping NB Nett Sales",
    "Stores NB Qty",
    "Stores NB Nett Sales",
    "Total NB Profit - Group",
    "PromoFlag",
]

# String / categorical columns
STRING_COLUMNS: List[str] = [
    "AnalystCategory",
    "Group",
    "SubGroup",
    "Description",
    "DayOfWeek",
    "Event",
]


class SchemaValidationError(ValueError):
    def __init__(self, message: str, errors: List[str]):
        super().__init__(message)
        self.errors = errors


def validate_schema(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Validate and enforce the column allowlist.

    Returns:
        (filtered_df, warnings) — df with only allowed columns, plus any warnings.

    Raises:
        SchemaValidationError if required columns are missing or no rows remain.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Normalise column names: strip whitespace
    df.columns = [c.strip() for c in df.columns]

    incoming_cols = set(df.columns.tolist())
    required_set = set(REQUIRED_COLUMNS)
    allowed_set = set(ALLOWED_COLUMNS)

    # 1. Strip extra columns (allowlist enforcement)
    extra_cols = incoming_cols - allowed_set
    if extra_cols:
        warnings.append(f"Extra columns stripped (not in allowlist): {sorted(extra_cols)}")

    # 2. Check all required columns are present
    missing_required = required_set - incoming_cols
    if missing_required:
        errors.append(f"Missing required columns: {sorted(missing_required)}")

    if errors:
        raise SchemaValidationError("Schema validation failed", errors)

    # 3. Keep only allowed columns that exist in this file
    cols_to_keep = [c for c in ALLOWED_COLUMNS if c in incoming_cols]
    df = df[cols_to_keep].copy()

    # 4. Validate numeric coercibility for numeric columns
    coerce_errors: List[str] = []
    for col in NUMERIC_COLUMNS:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        bad_pct = numeric.isna().mean()
        if bad_pct > 0.5:
            coerce_errors.append(
                f"Column '{col}': >50% values cannot be coerced to numeric ({bad_pct:.0%} invalid)"
            )

    if coerce_errors:
        raise SchemaValidationError("Type coercion validation failed", coerce_errors)

    # 5. Reject completely empty uploads
    if len(df) == 0:
        raise SchemaValidationError("Upload contains no rows", ["Empty DataFrame after column filter"])

    return df, warnings
