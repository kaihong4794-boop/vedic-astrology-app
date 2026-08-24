"""FastAPI backend for the Vedic astrology reading web app."""
from __future__ import annotations

import html
import logging
import os
import secrets
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("vedic_astrology")

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import astrology
import dasha
import db
import geocode
import interpretation

app = FastAPI(title="Vedic Astrology Reading")
db.init_db()

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
    birth_place: str | None = Field(default=None, max_length=200)
    lat: float
    lon: float
    timezone: str  # IANA tz name, e.g. "Asia/Shanghai"
    focus: str | None = Field(default=None, max_length=200)  # 用户填写的近期关注点（选填）


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

    focus = (req.focus or "").strip() or None

    try:
        reading = interpretation.generate_interpretation(
            chart_summary, dasha_summary, is_minor, req.name, focus
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("interpretation generation failed")
        raise HTTPException(502, f"生成解读失败: {exc}") from exc

    db.record_reading({
        "name": req.name,
        "birth_date": req.birth_date,
        "birth_time": req.birth_time,
        "birth_place": req.birth_place,
        "timezone": req.timezone,
        "lat": req.lat,
        "lon": req.lon,
        "is_minor": is_minor,
        "age": age,
        "ascendant_sign": chart.ascendant.sign_name,
        "ascendant_degree": astrology.format_degree(chart.ascendant.sign_degree),
        "tagline": reading.get("tagline"),
        "personality": reading.get("personality"),
        "wealth": reading.get("wealth"),
        "relationship": reading.get("relationship"),
        "current_period": reading.get("current_period"),
    })

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


_admin_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_admin_security)) -> None:
    expected_password = os.environ.get("ADMIN_PASSWORD")
    if not expected_password:
        raise HTTPException(503, "后台未配置 ADMIN_PASSWORD，已禁用")
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, expected_password)
    if not (correct_username and correct_password):
        raise HTTPException(
            401, "用户名或密码错误", headers={"WWW-Authenticate": "Basic"}
        )


@app.get("/admin", response_class=HTMLResponse)
def admin_list(_: None = Depends(_require_admin)):
    rows = db.list_readings()
    row_html = []
    for r in rows:
        created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        minor_badge = (
            '<span style="color:#cf8b78">未成年</span>' if r.is_minor else ""
        )
        row_html.append(f"""
        <tr>
          <td>{html.escape(created)}</td>
          <td>{html.escape(r.name or "-")}</td>
          <td>{html.escape(r.birth_date or "")} {html.escape(r.birth_time or "")}</td>
          <td>{html.escape(r.birth_place or "-")}</td>
          <td>{html.escape(r.ascendant_sign or "")} {html.escape(r.ascendant_degree or "")}</td>
          <td>{minor_badge}</td>
          <td>{html.escape(r.tagline or "")}</td>
          <td>
            <details>
              <summary>查看</summary>
              <p><b>性格</b><br>{html.escape(r.personality or "")}</p>
              <p><b>财富</b><br>{html.escape(r.wealth or "")}</p>
              <p><b>感情/人际</b><br>{html.escape(r.relationship or "")}</p>
              <p><b>近况</b><br>{html.escape(r.current_period or "")}</p>
            </details>
          </td>
        </tr>
        """)

    page = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="UTF-8">
      <title>后台记录</title>
      <style>
        body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background:#0f0c1a; color:#ece7f7; padding:20px; }}
        h1 {{ font-size:1.2rem; }}
        table {{ border-collapse: collapse; width:100%; font-size:0.85rem; }}
        th, td {{ border-bottom:1px solid #362c50; padding:8px; text-align:left; vertical-align:top; }}
        th {{ color:#9a8dbb; }}
        details summary {{ cursor:pointer; color:#d3ac6c; }}
        p {{ white-space: pre-wrap; max-width: 480px; }}
      </style>
    </head>
    <body>
      <h1>共 {len(rows)} 条记录</h1>
      <table>
        <thead>
          <tr>
            <th>时间</th><th>姓名</th><th>生日</th><th>出生地</th>
            <th>上升</th><th></th><th>金句</th><th>解读</th>
          </tr>
        </thead>
        <tbody>
          {"".join(row_html)}
        </tbody>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(page)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        # index.html itself must never be cached by the browser — it's what
        # references the versioned static assets (?v=N), so a stale cached
        # copy of THIS file keeps pointing at old markup/JS/CSS forever, no
        # matter how many times the ?v= query string is bumped.
        return FileResponse(
            str(FRONTEND_DIR / "index.html"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
