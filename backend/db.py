"""Persistence for generated readings, for the /admin review list.

Uses Postgres in production (DATABASE_URL set by Render) and falls back to
a local SQLite file for local development, so recording works everywhere
without extra setup.
"""
from __future__ import annotations

import os
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
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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

    tagline = Column(Text)
    personality = Column(Text)
    wealth = Column(Text)
    relationship = Column(Text)
    current_period = Column(Text)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def record_reading(payload: dict) -> None:
    """Best-effort insert — recording history must never break a request."""
    try:
        with _SessionLocal() as session:
            session.add(Reading(**payload))
            session.commit()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("vedic_astrology.db").exception("failed to record reading")


def list_readings(limit: int = 200) -> list[Reading]:
    with _SessionLocal() as session:
        stmt = select(Reading).order_by(Reading.created_at.desc()).limit(limit)
        return list(session.scalars(stmt))
