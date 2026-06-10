from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[Optional[int]] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(140), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    due_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)

    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
