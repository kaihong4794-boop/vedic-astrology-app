"""FastAPI backend for the Vedic astrology reading web app."""
from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import astrology
import dasha
import geocode
import interpretation

app = FastAPI(title="Vedic Astrology Reading")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class GeocodeResult(BaseModel):
    display_name: str
    lat: float
    lon: float
    timezone: str | None


class ChartRequest(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    birth_date: str  # "YYYY-MM-DD"
    birth_time: str  # "HH:MM"
    lat: float
    lon: float
    timezone: str  # IANA tz name, e.g. "Asia/Shanghai"


def _calc_age(birth: date, today: date) -> float:
    days = (today - birth).days
    return days / 365.2425


def _point_to_dict(p: astrology.Point) -> dict:
    return {
        "name": p.name,
        "name_zh": astrology.PLANET_NAMES_ZH.get(p.name, p.name),
        "sign": p.sign_name,
        "sign_index": p.sign_index,
        "sign_degree": astrology.format_degree(p.sign_degree),
        "house": p.house,
        "nakshatra": p.nakshatra_name,
        "pada": p.nakshatra_pada,
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/geocode", response_model=list[GeocodeResult])
async def api_geocode(q: str):
    if not q or not q.strip():
        raise HTTPException(400, "请输入城市名")
    try:
        results = await geocode.search_city(q.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"地理编码服务暂时不可用: {exc}") from exc
    return results


@app.post("/api/chart")
def api_chart(req: ChartRequest):
    try:
        birth_date = date.fromisoformat(req.birth_date)
        hh, mm = (int(x) for x in req.birth_time.split(":")[:2])
    except ValueError as exc:
        raise HTTPException(400, "出生日期或时间格式不正确") from exc

    try:
        tzinfo = ZoneInfo(req.timezone)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"无效的时区: {req.timezone}") from exc

    local_dt = datetime(
        birth_date.year, birth_date.month, birth_date.day, hh, mm, tzinfo=tzinfo
    )
    birth_dt_utc = local_dt.astimezone(dt_timezone.utc)

    chart = astrology.compute_chart(birth_dt_utc, req.lat, req.lon)

    now_utc = datetime.now(dt_timezone.utc)
    dasha_info = dasha.current_dasha_summary(birth_dt_utc, chart.moon_longitude, now_utc)

    age = _calc_age(birth_date, date.today())
    is_minor = age < 18

    chart_summary = astrology.chart_summary_zh(chart)
    dasha_summary = dasha.dasha_summary_zh(birth_dt_utc, chart.moon_longitude, now_utc)

    try:
        reading = interpretation.generate_interpretation(
            chart_summary, dasha_summary, is_minor, req.name
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"生成解读失败: {exc}") from exc

    order = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
    planets_out = [_point_to_dict(chart.planets[n]) for n in order]

    maha = dasha_info["mahadasha"]
    antar = dasha_info["antardasha"]
    upcoming = [
        {"lord": p.lord, "lord_zh": p.lord_zh, "start": p.start.date().isoformat()}
        for p in dasha_info["mahadashas"]
        if p.start >= maha.start
    ][:4]

    return {
        "name": req.name,
        "is_minor": is_minor,
        "age": round(age, 1),
        "ascendant": _point_to_dict(chart.ascendant),
        "planets": planets_out,
        "dasha": {
            "mahadasha": {
                "lord": maha.lord,
                "lord_zh": maha.lord_zh,
                "start": maha.start.date().isoformat(),
                "end": maha.end.date().isoformat(),
            },
            "antardasha": {
                "lord": antar.lord,
                "lord_zh": antar.lord_zh,
                "start": antar.start.date().isoformat(),
                "end": antar.end.date().isoformat(),
            },
            "upcoming_mahadashas": upcoming,
        },
        "interpretation": reading,
    }


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
