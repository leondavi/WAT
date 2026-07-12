"""Network actions: mock responses, wait for traffic, assert on it.

Mocking a backend response (``mock``) is the cleanest way to isolate "app bug vs
backend" in a complex flow — force a 500 and assert the UI degrades gracefully,
without touching the real server.
"""

from __future__ import annotations

import json

from ..context import StepContext
from ..registry import register_action


@register_action("mock", aliases=("route",), required=("url",), group="network",
                 description="Stub responses for URLs matching a glob/regex pattern.")
def mock(ctx: StepContext) -> None:
    pattern = str(ctx.field("url", required=True))
    status = int(ctx.step.get("status", 200))
    body = ctx.step.get("body", "")
    content_type = ctx.step.get("content_type", "application/json")
    if not isinstance(body, str):
        body = json.dumps(body)

    def _fulfill(route):
        route.fulfill(status=status, content_type=content_type, body=body)

    ctx.page.route(pattern, _fulfill)
    ctx.log.wat(f"mocking {pattern} -> {status}")


@register_action("unroute", required=("url",), group="network",
                 description="Remove a previously installed mock/route.")
def unroute(ctx: StepContext) -> None:
    ctx.page.unroute(str(ctx.field("url", required=True)))


@register_action("wait_for_response", required=("url",), group="network",
                 description="Wait for a response whose URL matches the pattern.")
def wait_for_response(ctx: StepContext) -> None:
    ctx.page.wait_for_response(str(ctx.field("url", required=True)), timeout=ctx.timeout_ms())


@register_action("wait_for_request", required=("url",), group="network",
                 description="Wait for a request whose URL matches the pattern.")
def wait_for_request(ctx: StepContext) -> None:
    ctx.page.wait_for_request(str(ctx.field("url", required=True)), timeout=ctx.timeout_ms())


@register_action("assert_response", required=("url", "status"), group="network",
                 description="Wait for a matching response and assert its status.")
def assert_response(ctx: StepContext) -> dict:
    want = int(ctx.field("status", required=True))
    resp = ctx.page.wait_for_response(str(ctx.field("url", required=True)), timeout=ctx.timeout_ms())
    ok = resp.status == want
    return {"pass": ok, "reason": None if ok else f"status {resp.status} != {want}"}
