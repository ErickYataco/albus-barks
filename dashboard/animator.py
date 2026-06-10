from itertools import cycle
from pathlib import Path

from .config import STATUS_IMAGE_DIR


class Animator:
    def __init__(self, base_dir: Path = STATUS_IMAGE_DIR):
        self.base_dir = base_dir
        self.cycles: dict[str, cycle] = {}

    def _frames_for_state(self, state: str) -> list[Path]:
        state = state.upper()
        folder = self.base_dir / state
        frames = sorted(path for path in folder.glob("*.png") if not path.name.startswith("_"))
        if not frames:
            frames = sorted(path for path in (self.base_dir / "IDLE").glob("*.png") if not path.name.startswith("_"))
        return frames

    def next_frame(self, state: str) -> Path | None:
        state = state.upper()
        if state not in self.cycles:
            frames = self._frames_for_state(state)
            self.cycles[state] = cycle(frames) if frames else cycle([])
        return next(self.cycles[state], None)
