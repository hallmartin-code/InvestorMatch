"""Optional OCR for image-only slides and pictures, using RapidOCR (ONNX; no system binary).

If RapidOCR is not installed, ``available()`` is False and callers record a limitation instead.
"""

from __future__ import annotations

import io
from functools import lru_cache

from app.utils.logging import get_logger

LOGGER = get_logger(__name__)


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:  # noqa: BLE001 - optional dependency (ImportError or onnxruntime load errors)
        return None
    try:
        return RapidOCR()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("OCR engine failed to start: %s", exc.__class__.__name__)
        return None


def available() -> bool:
    return _engine() is not None


def ocr_image(data: bytes) -> str:
    """Image bytes → text lines in reading order ('' when nothing is recognized)."""
    engine = _engine()
    if engine is None or not data:
        return ""
    try:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            array = np.array(image.convert("RGB"))
        result, _elapsed = engine(array)
    except Exception as exc:  # noqa: BLE001 - OCR is best effort
        LOGGER.warning("OCR failed on an image: %s", exc.__class__.__name__)
        return ""
    if not result:
        return ""
    # result rows: [box, text, confidence]; group into lines by the box's vertical centre.
    items = []
    for box, text, confidence in result:
        if float(confidence) < 0.5 or not str(text).strip():
            continue
        ys = [pt[1] for pt in box]
        xs = [pt[0] for pt in box]
        items.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), str(text).strip()))
    items.sort()
    lines: list[list[tuple[float, str]]] = []
    last_y = None
    for y, x, height, text in items:
        if last_y is None or abs(y - last_y) > max(height * 0.6, 6):
            lines.append([])
        lines[-1].append((x, text))
        last_y = y
    return "\n".join(" ".join(t for _x, t in sorted(line)) for line in lines)
