import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Alert, AlertRun

MEETING_REMINDER_THRESHOLD = timedelta(minutes=15)
MEETING_REMINDER_REPEAT = timedelta(minutes=5)
ACTIVE_STATUSES = ("active", "notified")


def safe_title(title: str, max_chars: int = 24) -> str:
    title = str(title or "Alert").strip()
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 1] + "..."


def alert_status(alert: Alert, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()

    if alert.status != "active":
        return alert.status

    if alert.alert_type == "meeting" and alert.starts_at and alert.starts_at <= now:
        return "expired"

    if alert.starts_at and alert.starts_at <= now + timedelta(minutes=30):
        return "due-soon"

    return "active"


def is_recent_alert(alert: Alert, minutes: int, now: Optional[datetime] = None) -> bool:
    if minutes <= 0:
        return False

    now = now or datetime.now()
    discovered_at = alert.synced_at or alert.created_at
    return bool(discovered_at and discovered_at >= now - timedelta(minutes=minutes))


def dog_state_for_alerts(alerts: list[Alert]) -> tuple[str, str]:
    active_alerts = [alert for alert in alerts if alert.status in ACTIVE_STATUSES]

    if not active_alerts:
        return "SLEEPY", "No active alerts"

    urgent_meeting = next((alert for alert in active_alerts if alert.alert_type == "meeting"), None)
    if urgent_meeting:
        return "BARK", "Meeting coming up"

    job_alert = next((alert for alert in active_alerts if alert.alert_type == "job"), None)
    if job_alert:
        return "HAPPY", "Job match found"

    return "HAPPY", "New alert found"


def upsert_alert(
    session: Session,
    *,
    alert_type: str,
    source: str,
    external_id: str,
    title: str,
    description: Optional[str] = None,
    url: Optional[str] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    severity: str = "info",
    score: int = 0,
    payload: Optional[dict] = None,
    synced_at: Optional[datetime] = None,
) -> Alert:
    now = datetime.now()
    statement = (
        select(Alert)
        .where(Alert.source == source)
        .where(Alert.external_id == external_id)
        .limit(1)
    )
    alert = session.execute(statement).scalars().first()

    payload_json = json.dumps(payload or {}, sort_keys=True) if payload is not None else None

    if alert is None:
        alert = Alert(
            alert_type=alert_type,
            source=source,
            external_id=external_id,
            title=title,
            description=description or None,
            url=url or None,
            starts_at=starts_at,
            ends_at=ends_at,
            status="active",
            severity=severity,
            score=score,
            payload_json=payload_json,
            synced_at=synced_at or now,
            created_at=now,
            updated_at=now,
        )
    else:
        alert.alert_type = alert_type
        alert.title = title
        alert.description = description or None
        alert.url = url or None
        alert.starts_at = starts_at
        alert.ends_at = ends_at
        alert.severity = severity
        alert.score = score
        alert.payload_json = payload_json
        alert.synced_at = synced_at or now
        alert.updated_at = now
        if alert.status == "expired" and (not starts_at or starts_at > now):
            alert.status = "active"

    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def upsert_calendar_alert(
    session: Session,
    external_id: str,
    title: str,
    starts_at: datetime,
    description: Optional[str] = None,
    synced_at: Optional[datetime] = None,
) -> Alert:
    return upsert_alert(
        session=session,
        alert_type="meeting",
        source="google_calendar",
        external_id=external_id,
        title=title,
        description=description,
        starts_at=starts_at,
        severity="high",
        score=100,
        synced_at=synced_at,
    )


def acknowledge_alert(session: Session, alert_id: int) -> Optional[Alert]:
    alert = session.get(Alert, alert_id)
    if not alert:
        return None

    alert.status = "acknowledged"
    alert.updated_at = datetime.now()
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def expire_started_meeting_alerts(session: Session, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    statement = (
        select(Alert)
        .where(Alert.alert_type == "meeting")
        .where(Alert.status.in_(ACTIVE_STATUSES))
        .where(Alert.starts_at <= now)
    )
    alerts = list(session.execute(statement).scalars().all())

    for alert in alerts:
        alert.status = "expired"
        alert.updated_at = now
        session.add(alert)

    if alerts:
        session.commit()

    return len(alerts)


def meeting_alert_for_reminder(session: Session, now: Optional[datetime] = None) -> Optional[Alert]:
    now = now or datetime.now()
    threshold = now + MEETING_REMINDER_THRESHOLD
    statement = (
        select(Alert)
        .where(Alert.alert_type == "meeting")
        .where(Alert.status.in_(ACTIVE_STATUSES))
        .where(Alert.starts_at > now)
        .where(Alert.starts_at <= threshold)
        .order_by(Alert.starts_at.asc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def reminder_overlay_for_meeting(alert: Optional[Alert], now: Optional[datetime] = None) -> Optional[dict]:
    if not alert or not alert.starts_at:
        return None

    now = now or datetime.now()
    should_remind = alert.last_reminder_at is None or alert.last_reminder_at <= now - MEETING_REMINDER_REPEAT
    if not should_remind:
        return None

    if alert.reminder_started_at is None:
        alert.reminder_started_at = now
    alert.last_reminder_at = now
    alert.reminder_count = (alert.reminder_count or 0) + 1
    alert.status = "notified"
    alert.updated_at = now

    minutes = max(1, int((alert.starts_at - now).total_seconds() // 60) + 1)
    return {
        "state": "MEETING",
        "mode": "meeting_reminder",
        "repeat": 1,
        "alert_id": alert.id,
        "title": safe_title(alert.title, 34),
        "minutes": minutes,
        "message": f"Don't be late. {safe_title(alert.title, 16)} in {minutes} min",
    }


def job_alert_for_reminder(
    session: Session,
    repeat_minutes: int = 5,
    now: Optional[datetime] = None,
) -> Optional[Alert]:
    now = now or datetime.now()
    repeat_after = now - timedelta(minutes=max(1, repeat_minutes))
    statement = (
        select(Alert)
        .where(Alert.alert_type == "job")
        .where(Alert.status.in_(ACTIVE_STATUSES))
        .where((Alert.last_reminder_at.is_(None)) | (Alert.last_reminder_at <= repeat_after))
        .order_by(Alert.score.desc(), Alert.synced_at.desc().nullslast(), Alert.created_at.desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def reminder_overlay_for_job(alert: Optional[Alert], now: Optional[datetime] = None) -> Optional[dict]:
    if not alert:
        return None

    now = now or datetime.now()
    if alert.reminder_started_at is None:
        alert.reminder_started_at = now
    alert.last_reminder_at = now
    alert.reminder_count = (alert.reminder_count or 0) + 1
    alert.status = "notified"
    alert.updated_at = now

    return {
        "state": "BARK",
        "mode": "job_reminder",
        "repeat": 1,
        "alert_id": alert.id,
        "title": safe_title(alert.title, 34),
        "score": alert.score,
        "description": safe_title(alert.description or "", 28),
        "message": f"High match. {safe_title(alert.title, 18)}",
    }


def alert_statement_for_filter(filter_value: str = "active"):
    statement = select(Alert)

    if filter_value == "all":
        pass
    elif filter_value == "history":
        statement = statement.where(Alert.status.notin_(ACTIVE_STATUSES))
    else:
        statement = statement.where(Alert.status.in_(ACTIVE_STATUSES))

    return statement


def list_alerts(session: Session, filter_value: str = "active", limit: Optional[int] = None, offset: int = 0) -> list[Alert]:
    statement = alert_statement_for_filter(filter_value)
    statement = statement.order_by(Alert.status.asc(), Alert.starts_at.asc().nullslast(), Alert.score.desc())
    if limit is not None:
        statement = statement.limit(limit).offset(offset)
    return list(session.execute(statement).scalars().all())


def count_alerts_for_filter(session: Session, filter_value: str = "active") -> int:
    filtered = alert_statement_for_filter(filter_value).subquery()
    statement = select(func.count()).select_from(filtered)
    return int(session.execute(statement).scalar_one())


def dashboard_alerts(session: Session, limit: int = 3) -> list[Alert]:
    statement = (
        select(Alert)
        .where(Alert.status.in_(ACTIVE_STATUSES))
        .order_by(Alert.score.desc(), Alert.starts_at.asc().nullslast(), Alert.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(statement).scalars().all())


def count_alerts(session: Session) -> dict:
    alerts = list(session.execute(select(Alert)).scalars().all())
    active = [alert for alert in alerts if alert.status in ACTIVE_STATUSES]
    high = [alert for alert in active if alert.severity in {"high", "urgent"}]

    return {
        "all": len(alerts),
        "active": len(active),
        "high": len(high),
        "history": len(alerts) - len(active),
    }


def alert_to_api(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "alert_type": alert.alert_type,
        "source": alert.source,
        "external_id": alert.external_id,
        "title": alert.title,
        "description": alert.description,
        "url": alert.url,
        "starts_at": alert.starts_at.isoformat() if alert.starts_at else None,
        "ends_at": alert.ends_at.isoformat() if alert.ends_at else None,
        "status": alert_status(alert),
        "severity": alert.severity,
        "score": alert.score,
        "synced_at": alert.synced_at.isoformat() if alert.synced_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }


def record_alert_run(
    session: Session,
    *,
    source: str,
    status: str,
    message: Optional[str] = None,
    items_seen: int = 0,
    alerts_created: int = 0,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> AlertRun:
    now = datetime.now()
    run = AlertRun(
        source=source,
        status=status,
        message=message,
        items_seen=items_seen,
        alerts_created=alerts_created,
        started_at=started_at or now,
        finished_at=finished_at or now,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def latest_runs(session: Session, limit: int = 10, offset: int = 0) -> list[AlertRun]:
    statement = select(AlertRun).order_by(AlertRun.finished_at.desc()).limit(limit).offset(offset)
    return list(session.execute(statement).scalars().all())


def count_runs(session: Session, max_items: int = 50) -> int:
    statement = select(func.count()).select_from(AlertRun)
    total = int(session.execute(statement).scalar_one())
    return min(total, max_items)


def run_to_api(run: AlertRun) -> dict:
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "message": run.message,
        "items_seen": run.items_seen,
        "alerts_created": run.alerts_created,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
