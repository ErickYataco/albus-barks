import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DEFAULT_CONFIG = CONFIG_DIR / "alerts.json"
EXAMPLE_CONFIG = CONFIG_DIR / "alerts.example.json"


def load_alert_config() -> dict[str, Any]:
    path = DEFAULT_CONFIG

    if not path.exists():
        path = EXAMPLE_CONFIG

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
