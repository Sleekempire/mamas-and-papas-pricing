"""
security/csv_sanitizer.py — Protection against CSV formula injection.

Strips DDE/formula injection characters from all cell values.
See: https://owasp.org/www-community/attacks/CSV_Injection
"""
from __future__ import annotations

import re
from typing import List

import pandas as pd

# Characters that trigger spreadsheet formula execution
_FORMULA_PREFIXES = ("=", "+", "-", "@", "|", "\t", "\r", "\x00")

# DDE pattern (e.g. =DDE("cmd",...))
_DDE_PATTERN = re.compile(r"(?i)=\s*dde\s*\(")

# HYPERLINK pattern
_HYPERLINK_PATTERN = re.compile(r"(?i)=\s*hyperlink\s*\(")

# cmd/powershell injection
_CMD_PATTERN = re.compile(r"(?i)(cmd\.exe|powershell|/bin/sh|bash\s+-c)")


class CSVInjectionError(ValueError):
    """Raised when a critical injection pattern is found that cannot be stripped."""
    pass


def sanitise_cell(value: str) -> str:
    """Strip formula injection prefixes from a single cell string value."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    # Strip leading dangerous characters iteratively
    while stripped and stripped[0] in _FORMULA_PREFIXES:
        stripped = stripped[1:].strip()
    return stripped


def sanitise_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sanitise all string columns in a DataFrame against formula injection.
    Raises CSVInjectionError if DDE or shell injection patterns are found.
    """
    for col in df.select_dtypes(include="object").columns:
        col_str = df[col].astype(str)

        # Hard reject on DDE / cmd patterns
        for pattern, label in [
            (_DDE_PATTERN, "DDE"),
            (_HYPERLINK_PATTERN, "HYPERLINK"),
            (_CMD_PATTERN, "shell injection"),
        ]:
            if col_str.str.contains(pattern, regex=True).any():
                raise CSVInjectionError(
                    f"Rejected: {label} injection pattern detected in column '{col}'"
                )

        # Strip soft formula prefixes
        df[col] = df[col].apply(
            lambda v: sanitise_cell(str(v)) if pd.notna(v) else v
        )

    return df


def validate_file_extension(filename: str) -> None:
    """Ensure only .csv files are accepted."""
    if not filename.lower().endswith(".csv"):
        raise ValueError(f"Only CSV files are accepted. Got: '{filename}'")


def validate_file_size(size_bytes: int, max_mb: float = 50.0) -> None:
    """Enforce a maximum upload file size."""
    max_bytes = int(max_mb * 1024 * 1024)
    if size_bytes > max_bytes:
        raise ValueError(
            f"File size {size_bytes / 1024 / 1024:.1f} MB exceeds maximum {max_mb} MB"
        )
