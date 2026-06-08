import importlib
import platform
from pathlib import Path

from PIL import Image

from .config import EPD_TYPE, RUNTIME_DIR


class SimulatedEPD:
    width = 250
    height = 122

    def init(self):
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    def display(self, image: Image.Image):
        output = RUNTIME_DIR / "last_render.png"
        image.save(output)
        print(f"Simulated e-ink render saved to {output}")

    def sleep(self):
        pass


class WaveshareEPD:
    def __init__(self, epd_type: str = EPD_TYPE):
        self.epd_type = epd_type
        self.epd = self._load_epd_module().EPD()
        self.width = self.epd.height
        self.height = self.epd.width
        self._base_loaded = False

    def _load_epd_module(self):
        import_errors = []
        for module_name in (
            f"resources.waveshare_epd.{self.epd_type}",
            f"waveshare_epd.{self.epd_type}",
        ):
            try:
                return importlib.import_module(module_name)
            except ImportError as exc:
                import_errors.append(f"{module_name}: {exc}")

        raise ImportError("; ".join(import_errors))

    def init(self):
        self._init_partial_update()

    def display(self, image: Image.Image):
        bw = image.convert("1")
        buffer = self.epd.getbuffer(bw)

        if not self._base_loaded and hasattr(self.epd, "displayPartBaseImage"):
            self.epd.displayPartBaseImage(buffer)
            self._base_loaded = True
            return

        if hasattr(self.epd, "displayPartial"):
            self.epd.displayPartial(buffer)
        else:
            self.epd.display(buffer)
        self._base_loaded = True

    def sleep(self):
        self.epd.sleep()

    def _init_partial_update(self):
        if hasattr(self.epd, "PART_UPDATE"):
            self.epd.init(self.epd.PART_UPDATE)
        elif hasattr(self.epd, "lut_partial_update"):
            self.epd.init(self.epd.lut_partial_update)
        else:
            self.epd.init()


def _is_probably_raspberry_pi() -> bool:
    machine = platform.machine().lower()
    if machine in {"armv6l", "armv7l", "aarch64"} and platform.system() == "Linux":
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text(errors="ignore")
            return "raspberry pi" in cpuinfo.lower() or "bcm" in cpuinfo.lower()
        except Exception:
            return True
    return False


def get_display(simulate: bool = False):
    if simulate:
        return SimulatedEPD()
    try:
        return WaveshareEPD()
    except Exception as exc:
        if _is_probably_raspberry_pi():
            raise
        print(f"Waveshare driver unavailable, using simulator: {exc}")
        return SimulatedEPD()
