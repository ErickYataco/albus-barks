from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = BASE_DIR / "resources"
STATUS_IMAGE_DIR = RESOURCES_DIR / "images" / "status"
RUNTIME_DIR = BASE_DIR / "runtime"

DISPLAY_WIDTH = 250
DISPLAY_HEIGHT = 122
EPD_TYPE = "epd2in13"

API_URL = "http://127.0.0.1:5582/api/dashboard-state"
REFRESH_SECONDS = 60
ALERT_REFRESH_SECONDS = 15
