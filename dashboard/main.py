import argparse
import signal
import time

from .animator import Animator
from .client import fallback_state, fetch_dashboard_state
from .config import ALERT_REFRESH_SECONDS, API_URL, REFRESH_SECONDS
from .display import render_dashboard, render_fullscreen_animation, render_job_reminder, render_meeting_reminder
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
            overlay_animations = state.get("overlay_animations") or []
            if not overlay_animations and state.get("overlay_animation"):
                overlay_animations = [state.get("overlay_animation")]
            for overlay_animation in overlay_animations:
                play_overlay_animation(epd, animator, overlay_animation)

            frame = animator.next_frame(dog_state)
            image = render_dashboard(state, frame)
            epd.display(image)

            if once:
                break

            sleep_for = ALERT_REFRESH_SECONDS if dog_state in {"BARK", "HAPPY", "SAD"} else REFRESH_SECONDS
            time.sleep(sleep_for)
    finally:
        epd.sleep()


def play_overlay_animation(epd, animator: Animator, animation: dict) -> None:
    state = animation.get("state", "MEETING")
    mode = animation.get("mode", "fullscreen")
    repeat = int(animation.get("repeat", 1) or 1)
    message = animation.get("message", "")
    is_meeting_reminder = (
        mode == "meeting_reminder"
        or state == "MEETING"
        or "minutes" in animation
        or str(message).lower().startswith("don't be late")
        or str(message).lower().startswith("dont be late")
    )
    is_job_reminder = mode == "job_reminder"

    for _ in range(max(1, repeat)):
        for _frame_number in range(5):
            frame_state = "MEETING" if is_meeting_reminder else "BARK" if is_job_reminder else state
            frame = animator.next_frame(frame_state)
            if is_meeting_reminder:
                image = render_meeting_reminder(animation, frame)
            elif is_job_reminder:
                image = render_job_reminder(animation, frame)
            else:
                image = render_fullscreen_animation(state, message, frame)
            epd.display(image)
            time.sleep(0.8)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Albus Barks e-ink dashboard")
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--once", action="store_true", help="Render one frame and exit")
    parser.add_argument("--simulate", action="store_true", help="Force simulator instead of Waveshare display")
    args = parser.parse_args()
    run(api_url=args.api_url, once=args.once, simulate=args.simulate)
