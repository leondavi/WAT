"""Visual regression extension: assert a screenshot matches a committed baseline.

Opt in with ``extensions = ["visual"]`` (installs the ``[visual]`` extra for Pillow).
Adds ``assert_screenshot``:

  * First run (no baseline) or ``visual_update`` -> the screenshot becomes the baseline
    and the step passes (so you establish/refresh baselines by running with ``--update-baselines``).
  * Otherwise the screenshot is diffed against the baseline pixel-by-pixel; the step fails
    if the fraction of differing pixels exceeds ``max_diff_ratio``, writing a ``.diff.png``
    (and the actual) into the run dir for inspection.

Baselines live in ``config.visual_baseline_dir`` (default ``<root>/baselines``) and are
meant to be committed. Diffs/actuals are transient run artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import StepContext
from ..errors import StepFailure, SOURCE_APP
from ..registry import register_action


def _pil() -> Any:
    try:
        from PIL import Image, ImageChops  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the [visual] extra
        raise StepFailure("action 'assert_screenshot' needs the [visual] extra (Pillow)",
                          source=SOURCE_APP) from exc
    return Image, ImageChops


def diff_png(baseline_path: str | Path, actual_path: str | Path, pixel_threshold: int = 0) -> dict[str, Any]:
    """Compare two PNGs. Pure + testable (no browser).

    Returns a dict with ``dimensions_match`` and, when they match, ``diff_pixels`` /
    ``total`` / ``ratio`` and a Pillow ``diff_image`` (the per-pixel difference).
    ``pixel_threshold`` (0-255) ignores per-channel noise below that delta.
    """
    Image, ImageChops = _pil()
    a = Image.open(baseline_path).convert("RGB")
    b = Image.open(actual_path).convert("RGB")
    if a.size != b.size:
        return {"dimensions_match": False, "baseline_size": a.size, "actual_size": b.size,
                "diff_pixels": None, "total": None, "ratio": 1.0, "diff_image": None}
    diff = ImageChops.difference(a, b)
    mask = diff.convert("L").point(lambda p: 255 if p > pixel_threshold else 0)
    diff_pixels = mask.histogram()[255]
    total = a.size[0] * a.size[1]
    return {"dimensions_match": True, "diff_pixels": diff_pixels, "total": total,
            "ratio": (diff_pixels / total) if total else 0.0, "diff_image": diff}


def _baseline_dir(ctx: StepContext) -> Path:
    raw = ctx.step.get("baseline_dir") or ctx.config.visual_baseline_dir or "baselines"
    p = Path(str(raw))
    return p if p.is_absolute() else (Path(ctx.config.root) / p)


def _out_dir(ctx: StepContext) -> Path:
    """Where transient actual/diff images go: the per-run log dir, else the artifacts dir."""
    d = getattr(ctx.log, "dir", None) or (ctx.config.artifacts_path() / ctx.flow_stem)
    Path(d).mkdir(parents=True, exist_ok=True)
    return Path(d)


def _take_shot(ctx: StepContext, target: Path) -> None:
    if ctx.step.get("selector"):
        ctx.locator().screenshot(path=str(target))
    else:
        ctx.page.screenshot(path=str(target), full_page=bool(ctx.step.get("full_page", False)))


@register_action("assert_screenshot", required=("name",), group="visual",
                 description="Compare a screenshot against a committed baseline (visual regression).")
def assert_screenshot(ctx: StepContext) -> dict:
    name = Path(str(ctx.field("name", required=True))).name
    if not name.endswith(".png"):
        name += ".png"
    baseline = _baseline_dir(ctx) / name
    out_dir = _out_dir(ctx)
    actual = out_dir / f"{ctx.flow_stem}.{name}"
    _take_shot(ctx, actual)

    update = bool(ctx.step.get("update", ctx.config.visual_update))
    if update or not baseline.exists():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(actual.read_bytes())
        ctx.log.wat(f"visual baseline {'updated' if update else 'created'}: {baseline}")
        return {"pass": True, "reason": None}

    threshold = float(ctx.step.get("max_diff_ratio", ctx.config.visual_max_diff_ratio))
    pixel_threshold = int(ctx.step.get("pixel_threshold", 0))
    d = diff_png(baseline, actual, pixel_threshold)
    if not d["dimensions_match"]:
        return {"pass": False,
                "reason": f"screenshot size changed: baseline {d['baseline_size']} vs actual {d['actual_size']}"}

    ok = d["ratio"] <= threshold
    if not ok and d["diff_image"] is not None:
        diff_path = out_dir / f"{ctx.flow_stem}.{name}.diff.png"
        d["diff_image"].save(str(diff_path))
        ctx.log.wat(f"visual diff written -> {diff_path}", level="warn")
    return {
        "pass": ok,
        "reason": None if ok else (
            f"visual mismatch: {d['diff_pixels']}/{d['total']} px differ "
            f"(ratio {d['ratio']:.4f} > max {threshold})"),
        "diff_pixels": d["diff_pixels"],
        "ratio": round(d["ratio"], 6),
    }
