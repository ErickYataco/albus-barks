from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Task

MEETING_REMINDER_THRESHOLD = timedelta(minutes=15)
MEETING_REMINDER_REPEAT = timedelta(seconds=10)


def task_status(task: Task, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()

    if task.done:
        return "done"

    if task.due_time < now:
        return "overdue"

    if task.due_time <= now + timedelta(minutes=30):
        return "due-soon"

    return "pending"


def dog_state_for_tasks(tasks: list[Task]) -> tuple[str, str]:
    now = datetime.now()

    if not tasks:
        return "SLEEPY", "No tasks yet"

    active_tasks = [task for task in tasks if not task.done]

    if not active_tasks:
        return "SLEEPY", "All tasks are done"

    statuses = [task_status(task, now) for task in active_tasks]

    if "overdue" in statuses:
        return "BARK", "You have overdue tasks"

    if "due-soon" in statuses:
        return "BARK", "A task is due soon"

    return "IDLE", "Albus is waiting"


def mark_started_calendar_tasks_done(session: Session, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    statement = (
        select(Task)
        .where(Task.source == "google_calendar")
        .where(Task.done.is_(False))
        .where(Task.due_time <= now)
    )
    tasks = list(session.execute(statement).scalars().all())

    for task in tasks:
        task.done = True
        task.completed_at = now
        task.updated_at = now
        session.add(task)

    if tasks:
        session.commit()

    return len(tasks)


def meeting_task_for_reminder(session: Session, now: Optional[datetime] = None) -> Optional[Task]:
    now = now or datetime.now()
    threshold = now + MEETING_REMINDER_THRESHOLD
    statement = (
        select(Task)
        .where(Task.source == "google_calendar")
        .where(Task.done.is_(False))
        .where(Task.due_time > now)
        .where(Task.due_time <= threshold)
        .order_by(Task.due_time.asc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def reminder_overlay_for_meeting(task: Optional[Task], now: Optional[datetime] = None) -> Optional[dict]:
    if not task:
        return None

    now = now or datetime.now()
    should_remind = task.last_reminder_at is None or task.last_reminder_at <= now - MEETING_REMINDER_REPEAT
    if not should_remind:
        return None

    if task.reminder_started_at is None:
        task.reminder_started_at = now
    task.last_reminder_at = now
    task.reminder_count = (task.reminder_count or 0) + 1
    task.updated_at = now

    minutes = max(1, int((task.due_time - now).total_seconds() // 60) + 1)
    return {
        "state": "MEETING",
        "mode": "meeting_reminder",
        "repeat": 1,
        "task_id": task.id,
        "title": safe_title(task.title, 34),
        "minutes": minutes,
        "message": f"Don't be late. {safe_title(task.title, 16)} in {minutes} min",
    }


def safe_title(title: str, max_chars: int = 24) -> str:
    title = str(title or "Meeting").strip()
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 1] + "…"


def get_task(session: Session, task_id: int) -> Optional[Task]:
    return session.get(Task, task_id)


def list_tasks(session: Session, filter_value: str = "active") -> list[Task]:
    statement = select(Task)

    if filter_value == "done":
        statement = statement.where(Task.done.is_(True))
    elif filter_value in ("active", "pending"):
        statement = statement.where(Task.done.is_(False))
    elif filter_value == "all":
        pass
    else:
        statement = statement.where(Task.done.is_(False))

    statement = statement.order_by(Task.done.asc(), Task.due_time.asc())

    return list(session.execute(statement).scalars().all())


def count_tasks(session: Session) -> dict:
    all_tasks = list(session.execute(select(Task)).scalars().all())
    now = datetime.now()

    pending = 0
    done = 0
    overdue = 0
    due_soon = 0

    for task in all_tasks:
        status = task_status(task, now)

        if status == "done":
            done += 1
        else:
            pending += 1

        if status == "overdue":
            overdue += 1

        if status == "due-soon":
            due_soon += 1

    return {
        "all": len(all_tasks),
        "pending": pending,
        "done": done,
        "overdue": overdue,
        "due_soon": due_soon,
    }


def create_task(
    session: Session,
    title: str,
    description: Optional[str],
    due_time: datetime,
) -> Task:
    task = Task(
        title=title,
        description=description or None,
        due_time=due_time,
        done=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    session.add(task)
    session.commit()
    session.refresh(task)

    return task


def upsert_calendar_task(
    session: Session,
    external_id: str,
    title: str,
    due_time: datetime,
    description: Optional[str] = None,
    synced_at: Optional[datetime] = None,
) -> Task:
    now = datetime.now()
    statement = (
        select(Task)
        .where(Task.source == "google_calendar")
        .where(Task.external_id == external_id)
        .limit(1)
    )
    task = session.execute(statement).scalars().first()

    if task is None:
        task = Task(
            title=title,
            description=description or None,
            due_time=due_time,
            done=False,
            source="google_calendar",
            external_id=external_id,
            synced_at=synced_at or now,
            created_at=now,
            updated_at=now,
        )
    else:
        task.title = title
        task.description = description or None
        task.due_time = due_time
        task.synced_at = synced_at or now
        task.updated_at = now
        if task.done and task.completed_at and task.due_time > now:
            task.done = False
            task.completed_at = None

    session.add(task)
    session.commit()
    session.refresh(task)

    return task


def update_task(
    session: Session,
    task: Task,
    title: str,
    description: Optional[str],
    due_time: datetime,
) -> Task:
    task.title = title
    task.description = description or None
    task.due_time = due_time
    task.updated_at = datetime.now()

    session.add(task)
    session.commit()
    session.refresh(task)

    return task


def toggle_task(session: Session, task: Task) -> Task:
    task.done = not task.done
    task.completed_at = datetime.now() if task.done else None
    task.updated_at = datetime.now()

    session.add(task)
    session.commit()
    session.refresh(task)

    return task


def delete_task(session: Session, task: Task) -> None:
    session.delete(task)
    session.commit()


def next_pending_task(session: Session) -> Optional[Task]:
    statement = (
        select(Task)
        .where(Task.done.is_(False))
        .order_by(Task.due_time.asc())
        .limit(1)
    )

    return session.execute(statement).scalars().first()


def dashboard_tasks(session: Session, limit: int = 3) -> list[Task]:
    statement = (
        select(Task)
        .where(Task.done.is_(False))
        .order_by(Task.due_time.asc())
        .limit(limit)
    )

    return list(session.execute(statement).scalars().all())

def task_to_api(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_time": task.due_time.isoformat() if task.due_time else None,
        "done": task.done,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "status": task_status(task),
        "source": getattr(task, "source", "manual"),
    }
