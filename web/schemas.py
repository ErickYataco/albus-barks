from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TaskRead(BaseModel):
    id: int
    title: str
    description: Optional[str]
    due_time: datetime
    due_time_short: str
    done: bool
    completed_at: Optional[datetime]
    status: str


class DashboardState(BaseModel):
    dog_state: str
    message: str
    tasks: list[TaskRead]
