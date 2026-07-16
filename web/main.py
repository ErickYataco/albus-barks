from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from background.config import load_alert_config
from . import crud
from .database import get_session, init_db

BASE_DIR = Path(__file__).resolve().parent
PAGE_SIZE = 10
MAX_SOURCE_RUNS = 50

app = FastAPI(title="Albus Barks", version="0.2.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def parse_form_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def pretty_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%b %d, %Y %I:%M %p")


templates.env.filters["pretty_datetime"] = pretty_datetime


def notification_config() -> dict:
    return load_alert_config().get("notifications", {})


def alert_repeat_minutes() -> int:
    config = notification_config()
    return int(config.get("job_reminder_repeat_minutes", 5))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    view: str = "alerts",
    filter: str = "active",
    page: int = 1,
    session: Session = Depends(get_session),
):
    view = view if view in {"alerts", "sources"} else "alerts"
    page = max(1, page)

    alert_total = crud.count_alerts_for_filter(session, filter)
    run_total = crud.count_runs(session, max_items=MAX_SOURCE_RUNS)
    total_items = alert_total if view == "alerts" else run_total
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    alerts = crud.list_alerts(session, filter, limit=PAGE_SIZE, offset=offset) if view == "alerts" else []
    runs = crud.latest_runs(session, limit=PAGE_SIZE, offset=offset) if view == "sources" and offset < MAX_SOURCE_RUNS else []
    active_alerts = crud.dashboard_alerts(session, limit=20)
    counts = crud.count_alerts(session)
    dog_state, message = crud.dog_state_for_alerts(active_alerts)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "alerts": [{"alert": alert, "status": crud.alert_status(alert)} for alert in alerts],
            "runs": runs,
            "counts": counts,
            "view": view,
            "filter_value": filter,
            "page": page,
            "page_size": PAGE_SIZE,
            "total_items": total_items,
            "total_pages": total_pages,
            "dog_state": dog_state,
            "message": message,
        },
    )


@app.get("/api/alerts")
def api_alerts(filter: str = "active", session: Session = Depends(get_session)):
    return [crud.alert_to_api(alert) for alert in crud.list_alerts(session, filter)]


@app.post("/api/alerts/{alert_id}/acknowledge")
def api_acknowledge_alert(alert_id: int, session: Session = Depends(get_session)):
    alert = crud.acknowledge_alert(session, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return crud.alert_to_api(alert)


@app.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, request: Request, session: Session = Depends(get_session)):
    alert = crud.acknowledge_alert(session, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    referer = request.headers.get("referer") or "/"
    return RedirectResponse(referer, status_code=303)


@app.post("/api/test-alert")
def api_test_alert(
    title: str = Form("Calendar test meeting"),
    starts_at: str = Form(...),
    session: Session = Depends(get_session),
):
    parsed_starts_at = parse_form_datetime(starts_at)
    if not parsed_starts_at:
        raise HTTPException(status_code=400, detail="Invalid starts_at. Use YYYY-MM-DDTHH:MM.")

    alert = crud.upsert_calendar_alert(
        session=session,
        external_id=f"local-test-{parsed_starts_at.isoformat()}-{title}",
        title=title,
        starts_at=parsed_starts_at,
        description="Local alert animation test",
    )
    return crud.alert_to_api(alert)


@app.get("/api/dashboard-state")
def api_dashboard_state(session: Session = Depends(get_session)):
    crud.expire_started_meeting_alerts(session)

    active_alerts = crud.dashboard_alerts(session, limit=3)
    dog_state, message = crud.dog_state_for_alerts(active_alerts)

    overlay_animations = []
    meeting_overlay = crud.reminder_overlay_for_meeting(crud.meeting_alert_for_reminder(session))
    if meeting_overlay:
        overlay_animations.append(meeting_overlay)

    job_overlay = crud.reminder_overlay_for_job(
        crud.job_alert_for_reminder(
            session,
            repeat_minutes=alert_repeat_minutes(),
        )
    )
    if job_overlay:
        overlay_animations.append(job_overlay)

    if overlay_animations:
        session.commit()

    return {
        "dog_state": dog_state,
        "message": message,
        "counts": crud.count_alerts(session),
        "overlay_animation": overlay_animations[0] if overlay_animations else None,
        "overlay_animations": overlay_animations,
        "alerts": [crud.alert_to_api(alert) for alert in active_alerts],
    }


@app.get("/api/source-runs")
def api_source_runs(session: Session = Depends(get_session)):
    return [crud.run_to_api(run) for run in crud.latest_runs(session, limit=50)]
