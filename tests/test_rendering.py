"""Tests for rendering module — coordinate math and image operations."""

from __future__ import annotations

import pytest

from card_extractor.models import BoundingBox
from card_extractor.rendering import norm_to_px


class TestBoundingBoxClamping:
    """BoundingBox.clamp_coordinate replaces the old standalone clamp01."""

    def test_in_range(self):
        box = BoundingBox(x1=0.5, y1=0.5, x2=0.8, y2=0.8)
        assert box.x1 == 0.5

    def test_below_zero(self):
        box = BoundingBox(x1=-0.1, y1=0.0, x2=0.5, y2=0.5)
        assert box.x1 == 0.0

    def test_above_one(self):
        box = BoundingBox(x1=0.0, y1=0.0, x2=1.5, y2=0.5)
        assert box.x2 == 1.0

    def test_boundaries(self):
        box = BoundingBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0)
        assert box.x1 == 0.0
        assert box.x2 == 1.0


class TestNormToPx:
    def test_full_image(self):
        px1, py1, px2, py2 = norm_to_px(0.0, 0.0, 1.0, 1.0, 100, 200)
        assert px1 == 0
        assert py1 == 0
        assert px2 == 99
        assert py2 == 199

    def test_quarter_image(self):
        px1, py1, px2, py2 = norm_to_px(0.0, 0.0, 0.5, 0.5, 100, 100)
        assert px1 == 0
        assert py1 == 0
        assert px2 == 50  # round(0.5 * 99) = 50
        assert py2 == 50

    def test_swapped_coords(self):
        """If x1>x2 or y1>y2, they get swapped."""
        px1, py1, px2, py2 = norm_to_px(0.8, 0.9, 0.2, 0.1, 100, 100)
        assert px1 <= px2
        assert py1 <= py2

    def test_clamping(self):
        """Values outside [0, w-1] or [0, h-1] get clamped."""
        px1, py1, px2, py2 = norm_to_px(0.0, 0.0, 1.0, 1.0, 10, 10)
        assert px1 >= 0
        assert py1 >= 0
        assert px2 <= 9
        assert py2 <= 9

    def test_small_image(self):
        px1, py1, px2, py2 = norm_to_px(0.0, 0.0, 1.0, 1.0, 1, 1)
        assert (px1, py1, px2, py2) == (0, 0, 0, 0)
