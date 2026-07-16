import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from background.config import load_alert_config
from web import crud


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DEFAULT_CREDENTIALS = CONFIG_DIR / "google_credentials.json"
DEFAULT_TOKEN = CONFIG_DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def sync_once(session: Session) -> dict:
    started_at = datetime.now()
    try:
        count = sync_google_calendar(session)
        crud.record_alert_run(
            session,
            source="google_calendar",
            status="ok",
            message=None,
            items_seen=count,
            alerts_created=count,
            started_at=started_at,
            finished_at=datetime.now(),
        )
        return {"synced": True, "count": count, "error": None}
    except Exception as exc:
        crud.record_alert_run(
            session,
            source="google_calendar",
            status="error",
            message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(),
        )
        return {"synced": False, "count": 0, "error": str(exc)}


def sync_google_calendar(session: Session) -> int:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Google Calendar packages are not installed") from exc

    credentials_path = DEFAULT_CREDENTIALS
    token_path = DEFAULT_TOKEN
    config = load_alert_config().get("calendar", {})
    calendar_id = os.getenv("ALBUS_GOOGLE_CALENDAR_ID", config.get("calendar_id", "primary"))

    if not credentials_path.exists():
        raise RuntimeError(f"Missing Google credentials file: {credentials_path}")

    if not token_path.exists():
        raise RuntimeError(f"Missing Google token file: {token_path}")

    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json())

    if not credentials.valid:
        raise RuntimeError(f"Invalid Google token file: {token_path}")

    service = build("calendar", "v3", credentials=credentials)
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=2)

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=horizon.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    count = 0
    for event in events_result.get("items", []):
        start = event.get("start", {})
        raw_start = start.get("dateTime") or start.get("date")
        if not raw_start or "dateTime" not in start:
            continue

        starts_at = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        crud.upsert_calendar_alert(
            session=session,
            external_id=event["id"],
            title=event.get("summary") or "Calendar meeting",
            description=event.get("description"),
            starts_at=starts_at,
            synced_at=datetime.now(),
        )
        count += 1

    return count


def main() -> None:
    from web.database import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Sync Google Calendar meetings into Albus alerts")
    parser.add_argument("--watch", action="store_true", help="Keep syncing instead of running once")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between syncs in watch mode")
    args = parser.parse_args()

    init_db()
    while True:
        with SessionLocal() as session:
            print(sync_once(session), flush=True)

        if not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
