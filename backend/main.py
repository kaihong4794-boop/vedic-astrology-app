"""FastAPI backend for the Vedic astrology reading web app."""
from __future__ import annotations

import html
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("vedic_astrology")

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator

import astrology
import dasha
import db
import geocode
import interpretation
import toyyibpay

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
    name: str = Field(..., min_length=1, max_length=50)
    birth_date: str  # "YYYY-MM-DD"
    birth_time: str  # "HH:MM"
    birth_place: str | None = Field(default=None, max_length=200)
    lat: float
    lon: float
    timezone: str  # IANA tz name, e.g. "Asia/Shanghai"

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("姓名不能为空")
        return v


class PayCreateRequest(BaseModel):
    reading_token: str
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)


# Price to unlock the full interpretation, in Ringgit. Kept as an env var
# (not hardcoded) since this is a number we expect to tune after seeing how
# ToyyibPay's flat per-transaction fee eats into a low price point.
_UNLOCK_PRICE_RM = float(os.environ.get("UNLOCK_PRICE_RM", "3.00"))


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


def _reading_response(
    *,
    token: str,
    paid: bool,
    chart_payload: dict,
    tagline: str | None,
    fields: dict,
) -> dict:
    """Shared shape for both POST /api/chart and GET /api/reading/{token}.

    `fields` holds the 10 `{topic}_insight` / `{topic}_advice` values —
    either straight from a freshly generated `reading` dict, or pulled off
    a stored DB row. The chart-based "insight" (what the chart shows and
    why) is always free and shown in full for every topic — that's the
    point of splitting insight from advice, so the free preview no longer
    needs an arbitrary character-count teaser. Only "advice" (the concrete
    actionable suggestions) is gated behind `paid`.
    """
    resp = {
        **chart_payload,
        "reading_token": token,
        "paid": paid,
        "price_rm": _UNLOCK_PRICE_RM,
        "interpretation_preview": {
            "tagline": tagline,
            **{f"{t}_insight": fields.get(f"{t}_insight") for t in interpretation.TOPICS},
        },
    }
    if paid:
        resp["interpretation_advice"] = {
            f"{t}_advice": fields.get(f"{t}_advice") for t in interpretation.TOPICS
        }
    return resp


@app.get("/api/health")
def health():
    return {"status": "ok"}


# /api/chart makes a real, billed Claude API call every time it's hit, with
# no login and no per-user identity — without a limit here, a script or bot
# could hammer this endpoint and run up the API bill with nothing to stop it.
# This is a simple in-memory per-IP limiter: it resets on process restart and
# each Render instance would track its own counts, but on the current
# single-instance deployment that's enough to block casual abuse. If this
# ever needs to survive restarts or multiple instances, move the counters to
# the database/Redis instead of this in-process dict.
_CHART_RATE_LIMIT_MAX = int(os.environ.get("CHART_RATE_LIMIT_PER_HOUR", "20"))
_CHART_RATE_LIMIT_WINDOW_SECONDS = 3600
_chart_request_log: dict[str, list[float]] = defaultdict(list)
_chart_rate_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    # Render sits behind a proxy, so the real client IP arrives via
    # X-Forwarded-For (first entry in the chain) rather than
    # request.client.host, which would otherwise just be the proxy's IP.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_chart_rate_limit(ip: str) -> None:
    now = time.time()
    cutoff = now - _CHART_RATE_LIMIT_WINDOW_SECONDS
    with _chart_rate_lock:
        recent = [t for t in _chart_request_log.get(ip, []) if t > cutoff]
        if len(recent) >= _CHART_RATE_LIMIT_MAX:
            _chart_request_log[ip] = recent
            raise HTTPException(429, "请求太频繁，请稍后再试（每小时生成次数已达上限）")
        recent.append(now)
        _chart_request_log[ip] = recent
        # Opportunistic cleanup so this dict doesn't grow forever if the
        # process stays up a long time and sees many distinct IPs.
        if len(_chart_request_log) > 5000:
            stale = [k for k, v in _chart_request_log.items() if not v or v[-1] <= cutoff]
            for k in stale:
                del _chart_request_log[k]


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
def api_chart(req: ChartRequest, request: Request):
    _check_chart_rate_limit(_client_ip(request))

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
        logger.exception("interpretation generation failed")
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

    # Everything that stays free regardless of payment status — the raw
    # computed chart, not the AI interpretation. Snapshotted to chart_json
    # so GET /api/reading/{token} can re-serve this exact payload later
    # (e.g. after the browser comes back from the payment page) without
    # recomputing anything.
    chart_payload = {
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
    }

    db_payload = {
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
        "chart_json": json.dumps(chart_payload),
        "tagline": reading.get("tagline"),
    }
    for t in interpretation.TOPICS:
        db_payload[f"{t}_insight"] = reading.get(f"{t}_insight")
        db_payload[f"{t}_advice"] = reading.get(f"{t}_advice")

    token = db.record_reading(db_payload)
    if token is None:
        # Without a saved row there's no token to unlock later, so this
        # can't be papered over the way a lost history row could be.
        raise HTTPException(502, "系统暂时繁忙，请稍后重试")

    return _reading_response(
        token=token,
        paid=False,
        chart_payload=chart_payload,
        tagline=reading.get("tagline"),
        fields=reading,
    )


