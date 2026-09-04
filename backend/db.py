"""Persistence for generated readings.

Uses Postgres in production (DATABASE_URL set by Render) and falls back to
a local SQLite file for local development, so recording works everywhere
without extra setup.

Beyond the original "history log for /admin" role, this now also backs the
pay-to-unlock flow: each reading gets a random `token` the frontend uses to
fetch it back (after a redirect from the payment page), and a `paid` flag
that gates whether the full interpretation is returned or just the free
preview.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("vedic_astrology.db")

_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./local_readings.db")
# Render's Postgres URLs use the `postgres://` scheme, which SQLAlchemy 2.x
# no longer accepts — normalize to `postgresql://`.
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

_engine = create_engine(_DATABASE_URL, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine)
Base = declarative_base()


class Reading(Base):
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(dt_timezone.utc))

    # Opaque public identifier used by the frontend to fetch this reading
    # back (e.g. after returning from the payment page) — never expose the
    # autoincrement `id` for that, it's guessable/enumerable.
    token = Column(String(36), unique=True, index=True, nullable=True)
    paid = Column(Boolean, default=False, nullable=False)
    bill_code = Column(String(50), nullable=True)  # ToyyibPay BillCode, once created

    name = Column(String(50), nullable=True)
    birth_date = Column(String(20))
    birth_time = Column(String(10))
    birth_place = Column(String(200), nullable=True)
    timezone = Column(String(50))
    lat = Column(Float)
    lon = Column(Float)

    is_minor = Column(Boolean)
    age = Column(Float)
    ascendant_sign = Column(String(20))
    ascendant_degree = Column(String(20))

    # JSON-encoded snapshot of the free chart/dasha payload (ascendant,
    # planets, dasha timeline) — stored so GET /api/reading/{token} can
    # re-serve the exact same result after a payment redirect without
    # recomputing the chart or re-rendering anything differently.
    chart_json = Column(Text, nullable=True)

    tagline = Column(Text)
    personality_insight = Column(Text)
    personality_advice = Column(Text)
    career_insight = Column(Text)
    career_advice = Column(Text)
    wealth_insight = Column(Text)
    wealth_advice = Column(Text)
    relationship_insight = Column(Text)
    relationship_advice = Column(Text)
    current_period_insight = Column(Text)
    current_period_advice = Column(Text)


class InterpretationCache(Base):
    """Caches the AI-generated tagline/insight/advice text keyed by the exact
    chart-defining inputs (birth date/time/location/timezone/minor status/
    name).

    The chart math itself (astrology.compute_chart) is already deterministic
    — the same birth data always yields the same ascendant/planets. But the
    interpretation text is written fresh by Claude on every /api/chart call,
    and an LLM does not return identical wording for identical input. Without
    this cache, submitting the exact same birth data twice (a user testing
    the app, or genuinely coming back) produces two differently-worded
    readings, which reads as inconsistent/unreliable even though the
    underlying astrology is correct both times. Caching also skips a
    redundant paid Claude API call for a repeat submission.
    """

    __tablename__ = "interpretation_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(160), unique=True, index=True, nullable=False)
    reading_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(dt_timezone.utc))


def get_cached_interpretation(cache_key: str) -> dict | None:
    with _SessionLocal() as session:
        stmt = select(InterpretationCache).where(InterpretationCache.cache_key == cache_key)
        row = session.scalars(stmt).first()
        if row is None:
            return None
        try:
            return json.loads(row.reading_json)
        except ValueError:
            logger.exception("corrupt cached interpretation for key %s", cache_key)
            return None


def save_cached_interpretation(cache_key: str, reading: dict) -> None:
    try:
        with _SessionLocal() as session:
            # Another concurrent request may have cached the same key first
            # (e.g. two near-simultaneous submissions of the same birth
            # data) — don't overwrite, first write wins, table has a unique
            # index on cache_key anyway so this also avoids an IntegrityError.
            existing = session.scalars(
                select(InterpretationCache).where(InterpretationCache.cache_key == cache_key)
            ).first()
            if existing is not None:
                return
            session.add(InterpretationCache(cache_key=cache_key, reading_json=json.dumps(reading)))
            session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to save cached interpretation for key %s", cache_key)


def _ensure_columns() -> None:
    """Lightweight, idempotent 'migration'.

    Base.metadata.create_all() only creates TABLES that don't exist yet —
    it never adds a column to a table that's already there. The production
    Postgres table predates `token`/`paid`/`bill_code`/`chart_json`, so
    without this, every insert against the old live table would blow up
    (or worse, silently drop the new columns) the moment this code deploys.
    """
    inspector = inspect(_engine)
    if "readings" not in inspector.get_table_names():
        return  # brand-new DB — create_all() already created the full shape
    existing = {c["name"] for c in inspector.get_columns("readings")}
    additions = {
        "token": "VARCHAR(36)",
        "paid": "BOOLEAN DEFAULT FALSE",
        "bill_code": "VARCHAR(50)",
        "chart_json": "TEXT",
        # Legacy single-field columns from before the insight/advice split —
        # kept here (rather than removed) so a still-running old process
        # writing to these names during a rolling deploy wouldn't 500; safe
        # to drop from a future migration once that's no longer a concern.
        "career": "TEXT",
        "personality_insight": "TEXT",
        "personality_advice": "TEXT",
        "career_insight": "TEXT",
        "career_advice": "TEXT",
        "wealth_insight": "TEXT",
        "wealth_advice": "TEXT",
        "relationship_insight": "TEXT",
        "relationship_advice": "TEXT",
        "current_period_insight": "TEXT",
        "current_period_advice": "TEXT",
    }
    with _engine.begin() as conn:
        for col, ddl_type in additions.items():
            if col in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE readings ADD COLUMN {col} {ddl_type}"))
                logger.info("added missing column readings.%s", col)
            except Exception:  # noqa: BLE001
                logger.exception("failed to add column readings.%s", col)


def init_db() -> None:
    Base.metadata.create_all(_engine)
    _ensure_columns()


def record_reading(payload: dict) -> str | None:
    """Insert a new reading row and return its public token.

    Unlike the old history-only version of this function, a failure here is
    no longer just a lost analytics row — without a persisted row there is
    no token to unlock later, so the caller must treat `None` as a real
    failure (see api_chart in main.py), not silently carry on.
    """
    token = str(uuid.uuid4())
    try:
        with _SessionLocal() as session:
            session.add(Reading(token=token, paid=False, **payload))
            session.commit()
        return token
    except Exception:  # noqa: BLE001
        logger.exception("failed to record reading")
        return None


def get_reading(token: str) -> Reading | None:
    with _SessionLocal() as session:
        stmt = select(Reading).where(Reading.token == token)
        return session.scalars(stmt).first()


def mark_paid(token: str, bill_code: str) -> bool:
    """Mark a reading as paid. Returns False if the token doesn't exist."""
    with _SessionLocal() as session:
        stmt = select(Reading).where(Reading.token == token)
        row = session.scalars(stmt).first()
        if row is None:
            return False
        row.paid = True
        row.bill_code = bill_code
        session.commit()
        return True


def list_readings(limit: int = 200) -> list[Reading]:
    with _SessionLocal() as session:
        stmt = select(Reading).order_by(Reading.created_at.desc()).limit(limit)
        return list(session.scalars(stmt))
