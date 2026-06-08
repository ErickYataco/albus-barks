import argparse
import signal
import time

from .animator import Animator
from .client import fallback_state, fetch_dashboard_state
from .config import ALERT_REFRESH_SECONDS, API_URL, REFRESH_SECONDS
from .display import render_dashboard
from .epd_driver import get_display

_running = True


def _stop(_signum, _frame) -> None:
    global _running
    _running = False


def run(api_url: str, once: bool = False, simulate: bool = False) -> None:
    global _running
    _running = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    animator = Animator()
    epd = get_display(simulate=simulate)
    epd.init()

    try:
        while _running:
            try:
                state = fetch_dashboard_state(api_url)
            except Exception as exc:
                state = fallback_state(f"API offline: {api_url}")

            dog_state = state.get("dog_state", "IDLE")
            frame = animator.next_frame(dog_state)
            image = render_dashboard(state, frame)
            epd.display(image)

            if once:
                break

            sleep_for = ALERT_REFRESH_SECONDS if dog_state in {"BARK", "HAPPY", "SAD"} else REFRESH_SECONDS
            time.sleep(sleep_for)
    finally:
        epd.sleep()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Albus Barks e-ink dashboard")
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--once", action="store_true", help="Render one frame and exit")
    parser.add_argument("--simulate", action="store_true", help="Force simulator instead of Waveshare display")
    args = parser.parse_args()
    run(api_url=args.api_url, once=args.once, simulate=args.simulate)
