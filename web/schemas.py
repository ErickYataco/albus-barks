from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AlertRead(BaseModel):
    id: int
    alert_type: str
    source: str
    external_id: str
    title: str
    description: Optional[str]
    url: Optional[str]
    starts_at: Optional[datetime]
    status: str
    severity: str
    score: int


class DashboardState(BaseModel):
    dog_state: str
    message: str
    alerts: list[AlertRead]
