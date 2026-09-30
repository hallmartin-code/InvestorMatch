"""TEN Capital print style: restrained navy palette and Open Sans (bundled, SIL OFL)."""

from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.config import FONT_DIR, LOGO_PATH

NAVY = HexColor("#1F3864")
BLUE = HexColor("#2E75B6")
INK = HexColor("#1F2328")
INK_2 = HexColor("#4A5360")
MUTED = HexColor("#6B7380")
RULE = HexColor("#D9DDE3")
ZEBRA = HexColor("#F5F7FA")
TINT = HexColor("#EEF3FA")
WHITE = HexColor("#FFFFFF")

_FONTS = {"OpenSans": "OpenSans-Regular.ttf", "OpenSans-SemiBold": "OpenSans-SemiBold.ttf",
          "OpenSans-Bold": "OpenSans-Bold.ttf", "OpenSans-Italic": "OpenSans-Italic.ttf"}
_FALLBACK = {"OpenSans": "Helvetica", "OpenSans-SemiBold": "Helvetica-Bold", "OpenSans-Bold": "Helvetica-Bold",
             "OpenSans-Italic": "Helvetica-Oblique"}
_resolved: dict[str, str] | None = None


def font(name: str) -> str:
    global _resolved
    if _resolved is None:
        _resolved = {}
        for key, filename in _FONTS.items():
            try:
                if key not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(key, str(FONT_DIR / filename)))
                _resolved[key] = key
            except Exception:  # noqa: BLE001 - a missing font must not stop the report
                _resolved[key] = _FALLBACK[key]
        if _resolved["OpenSans"] == "OpenSans":
            pdfmetrics.registerFontFamily("OpenSans", normal="OpenSans", bold=_resolved["OpenSans-Bold"],
                                          italic=_resolved["OpenSans-Italic"], boldItalic=_resolved["OpenSans-Bold"])
    return _resolved.get(name, "Helvetica")


def logo_path():
    return LOGO_PATH if LOGO_PATH.is_file() else None
