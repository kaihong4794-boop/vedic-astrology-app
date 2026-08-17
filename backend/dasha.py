"""Vimshottari Dasha (120-year planetary period cycle) calculation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from astrology import DASHA_ORDER, NAKSHATRA_LORDS, NAKSHATRA_SPAN, PLANET_NAMES_ZH

DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}
TOTAL_CYCLE_YEARS = sum(DASHA_YEARS.values())  # 120
DAYS_PER_YEAR = 365.2425


@dataclass
class Period:
    lord: str
    start: datetime
    end: datetime

    @property
    def lord_zh(self) -> str:
        return PLANET_NAMES_ZH.get(self.lord, self.lord)


def _add_years(dt: datetime, years: float) -> datetime:
    return dt + timedelta(days=years * DAYS_PER_YEAR)


def _nakshatra_fraction_elapsed(moon_longitude: float) -> tuple[str, float]:
    moon_longitude = moon_longitude % 360
    idx = int(moon_longitude // NAKSHATRA_SPAN)
    within = moon_longitude % NAKSHATRA_SPAN
    fraction_elapsed = within / NAKSHATRA_SPAN
    return NAKSHATRA_LORDS[idx], fraction_elapsed


def compute_mahadashas(birth_dt_utc: datetime, moon_longitude: float, cycles: int = 2) -> list[Period]:
    """Compute Mahadasha (major period) sequence starting at birth.

    `cycles` controls how many full 120-year cycles to generate (2 is
    generous headroom beyond a human lifespan for "current dasha" lookups).
    """
    start_lord, frac_elapsed = _nakshatra_fraction_elapsed(moon_longitude)
    start_idx = DASHA_ORDER.index(start_lord)

    periods: list[Period] = []
    cursor = birth_dt_utc

    first_full_years = DASHA_YEARS[start_lord]
    first_balance_years = first_full_years * (1 - frac_elapsed)
    end = _add_years(cursor, first_balance_years)
    periods.append(Period(lord=start_lord, start=cursor, end=end))
    cursor = end

    total_spans = 9 * cycles
    for step in range(1, total_spans):
        lord = DASHA_ORDER[(start_idx + step) % 9]
        years = DASHA_YEARS[lord]
        end = _add_years(cursor, years)
        periods.append(Period(lord=lord, start=cursor, end=end))
        cursor = end

    return periods


def compute_antardashas(maha_period: Period) -> list[Period]:
    """Compute Antardasha (sub-period) sequence within one Mahadasha."""
    maha_years = DASHA_YEARS[maha_period.lord]
    start_idx = DASHA_ORDER.index(maha_period.lord)
    periods: list[Period] = []
    cursor = maha_period.start
    for offset in range(9):
        lord = DASHA_ORDER[(start_idx + offset) % 9]
        years = maha_years * DASHA_YEARS[lord] / TOTAL_CYCLE_YEARS
        end = _add_years(cursor, years)
        periods.append(Period(lord=lord, start=cursor, end=end))
        cursor = end
    # Correct rounding drift on the last sub-period so it ends exactly at
    # the parent Mahadasha's end.
    if periods:
        periods[-1].end = maha_period.end
    return periods


def find_current(periods: list[Period], at: datetime) -> Period | None:
    for p in periods:
        if p.start <= at < p.end:
            return p
    return periods[-1] if periods and at >= periods[-1].end else (periods[0] if periods else None)


def current_dasha_summary(birth_dt_utc: datetime, moon_longitude: float, at: datetime) -> dict:
    mahadashas = compute_mahadashas(birth_dt_utc, moon_longitude)
    current_maha = find_current(mahadashas, at)
    antardashas = compute_antardashas(current_maha)
    current_antar = find_current(antardashas, at)
    return {
        "mahadasha": current_maha,
        "antardasha": current_antar,
        "mahadashas": mahadashas,
        "antardashas": antardashas,
    }


def dasha_summary_zh(birth_dt_utc: datetime, moon_longitude: float, at: datetime) -> str:
    info = current_dasha_summary(birth_dt_utc, moon_longitude, at)
    maha: Period = info["mahadasha"]
    antar: Period = info["antardasha"]
    lines = [
        f"当前大运(Mahadasha): {maha.lord_zh}({maha.lord}) "
        f"{maha.start.date()} 至 {maha.end.date()}",
        f"当前小运(Antardasha): {antar.lord_zh}({antar.lord}) "
        f"{antar.start.date()} 至 {antar.end.date()}",
    ]
    upcoming = [p for p in info["mahadashas"] if p.start >= maha.start][:4]
    lines.append("未来大运序列: " + "、".join(f"{p.lord_zh}({p.start.date()})" for p in upcoming))
    return "\n".join(lines)
