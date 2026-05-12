"""PDF rendering and image manipulation — deterministic, no LLM calls."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps

from card_extractor.models import BoundingBox


# ---------------------------------------------------------------------------
# Coordinate math
# ---------------------------------------------------------------------------


def norm_to_px(
    x1: float, y1: float, x2: float, y2: float, w: int, h: int,
) -> tuple[int, int, int, int]:
    """Convert normalized [0,1] coords to pixel coords, clamped to image bounds."""
    px1 = int(round(x1 * (w - 1)))
    py1 = int(round(y1 * (h - 1)))
    px2 = int(round(x2 * (w - 1)))
    py2 = int(round(y2 * (h - 1)))

    px1 = max(0, min(px1, w - 1))
    px2 = max(0, min(px2, w - 1))
    py1 = max(0, min(py1, h - 1))
    py2 = max(0, min(py2, h - 1))

    px1, px2 = (px1, px2) if px1 <= px2 else (px2, px1)
    py1, py2 = (py1, py2) if py1 <= py2 else (py2, py1)
    return px1, py1, px2, py2


# ---------------------------------------------------------------------------
# PDF → PNG rendering (pypdfium2, Apache-2.0)
# ---------------------------------------------------------------------------


def pdf_to_page_pngs(
    pdf_path: Path, out_dir: Path, dpi: int = 300,
) -> list[Path]:
    """Render each page of a PDF to a PNG image at the given DPI."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))

    scale = dpi / 72.0
    saved: list[Path] = []

    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        out_path = out_dir / f"{pdf_path.stem}_{i + 1}.png"
        pil_image.save(str(out_path))
        saved.append(out_path)

    pdf.close()
    return saved


# ---------------------------------------------------------------------------
# Image cropping
# ---------------------------------------------------------------------------


def crop_region(
    image_path: Path,
    box: BoundingBox,
    out_path: Path,
    pad_px: int = 10,
) -> Optional[Path]:
    """Crop a bounding box region from an image with optional padding."""
    im = Image.open(image_path).convert("RGBA")
    w, h = im.size

    px1, py1, px2, py2 = norm_to_px(box.x1, box.y1, box.x2, box.y2, w, h)

    px1 = max(0, px1 - pad_px)
    py1 = max(0, py1 - pad_px)
    px2 = min(w - 1, px2 + pad_px)
    py2 = min(h - 1, py2 + pad_px)

    if px2 <= px1 or py2 <= py1:
        return None

    crop = im.crop((px1, py1, px2 + 1, py2 + 1))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(str(out_path))
    return out_path


def crop_front_boxes(
    image_path: Path,
    boxes: list[BoundingBox],
    out_dir: Path,
    base_name: str,
    pad_px: int = 10,
) -> list[Path]:
    """Crop all Front-labeled boxes and save as numbered PNGs."""
    front_boxes = [b for b in boxes if b.card_type == "Front"]
    saved: list[Path] = []

    for idx, box in enumerate(front_boxes, start=1):
        out_path = out_dir / f"{base_name}_boxed_{idx}.png"
        result = crop_region(image_path, box, out_path, pad_px=pad_px)
        if result is not None:
            saved.append(result)

    return saved


# ---------------------------------------------------------------------------
# Debug visualization
# ---------------------------------------------------------------------------


_COLOR_MAP = {"Front": "lime", "Back": "red"}
_FALLBACK_COLORS = ["yellow", "cyan", "magenta", "orange"]


def draw_debug_boxes(
    image_path: Path,
    boxes: list[BoundingBox],
    out_path: Path,
    line_width: Optional[int] = None,
) -> None:
    """Draw labeled outlines on an image for visual QA."""
    im = Image.open(image_path).convert("RGBA")
    w, h = im.size

    if line_width is None:
        line_width = max(3, min(w, h) // 300)

    draw = ImageDraw.Draw(im)
    for i, box in enumerate(boxes):
        px1, py1, px2, py2 = norm_to_px(box.x1, box.y1, box.x2, box.y2, w, h)
        color = _COLOR_MAP.get(box.card_type, _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)])
        draw.rectangle([px1, py1, px2, py2], outline=color, width=line_width)
        label = f"{i + 1}:{box.card_type}"
        draw.text((px1 + 3, max(0, py1 - 14)), label, fill=color)

    im.save(str(out_path))


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


def preprocess_for_vlm(image_path: Path, out_path: Path) -> Path:
    """Apply preprocessing to improve VLM accuracy on degraded scans.

    Normalizes contrast and strips the alpha channel.  If anything goes
    wrong the original path is returned unchanged (graceful degradation).
    """
    try:
        im = Image.open(image_path)
        # Drop alpha — VLMs don't need it
        if im.mode == "RGBA":
            im = im.convert("RGB")
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im = ImageOps.autocontrast(im, cutoff=1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(str(out_path))
        return out_path
    except Exception:
        return image_path



# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def encode_image_base64(image_path: Path) -> str:
    """Read an image file and return its base64-encoded contents."""
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")
