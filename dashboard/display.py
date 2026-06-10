from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


SCREEN_WIDTH = 250
SCREEN_HEIGHT = 122

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources" / "images" / "status"


def load_font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for path in candidates:
        try:
            if path and Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


FONT_TINY = load_font(8)
FONT_SMALL = load_font(10)
FONT_MEDIUM = load_font(11)
FONT_BOLD = load_font(11, bold=True)
FONT_TITLE = load_font(14, bold=True)


def safe_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def format_due_time(value: Optional[str]) -> str:
    if not value:
        return ""

    try:
        dt = datetime.fromisoformat(value.replace("Z", ""))
        return dt.strftime("%H:%M")
    except Exception:
        return ""


def mood_icon(dog_state: str) -> str:
    icons = {
        "IDLE": "•",
        "BARK": "!",
        "HAPPY": "*",
        "SLEEPY": "z",
        "SAD": "!",
    }
    return icons.get(dog_state.upper(), "•")


def load_dog_image(
    dog_state: str,
    frame_path: Optional[Path] = None,
    max_size: tuple[int, int] = (92, 72),
) -> Image.Image:
    state = dog_state.upper()

    if frame_path and frame_path.exists():
        path = frame_path
    else:
        path = RESOURCES_DIR / state / "1.png"

    if not path.exists():
        path = RESOURCES_DIR / "IDLE" / "1.png"

    dog = Image.open(path).convert("L")

    # Crop white space around the dog so it looks larger on screen
    inverted = Image.eval(dog, lambda p: 255 - p)
    bbox = inverted.getbbox()
    if bbox:
        dog = dog.crop(bbox)

    # Keep it sized for the target dashboard area.
    dog.thumbnail(max_size)

    # Convert to clean 1-bit for e-ink
    dog = dog.point(lambda p: 255 if p > 175 else 0).convert("1")

    return dog


def render_dashboard(state: dict, frame_path: Optional[Path] = None) -> Image.Image:
    dog_state = state.get("dog_state", "IDLE").upper()
    message = state.get("message", "Albus is waiting")
    tasks = state.get("tasks", [])

    image = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    # Header
    now = datetime.now().strftime("%H:%M")
    draw.text((4, 2), now, font=FONT_TITLE, fill=0)
    draw.text((195, 2), "ALBUS", font=FONT_TITLE, fill=0)
    draw.line((4, 20, 246, 20), fill=0, width=1)

    # State row
    draw.text((4, 24), dog_state, font=FONT_BOLD, fill=0)
    draw.text((52, 24), mood_icon(dog_state), font=FONT_BOLD, fill=0)
    draw.text((66, 24), safe_text(message, 23), font=FONT_SMALL, fill=0)

    # Divider
    draw.line((4, 39, 246, 39), fill=0, width=1)

    # Tasks area
    y = 44
    if not tasks:
        draw.text((6, y), "No tasks", font=FONT_BOLD, fill=0)
        draw.text((6, y + 14), "Albus can rest", font=FONT_SMALL, fill=0)
    else:
        for task in tasks[:3]:
            title = safe_text(task.get("title", "Untitled"), 14)
            due = format_due_time(task.get("due_time"))
            status = task.get("status", "pending")

            checkbox = "[x]" if status == "done" else "[ ]"

            draw.text((6, y), checkbox, font=FONT_SMALL, fill=0)
            draw.text((28, y), title, font=FONT_SMALL, fill=0)

            if due:
                draw.text((110, y), due, font=FONT_SMALL, fill=0)

            y += 15

    # Dog image
    dog = load_dog_image(dog_state, frame_path)

    dog_x = SCREEN_WIDTH - dog.width - 6
    dog_y = SCREEN_HEIGHT - dog.height - 4
    image.paste(dog, (dog_x, dog_y))

    # Dog area border disabled; it made the sprite feel boxed-in on the e-ink screen.
    # draw.rectangle((158, 42, 246, 118), outline=0)

    return image


def render_fullscreen_animation(state: str, message: str = "", frame_path: Optional[Path] = None) -> Image.Image:
    image = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    dog = load_dog_image(state, frame_path)
    dog.thumbnail((150, 102))
    dog_x = (SCREEN_WIDTH - dog.width) // 2
    dog_y = 6 if message else (SCREEN_HEIGHT - dog.height) // 2
    image.paste(dog, (dog_x, dog_y))

    if message:
        draw.text((6, SCREEN_HEIGHT - 15), safe_text(message, 34), font=FONT_SMALL, fill=0)

    return image


def wrap_text(text: str, font, max_width: int, max_lines: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
        current = word

        if len(lines) == max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if lines and len(lines) == max_lines:
        last = lines[-1]
        while font.getbbox(last + "...")[2] - font.getbbox(last + "...")[0] > max_width and last:
            last = last[:-1]
        lines[-1] = (last + "...") if last != lines[-1] else lines[-1]

    return lines


def render_meeting_reminder(animation: dict, frame_path: Optional[Path] = None) -> Image.Image:
    image = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    minutes = animation.get("minutes")
    title = animation.get("title", "Meeting")

    draw.text((4, 2), datetime.now().strftime("%H:%M"), font=FONT_TITLE, fill=0)
    draw.text((195, 2), "ALBUS", font=FONT_TITLE, fill=0)
    draw.line((4, 20, 246, 20), fill=0, width=1)

    dog = load_dog_image("MEETING", frame_path, max_size=(122, 98))
    dog_x = 4 + ((118 - dog.width) // 2)
    dog_y = SCREEN_HEIGHT - dog.height - 2
    image.paste(dog, (dog_x, dog_y))

    text_x = 132
    text_width = 112

    draw.text((text_x, 27), "DONT", font=FONT_TITLE, fill=0)
    draw.text((text_x, 43), "BE LATE", font=FONT_TITLE, fill=0)

    if minutes is not None:
        draw.text((text_x, 63), f"In {minutes} min", font=FONT_BOLD, fill=0)
    else:
        draw.text((text_x, 63), "Meeting soon", font=FONT_BOLD, fill=0)

    y = 81
    for line in wrap_text(title, FONT_SMALL, text_width, 3):
        draw.text((text_x, y), line, font=FONT_SMALL, fill=0)
        y += 12

    return image
