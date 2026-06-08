from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud
from .database import get_session, init_db
from .models import Task

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Albus Barks", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def parse_form_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def html_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def pretty_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%b %d, %Y %I:%M %p")


def redirect_to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


templates.env.filters["html_datetime"] = html_datetime
templates.env.filters["pretty_datetime"] = pretty_datetime


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, filter: str = "active", session: Session = Depends(get_session)):
    tasks = crud.list_tasks(session, filter)
    all_tasks = list(session.execute(select(Task)).scalars().all())
    counts = crud.count_tasks(session)
    dog_state, message = crud.dog_state_for_tasks(all_tasks)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tasks": [{"task": task, "status": crud.task_status(task)} for task in tasks],
            "counts": counts,
            "filter_value": filter,
            "dog_state": dog_state,
            "message": message,
        },
    )


@app.get("/tasks/new", response_class=HTMLResponse)
def new_task(request: Request):
    return templates.TemplateResponse(
        "task_form.html",
        {"request": request, "mode": "create", "task": None, "error": None},
    )


@app.post("/tasks/new")
def create_task(
    title: str = Form(...),
    description: str = Form(""),
    due_time: str = Form(...),
    session: Session = Depends(get_session),
):
    parsed_due_time = parse_form_datetime(due_time)
    if not title.strip() or not parsed_due_time:
        return redirect_to("/tasks/new?error=invalid")

    crud.create_task(
        session=session,
        title=title.strip(),
        description=description.strip() or None,
        due_time=parsed_due_time,
    )
    return redirect_to("/")


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, session: Session = Depends(get_session)):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return templates.TemplateResponse(
        "task_detail.html",
        {"request": request, "task": task, "status": crud.task_status(task)},
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form(task_id: int, request: Request, session: Session = Depends(get_session)):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return templates.TemplateResponse(
        "task_form.html",
        {"request": request, "mode": "edit", "task": task, "error": None},
    )


@app.post("/tasks/{task_id}/edit")
def edit_task(
    task_id: int,
    title: str = Form(...),
    description: str = Form(""),
    due_time: str = Form(...),
    session: Session = Depends(get_session),
):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    parsed_due_time = parse_form_datetime(due_time)
    if not title.strip() or not parsed_due_time:
        return redirect_to(f"/tasks/{task_id}/edit")

    crud.update_task(session, task, title.strip(), description.strip() or None, parsed_due_time)
    return redirect_to(f"/tasks/{task_id}")


@app.post("/tasks/{task_id}/toggle")
def toggle_task(task_id: int, session: Session = Depends(get_session)):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    crud.toggle_task(session, task)
    return redirect_to("/")


@app.post("/tasks/{task_id}/delete")
def delete_task(task_id: int, session: Session = Depends(get_session)):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    crud.delete_task(session, task)
    return redirect_to("/")


@app.get("/api/tasks")
def api_tasks(session: Session = Depends(get_session)):
    tasks = list(
        session.execute(
            select(Task).order_by(Task.done.asc(), Task.due_time.asc())
        ).scalars().all()
    )
    return [crud.task_to_api(task) for task in tasks]


@app.get("/api/dashboard-state")
def api_dashboard_state(session: Session = Depends(get_session)):
    all_tasks = list(session.execute(select(Task)).scalars().all())
    tasks = crud.dashboard_tasks(session, limit=3)

    dog_state, message = crud.dog_state_for_tasks(all_tasks)

    return {
        "dog_state": dog_state,
        "message": message,
        "counts": crud.count_tasks(session),
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "due_time": task.due_time.isoformat(),
                "done": task.done,
                "status": crud.task_status(task),
            }
            for task in tasks
        ],
    }


@app.post("/api/tasks/{task_id}/toggle")
def api_toggle_task(task_id: int, session: Session = Depends(get_session)):
    task = crud.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    updated = crud.toggle_task(session, task)
    return crud.task_to_api(updated)
