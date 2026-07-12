"""Capture & artifact actions: store values, screenshots, PDFs, log tails."""

from __future__ import annotations

import json
from pathlib import Path

from ..context import StepContext
from ..errors import StepFailure, SOURCE_FLOW_AUTHORING
from ..registry import register_action


@register_action("capture", required=("selector",), group="capture",
                 description="Read an element attribute/value/text into the capture store.")
def capture(ctx: StepContext) -> None:
    var = ctx.step.get("var") or ctx.step.get("store_as")
    if not var:
        raise StepFailure("capture requires 'var' (or 'store_as')", source=SOURCE_FLOW_AUTHORING)
    loc = ctx.locator()
    attr = ctx.step.get("attr")
    if attr:
        value = loc.get_attribute(attr)
    elif ctx.step.get("property") == "value":
        value = loc.input_value()
    else:
        value = loc.text_content()
    ctx.store[var] = (value or "").strip()
    ctx.log.wat(f"captured {var}={ctx.store[var]!r}")


@register_action("screenshot", group="capture", description="Save a PNG to the artifacts dir.")
def screenshot(ctx: StepContext) -> None:
    name = ctx.step.get("name") or ctx.step.get("path") or "screenshot"
    name = Path(str(name)).name
    if not name.endswith(".png"):
        name += ".png"
    out_dir = ctx.config.artifacts_path() / ctx.flow_stem
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    if ctx.step.get("selector"):
        ctx.locator().screenshot(path=str(target))
    else:
        ctx.page.screenshot(path=str(target), full_page=bool(ctx.step.get("full_page", True)))
    ctx.log.wat(f"screenshot -> {target}")


@register_action("pdf", group="capture", description="Save the page as a PDF (chromium only).")
def pdf(ctx: StepContext) -> None:
    name = Path(str(ctx.step.get("name", "page"))).name
    out_dir = ctx.config.artifacts_path() / ctx.flow_stem
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.page.pdf(path=str(out_dir / (name if name.endswith(".pdf") else name + ".pdf")))


@register_action("snapshot", group="capture",
                 description="Save the accessibility tree snapshot as JSON.")
def snapshot(ctx: StepContext) -> None:
    tree = ctx.page.accessibility.snapshot()
    out_dir = ctx.config.artifacts_path() / ctx.flow_stem
    out_dir.mkdir(parents=True, exist_ok=True)
    name = Path(str(ctx.step.get("name", "a11y"))).name
    (out_dir / (name + ".json")).write_text(json.dumps(tree, indent=2), encoding="utf-8")


@register_action("tail_log", group="capture",
                 description="Read the tail of a log file into the [APP] channel.")
def tail_log(ctx: StepContext) -> None:
    path = ctx.field("path") or ctx.config.app_log_path
    if not path:
        raise StepFailure("tail_log needs 'path' or config.app_log_path", source=SOURCE_FLOW_AUTHORING)
    lines = int(ctx.step.get("lines", 50))
    p = Path(str(path))
    if not p.exists():
        ctx.log.app(f"(no log file at {p})")
        return
    tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    for line in tail:
        ctx.log.app(line)
    if ctx.step.get("store_as"):
        ctx.store[ctx.step["store_as"]] = "\n".join(tail)


@register_action("save_store", group="capture",
                 description="Dump the capture store to an artifact JSON file.")
def save_store(ctx: StepContext) -> None:
    out_dir = ctx.config.artifacts_path() / ctx.flow_stem
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "store.json").write_text(json.dumps(ctx.store, indent=2, default=str), encoding="utf-8")
