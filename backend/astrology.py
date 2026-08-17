"""Vedic (sidereal, Lahiri ayanamsa) natal chart calculation using pyswisseph.

Uses the Moshier semi-analytic ephemeris (FLG_MOSEPH) so no external
ephemeris data files need to be downloaded or deployed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import swisseph as swe

FLAGS = swe.FLG_SIDEREAL | swe.FLG_MOSEPH

SIGNS = [
    "白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
    "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
]

NAKSHATRAS = [
    "Ashwini 阿湿宁", "Bharani 婆罗尼", "Krittika 克利提卡", "Rohini 罗希尼",
    "Mrigashira 姆里加西拉", "Ardra 阿德拉", "Punarvasu 普纳瓦苏", "Pushya 普沙",
    "Ashlesha 阿修莱莎", "Magha 玛伽", "Purva Phalguni 布尔瓦帕古尼",
    "Uttara Phalguni 优塔拉帕古尼", "Hasta 哈斯塔", "Chitra 奇特拉",
    "Swati 斯瓦提", "Vishakha 毗萨迦", "Anuradha 阿努拉达", "Jyeshtha 杰斯塔",
    "Mula 慕拉", "Purva Ashadha 布尔瓦阿沙达", "Uttara Ashadha 优塔拉阿沙达",
    "Shravana 室罗筏拿", "Dhanishta 达尼什塔", "Shatabhisha 沙塔比沙",
    "Purva Bhadrapada 布尔瓦跋达罗钵陀", "Uttara Bhadrapada 优塔拉跋达罗钵陀",
    "Revati 瑞瓦提",
]

# Vimshottari dasha order — also used to find each nakshatra's ruling lord
# (27 nakshatras cycle through the 9 lords exactly 3 times).
DASHA_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
NAKSHATRA_LORDS = DASHA_ORDER * 3

PLANET_NAMES_ZH = {
    "Sun": "太阳", "Moon": "月亮", "Mars": "火星", "Mercury": "水星",
    "Jupiter": "木星", "Venus": "金星", "Saturn": "土星",
    "Rahu": "罗睺", "Ketu": "计都",
}

_PLANET_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,
}

NAKSHATRA_SPAN = 360.0 / 27.0


@dataclass
class Point:
    name: str
    longitude: float
    sign_index: int
    sign_name: str
    sign_degree: float
    nakshatra_index: int
    nakshatra_name: str
    nakshatra_pada: int
    nakshatra_lord: str
    house: int


@dataclass
class Chart:
    ascendant: Point
    planets: dict[str, Point] = field(default_factory=dict)
    moon_longitude: float = 0.0


def julian_day_ut(dt_utc: datetime) -> float:
    hour = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, swe.GREG_CAL)


def _sign_of(longitude: float) -> tuple[int, str, float]:
    longitude = longitude % 360
    idx = int(longitude // 30)
    return idx, SIGNS[idx], longitude % 30


def _nakshatra_of(longitude: float) -> tuple[int, str, int, str]:
    longitude = longitude % 360
    idx = int(longitude // NAKSHATRA_SPAN)
    within = longitude % NAKSHATRA_SPAN
    pada = int(within // (NAKSHATRA_SPAN / 4)) + 1
    return idx, NAKSHATRAS[idx], pada, NAKSHATRA_LORDS[idx]


def _make_point(name: str, longitude: float, asc_sign_index: int) -> Point:
    sign_idx, sign_name, sign_deg = _sign_of(longitude)
    nak_idx, nak_name, pada, nak_lord = _nakshatra_of(longitude)
    house = (sign_idx - asc_sign_index) % 12 + 1
    return Point(
        name=name,
        longitude=longitude,
        sign_index=sign_idx,
        sign_name=sign_name,
        sign_degree=sign_deg,
        nakshatra_index=nak_idx,
        nakshatra_name=nak_name,
        nakshatra_pada=pada,
        nakshatra_lord=nak_lord,
        house=house,
    )


def compute_chart(dt_utc: datetime, lat: float, lon: float) -> Chart:
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    jd = julian_day_ut(dt_utc)

    cusps, ascmc = swe.houses_ex(jd, lat, lon, b"W", swe.FLG_SIDEREAL)
    asc_longitude = ascmc[0]
    asc_sign_idx, _, _ = _sign_of(asc_longitude)
    ascendant = _make_point("Ascendant", asc_longitude, asc_sign_idx)
    ascendant.house = 1

    planets: dict[str, Point] = {}
    moon_longitude = 0.0
    for name, pid in _PLANET_IDS.items():
        xx, _ret_flags = swe.calc_ut(jd, pid, FLAGS)
        longitude = xx[0]
        planets[name] = _make_point(name, longitude, asc_sign_idx)
        if name == "Moon":
            moon_longitude = longitude

    rahu_longitude = planets["Rahu"].longitude
    ketu_longitude = (rahu_longitude + 180) % 360
    planets["Ketu"] = _make_point("Ketu", ketu_longitude, asc_sign_idx)

    return Chart(ascendant=ascendant, planets=planets, moon_longitude=moon_longitude)


def format_degree(deg: float) -> str:
    d = int(deg)
    m_full = (deg - d) * 60
    m = int(m_full)
    return f"{d}°{m:02d}'"


def chart_summary_zh(chart: Chart) -> str:
    lines = []
    a = chart.ascendant
    lines.append(
        f"上升(Lagna): {a.sign_name} {format_degree(a.sign_degree)}，"
        f"星宿: {a.nakshatra_name} 第{a.nakshatra_pada}分度"
    )
    order = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
    for name in order:
        p = chart.planets[name]
        zh = PLANET_NAMES_ZH[name]
        lines.append(
            f"{zh}({name}): {p.sign_name} {format_degree(p.sign_degree)}，第{p.house}宫，"
            f"星宿: {p.nakshatra_name} 第{p.nakshatra_pada}分度"
        )
    return "\n".join(lines)
