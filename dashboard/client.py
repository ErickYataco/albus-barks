import requests

from .config import API_URL


def fetch_dashboard_state(api_url: str = API_URL) -> dict:
    response = requests.get(api_url, timeout=5)
    response.raise_for_status()
    return response.json()


def fallback_state(message: str = "API offline") -> dict:
    return {
        "dog_state": "SAD",
        "message": message,
        "tasks": [],
    }
