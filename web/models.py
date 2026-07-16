from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[Optional[int]] = mapped_column(Integer, primary_key=True, index=True)

    alert_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(140), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True, nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    severity: Mapped[str] = mapped_column(String(40), default="info", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)

    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AlertRun(Base):
    __tablename__ = "alert_runs"

    id: Mapped[Optional[int]] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
