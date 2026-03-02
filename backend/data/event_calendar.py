"""
data/event_calendar.py — Hard-coded Mamas & Papas promotional event calendar 2021-2025.

Based on the exact event schedule in the MAMASANDPAPAS PRICE MARKDOWN notebook.
Used to enrich/override Event and PromoFlag columns during data cleaning.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# ── Event calendars per (FiscalYear, FiscalWeekNumber) ───────────────────────
# Drawn verbatim from the Jupyter notebook's hard-coded event lists.

_EVENTS_2025 = [
    "EVENT", "Easter", "Easter", "Easter",
    "May Day", "Mayday", "May Day", "No Event",
    "Spring Sales", "Spring Sales", "No Event", "No Event", "No Event",
    "Summer Sale", "Summer Sale", "Summer Sale", "Summer Sale", "Summer Sale", "Summer Sale",
    "No Event", "No Event",
    "Aug BH", "Aug BH",
    "No Event", "No Event",
    "MSS", "MSS", "MSS",
    "No Event", "Thu",
    "Halloween", "Halloween", "No Event",
    "Black Friday", "Black Friday", "Black Friday",
    "Cyber",
    "No Event",
    "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale",
    "No Event", "Thu", "Event",
    "No Event", "No Event",
    "MSS", "No Event", "No Event", "Event",
]

_EVENTS_2024 = [
    "Easter", "Easter", "No Event", "May Day", "May Day", "May Day", "No Event",
    "The Spring", "The Spring", "The Spring",
    "No Event", "Summer Sales", "Summer Sales", "Summer Sales", "Summer Sales",
    "Summer Sales", "Summer Sales", "Summer Sales",
    "No Event", "Aug BH", "Aug BH", "Aug BH", "No Event",
    "MSS", "MSS", "MSS", "No Event", "The Halloween", "The Halloween",
    "The Halloween", "No Event", "No Event", "Black Friday", "Black Friday",
    "Black Friday", "No Event", "No Event", "Winter Sale",
    "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale",
    "No Event", "No Event", "Events", "Events", "No Event",
    "Mss", "Mss", "Mss", "No Event", "Easter",
]

_EVENTS_2023 = [
    "No Event", "Easter", "Easter", "May Day", "May Day", "No Event", "No Event",
    "No Event", "The Spring", "The Spring",
    "No Event", "Summer Sales", "Summer Sales", "Summer Sales", "Summer Sales",
    "Summer Sales", "Summer Sales", "No Event",
    "No Event", "No Event", "Aug BH", "Aug BH", "No Event",
    "MSS", "MSS", "MSS", "No Event", "The Halloween", "The Halloween",
    "The Halloween", "No Event", "No Event", "Black Friday", "Black Friday",
    "Black Friday", "No Event", "Winter Sale", "Winter Sale",
    "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale",
    "No Event", "No Event", "Events", "Events", "No Event",
    "Mss", "Mss", "Mss", "No Event", "Easter",
]

_EVENTS_2022 = [
    "Easter", "Easter", "No Event", "No Event", "May Day", "May Day",
    "No Event", "No Event", "The Spring", "The Spring", "No Event",
    "No Event", "Summer Sales", "Summer Sales", "Summer Sales", "Summer Sales",
    "Summer Sales", "No Event", "No Event", "No Event",
    "No Event", "Aug BH", "Aug BH", "No Event",
    "MSS", "MSS", "MSS", "MSS", "No Event", "No Event",
    "The Halloween", "The Halloween",
    "No Event", "No Event", "Black Friday", "Black Friday", "Cyber",
    "No Event", "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale",
    "Winter Sale", "Winter Sale", "No Event", "No Event",
    "Events", "Events", "No Event", "Mss", "Mss", "Mss",
]

_EVENTS_2021 = [
    "No Event", "Easter", "Easter", "May Day", "May Day", "No Event",
    "No Event", "No Event", "The Spring", "The Spring", "No Event",
    "Summer Sales", "Summer Sales", "Summer Sales", "Summer Sales",
    "Summer Sales", "Summer Sales", "No Event", "No Event", "No Event",
    "Aug BH", "Aug BH", "No Event", "No Event",
    "MSS", "MSS", "MSS", "MSS", "No Event",
    "The Halloween", "The Halloween", "No Event",
    "No Event", "Black Friday", "Black Friday", "Cyber",
    "No Event", "Winter Sale", "Winter Sale", "Winter Sale", "Winter Sale",
    "Winter Sale", "Winter Sale", "No Event", "No Event",
    "Events", "Events", "Mss", "Mss", "Mss", "No Event", "Easter",
]

# ── Mapping: year → 52-week event list ───────────────────────────────────────
_CALENDAR: Dict[int, list] = {
    2021: _EVENTS_2021,
    2022: _EVENTS_2022,
    2023: _EVENTS_2023,
    2024: _EVENTS_2024,
    2025: _EVENTS_2025,
}

# Non-promo event strings (anything else is promotional)
_NO_PROMO_STRINGS = {"no event", "no promotion", ""}


def get_event(fiscal_year: int, fiscal_week: int) -> Optional[str]:
    """
    Return the event name for a given fiscal year and week.
    Returns None if the year/week is out of range.
    Week is 1-indexed (1–52).
    """
    events = _CALENDAR.get(int(fiscal_year))
    if events is None:
        return None
    idx = int(fiscal_week) - 1
    if 0 <= idx < len(events):
        return events[idx]
    return None


def is_promo(event: Optional[str]) -> int:
    """Return 1 if the event string is promotional, else 0."""
    if event is None:
        return 0
    return 0 if event.strip().lower() in _NO_PROMO_STRINGS else 1


def enrich_events(df) -> None:
    """
    In-place: add/overwrite 'Event' and 'PromoFlag' columns using the hard-coded
    event calendar for rows where FiscalYear is in 2021–2025.
    Rows for other years keep whatever was in the original data (or 'No Promotion').
    """
    import pandas as pd

    if "FiscalYear" not in df.columns or "FiscalWeekNumber" not in df.columns:
        return

    # Ensure Event column exists
    if "Event" not in df.columns:
        df["Event"] = "No Promotion"
    # Ensure PromoFlag column exists
    if "PromoFlag" not in df.columns:
        df["PromoFlag"] = 0

    for year in _CALENDAR.keys():
        mask = df["FiscalYear"] == year
        if not mask.any():
            continue
        # Apply vectorised lookup
        weeks = df.loc[mask, "FiscalWeekNumber"]
        events_list = _CALENDAR[year]

        def _ev(w):
            idx = int(w) - 1
            if 0 <= idx < len(events_list):
                return events_list[idx]
            return "No Promotion"

        df.loc[mask, "Event"] = weeks.apply(_ev)
        df.loc[mask, "PromoFlag"] = df.loc[mask, "Event"].apply(
            lambda e: 0 if str(e).strip().lower() in _NO_PROMO_STRINGS else 1
        )
