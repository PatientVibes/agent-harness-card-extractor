"""Coordinate-system bridge: harness BoundingBox (normalized 0–1) → pdf_vlm_renderer BoundingBox (pixels).

The harness ``BoundingBox`` at :mod:`card_extractor.models` is the VLM-prompt
contract (prompts return normalized coords + a ``card_type`` label). The
``pdf_vlm_renderer.BoundingBox`` is pixel-coord + label + confidence — that's
the type used at the rendering boundary.

This module is the only place that knows about both.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pdf_vlm_renderer import BoundingBox as RendererBox

from card_extractor.models import BoundingBox as HarnessBox


def norm_to_px(box: HarnessBox, width: int, height: int) -> RendererBox:
    """Convert a normalized harness ``BoundingBox`` (0–1 coords) to pixel coords.

    Clamps coordinates to ``[0, width-1] / [0, height-1]`` and normalizes ordering
    so ``x_min <= x_max`` and ``y_min <= y_max`` — mirrors the historical
    ``rendering.norm_to_px`` semantics.
    """
    px1 = int(round(box.x1 * (width - 1)))
    py1 = int(round(box.y1 * (height - 1)))
    px2 = int(round(box.x2 * (width - 1)))
    py2 = int(round(box.y2 * (height - 1)))

    px1 = max(0, min(px1, width - 1))
    px2 = max(0, min(px2, width - 1))
    py1 = max(0, min(py1, height - 1))
    py2 = max(0, min(py2, height - 1))

    px1, px2 = (px1, px2) if px1 <= px2 else (px2, px1)
    py1, py2 = (py1, py2) if py1 <= py2 else (py2, py1)

    return RendererBox(
        x_min=px1,
        y_min=py1,
        x_max=px2,
        y_max=py2,
        label=box.card_type,
    )


def norm_to_px_for_image(box: HarnessBox, image_path: Path) -> RendererBox:
    """Convert a normalized harness box to pixel coords using an image file's dimensions."""
    with Image.open(image_path) as im:
        w, h = im.size
    return norm_to_px(box, w, h)