@app.get("/api/reading/{token}")
def api_reading_get(token: str):
    row = db.get_reading(token)
    if row is None:
        raise HTTPException(404, "找不到这份解读，链接可能已失效")
    chart_payload = json.loads(row.chart_json) if row.chart_json else {}
    fields = {}
    for t in interpretation.TOPICS:
        fields[f"{t}_insight"] = getattr(row, f"{t}_insight", None)
        fields[f"{t}_advice"] = getattr(row, f"{t}_advice", None)
    return _reading_response(
        token=row.token,
        paid=row.paid,
        chart_payload=chart_payload,
        tagline=row.tagline,
        fields=fields,
    )


@app.post("/api/pay/create")
async def api_pay_create(req: PayCreateRequest, request: Request):
    row = db.get_reading(req.reading_token)
    if row is None:
        raise HTTPException(404, "找不到这份解读，请重新生成")
    if row.paid:
        return {"already_paid": True}
    if not toyyibpay.is_configured():
        raise HTTPException(503, "支付功能尚未开通，请联系网站管理员")

    amount_cents = int(round(_UNLOCK_PRICE_RM * 100))
    base = str(request.base_url).rstrip("/")
    return_url = f"{base}/?reading={req.reading_token}"
    callback_url = f"{base}/api/pay/callback"

    try:
        bill_code = await toyyibpay.create_bill(
            amount_cents=amount_cents,
            reading_token=req.reading_token,
            return_url=return_url,
            callback_url=callback_url,
            payer_name=req.name or row.name or "客人",
            payer_email=req.email or "",
        )
    except toyyibpay.ToyyibPayError as exc:
        logger.exception("failed to create ToyyibPay bill")
        raise HTTPException(502, f"创建支付订单失败: {exc}") from exc

    return {"payment_url": toyyibpay.payment_url(bill_code)}


@app.post("/api/pay/callback")
async def api_pay_callback(request: Request):
    # ToyyibPay POSTs here server-to-server once a payment completes. We
    # never trust the POST body's claimed status by itself — anyone can hit
    # a public URL and claim "status=1" — so we always re-check directly
    # with ToyyibPay using the billcode before marking anything paid.
    form = await request.form()
    bill_code = form.get("billcode") or form.get("billCode")
    reading_token = form.get("order_id")
    if not bill_code or not reading_token:
        logger.warning("ToyyibPay callback missing billcode/order_id: %s", dict(form))
        return PlainTextResponse("OK")

    try:
        paid = await toyyibpay.bill_is_paid(str(bill_code))
    except toyyibpay.ToyyibPayError:
        logger.exception("failed to verify ToyyibPay bill %s", bill_code)
        return PlainTextResponse("OK")

    if paid:
        db.mark_paid(str(reading_token), str(bill_code))
    return PlainTextResponse("OK")


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
        paid_badge = (
            '<span style="color:#7cc47f">已付款</span>' if r.paid else '<span style="color:#8f81b3">未付款</span>'
        )
        topic_html = ""
        for topic, label in interpretation.TOPIC_LABELS_ZH.items():
            insight = getattr(r, f"{topic}_insight", "") or ""
            advice = getattr(r, f"{topic}_advice", "") or ""
            topic_html += (
                f"<p><b>{html.escape(label)} · 分析</b><br>{html.escape(insight)}</p>"
                f"<p><b>{html.escape(label)} · 建议</b><br>{html.escape(advice)}</p>"
            )
        row_html.append(f"""
        <tr>
          <td>{html.escape(created)}</td>
          <td>{html.escape(r.name or "-")}</td>
          <td>{html.escape(r.birth_date or "")} {html.escape(r.birth_time or "")}</td>
          <td>{html.escape(r.birth_place or "-")}</td>
          <td>{html.escape(r.ascendant_sign or "")} {html.escape(r.ascendant_degree or "")}</td>
          <td>{minor_badge}</td>
          <td>{paid_badge}</td>
          <td>{html.escape(r.tagline or "")}</td>
          <td>
            <details>
              <summary>查看</summary>
              {topic_html}
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
            <th>上升</th><th></th><th>付款</th><th>金句</th><th>解读</th>
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

    @app.get("/privacy")
    def privacy():
        return FileResponse(
            str(FRONTEND_DIR / "privacy.html"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
