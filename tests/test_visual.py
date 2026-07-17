"""Visual regression: diff_png (pure) + the assert_screenshot action.

Exercises the real action against a fake page whose screenshot() writes a generated PNG,
so the create/compare/mismatch/update paths are covered without a browser.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PIL")  # the [visual] extra; skipped if Pillow is absent

from PIL import Image  # noqa: E402

import wat  # noqa: F401,E402 — registers core actions
from wat.ext import visual as V  # noqa: E402 — registers assert_screenshot
from wat.config import WatConfig  # noqa: E402
from conftest import make_ctx, NullLog  # noqa: E402


def _png(path, color, size=(20, 20)):
    Image.new("RGB", size, color).save(path)


class ShotPage:
    """Fake page whose screenshot() copies a prepared PNG to the requested path."""

    def __init__(self, src):
        self._src = src

    def screenshot(self, path, **kw):
        Image.open(self._src).save(path)


class DirLog(NullLog):
    def __init__(self, d):
        self.dir = d


def _ctx(step, tmp_path, page_png):
    cfg = WatConfig(root=str(tmp_path))
    ctx = make_ctx(step, page=ShotPage(page_png), config=cfg)
    ctx.log = DirLog(tmp_path / "run")          # actual/diff land here
    (tmp_path / "run").mkdir(exist_ok=True)
    return ctx


# -- diff_png (pure) ---------------------------------------------------------

def test_diff_png_identical_is_zero(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _png(a, (10, 20, 30)); _png(b, (10, 20, 30))
    d = V.diff_png(a, b)
    assert d["dimensions_match"] and d["diff_pixels"] == 0 and d["ratio"] == 0.0


def test_diff_png_counts_changed_pixels(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _png(a, (0, 0, 0), size=(10, 10))
    img = Image.new("RGB", (10, 10), (0, 0, 0)); img.putpixel((0, 0), (255, 255, 255)); img.save(b)
    d = V.diff_png(a, b)
    assert d["diff_pixels"] == 1 and d["total"] == 100 and 0 < d["ratio"] < 1


def test_diff_png_dimension_mismatch(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _png(a, (0, 0, 0), size=(10, 10)); _png(b, (0, 0, 0), size=(12, 10))
    assert V.diff_png(a, b)["dimensions_match"] is False


# -- assert_screenshot action ------------------------------------------------

def test_first_run_creates_baseline_and_passes(tmp_path):
    shot = tmp_path / "shot.png"; _png(shot, (5, 5, 5))
    ctx = _ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, shot)
    result = V.assert_screenshot(ctx)
    assert result["pass"] is True
    assert (tmp_path / "baselines" / "home.png").exists()  # baseline established


def test_matching_screenshot_passes(tmp_path):
    shot = tmp_path / "shot.png"; _png(shot, (5, 5, 5))
    step = {"action": "assert_screenshot", "name": "home"}
    V.assert_screenshot(_ctx(step, tmp_path, shot))          # create baseline
    assert V.assert_screenshot(_ctx(step, tmp_path, shot))["pass"] is True  # compare -> match


def test_mismatch_fails_and_writes_diff(tmp_path):
    base_shot = tmp_path / "base.png"; _png(base_shot, (0, 0, 0), size=(10, 10))
    V.assert_screenshot(_ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, base_shot))
    changed = tmp_path / "changed.png"
    img = Image.new("RGB", (10, 10), (0, 0, 0))
    for x in range(10):
        img.putpixel((x, 0), (255, 0, 0))
    img.save(changed)
    ctx = _ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, changed)
    result = V.assert_screenshot(ctx)
    assert result["pass"] is False and "visual mismatch" in result["reason"]
    assert list((tmp_path / "run").glob("*.diff.png")), "a diff image should be written on mismatch"


def test_threshold_tolerates_small_diff(tmp_path):
    base_shot = tmp_path / "base.png"; _png(base_shot, (0, 0, 0), size=(10, 10))
    V.assert_screenshot(_ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, base_shot))
    changed = tmp_path / "changed.png"
    img = Image.new("RGB", (10, 10), (0, 0, 0)); img.putpixel((0, 0), (255, 255, 255)); img.save(changed)
    # 1/100 pixels differ -> passes with a 2% tolerance, fails at 0.
    step = {"action": "assert_screenshot", "name": "home", "max_diff_ratio": 0.02}
    assert V.assert_screenshot(_ctx(step, tmp_path, changed))["pass"] is True


def test_update_rewrites_baseline(tmp_path):
    base_shot = tmp_path / "base.png"; _png(base_shot, (0, 0, 0))
    V.assert_screenshot(_ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, base_shot))
    new_shot = tmp_path / "new.png"; _png(new_shot, (255, 255, 255))
    step = {"action": "assert_screenshot", "name": "home", "update": True}
    assert V.assert_screenshot(_ctx(step, tmp_path, new_shot))["pass"] is True  # update -> pass
    # baseline now holds the new image, so a plain compare against it matches
    assert V.assert_screenshot(_ctx({"action": "assert_screenshot", "name": "home"}, tmp_path, new_shot))["pass"]
