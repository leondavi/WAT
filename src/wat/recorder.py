"""Flow recorder: capture real browser interactions into an ``fl_*.json`` draft.

``wat --record`` opens a headed browser; an injected script observes clicks, typing,
select/checkbox changes, and Enter/Escape presses, inferring a canonical WAT selector
for each (``testid`` > ``id`` > ``role``+name > ``name`` attr > short CSS path). When
the browser is closed, the collected steps are written as a flow file.

The output is deliberately a *draft*: selectors and waits need a human pass (the file
says so in its description), and assertions must be added by the author — a recorder
can see what you did, not what you meant to verify.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import WatConfig

# In-page observer. Capture-phase listeners so the app can't swallow events first.
# Payloads: {kind: click|type|select|check|uncheck|press, by, selector, name?, value?}
_RECORDER_JS = """(() => {
  if (window.__watRecorderInstalled) return;
  window.__watRecorderInstalled = true;

  const ACTIONABLE = 'button, a, input, select, textarea, label, [role="button"], [role="link"]';
  const target = el => (el.closest && el.closest(ACTIONABLE)) || el;

  const infer = el => {
    if (el.dataset && el.dataset.testid) return {by: 'testid', selector: el.dataset.testid};
    if (el.id) return {by: 'css', selector: '#' + CSS.escape(el.id)};
    const name = el.getAttribute && el.getAttribute('name');
    if (name) return {by: 'css', selector: el.tagName.toLowerCase() + "[name='" + name + "']"};
    const role = el.tagName === 'BUTTON' ? 'button' : (el.tagName === 'A' && el.href ? 'link' : null);
    const text = (el.textContent || '').trim();
    if (role && text && text.length <= 40) return {by: 'role', selector: role, name: text};
    // Fallback: a short positional CSS path (up to 3 ancestors).
    const part = e => {
      const tag = e.tagName.toLowerCase();
      const sibs = e.parentElement ? Array.from(e.parentElement.children).filter(c => c.tagName === e.tagName) : [];
      return sibs.length > 1 ? tag + ':nth-of-type(' + (sibs.indexOf(e) + 1) + ')' : tag;
    };
    const path = [];
    for (let e = el; e && e.tagName !== 'HTML' && path.length < 3; e = e.parentElement) path.unshift(part(e));
    return {by: 'css', selector: path.join(' > ')};
  };

  const send = payload => window._watRecord && window._watRecord(payload);

  document.addEventListener('click', ev => {
    const el = target(ev.target);
    if (el.tagName === 'SELECT' || el.tagName === 'OPTION') return;  // change event covers it
    send({kind: 'click', ...infer(el)});
  }, true);

  document.addEventListener('change', ev => {
    const el = ev.target;
    const loc = infer(el);
    if (el.tagName === 'SELECT') send({kind: 'select', ...loc, value: el.value});
    else if (el.type === 'checkbox') send({kind: el.checked ? 'check' : 'uncheck', ...loc});
    else if (el.type === 'radio') send({kind: 'check', ...loc});
    else send({kind: 'type', ...loc, value: el.value});
  }, true);

  document.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === 'Escape')
      send({kind: 'press', ...infer(target(ev.target)), value: ev.key});
  }, true);
})()"""

_KIND_TO_ACTION = {"click": "click", "type": "type", "select": "select_option",
                   "check": "check", "uncheck": "uncheck", "press": "press"}

# Navigations this soon after an interaction are treated as its consequence, not a step.
_NAV_ECHO_WINDOW_S = 1.5


class Recorder:
    """Collects recorded events into canonical steps (pure aggregation; no browser)."""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")
        self.steps: list[dict[str, Any]] = []
        self._last_interaction = 0.0

    # -- event intake ------------------------------------------------------

    def on_event(self, payload: dict[str, Any]) -> None:
        """Handle one in-page payload (the ``_watRecord`` binding target)."""
        kind = payload.get("kind")
        action = _KIND_TO_ACTION.get(kind)
        if action is None:
            return
        self._last_interaction = time.monotonic()
        step: dict[str, Any] = {"action": action, "by": payload["by"], "selector": payload["selector"]}
        if payload.get("name"):
            step["name"] = payload["name"]
        if "value" in payload:
            step["value"] = payload["value"]
        if step.get("by") == "css":
            del step["by"]  # css is the default; keep the file clean
        self._add(step)

    def on_navigation(self, url: str) -> None:
        """Record ``open`` for the first navigation; later ones only when they are not
        the immediate echo of a recorded click/press (heuristic, documented)."""
        rel = self._relativize(url)
        if not self.steps:
            self.steps.append({"action": "open", "url": rel})
            return
        if time.monotonic() - self._last_interaction > _NAV_ECHO_WINDOW_S:
            self._add({"action": "navigate", "url": rel})

    # -- assembly ----------------------------------------------------------

    def _add(self, step: dict[str, Any]) -> None:
        prev = self.steps[-1] if self.steps else None
        same_target = prev is not None and prev.get("selector") == step.get("selector") \
            and prev.get("by") == step.get("by")
        # Coalesce keystroke-by-keystroke typing into one final `type`.
        if same_target and step["action"] == "type" and prev["action"] == "type":
            prev["value"] = step["value"]
            return
        # A click that merely toggled/selected is subsumed by the change it caused.
        if same_target and prev["action"] == "click" \
                and step["action"] in ("select_option", "check", "uncheck"):
            self.steps[-1] = step
            return
        self.steps.append(step)

    def _relativize(self, url: str) -> str:
        if self.base_url and url.startswith(self.base_url):
            return url[len(self.base_url):] or "/"
        return url

    def flow(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "description": "Recorded by `wat --record` - a DRAFT: review selectors, "
                           "replace sleeps/waits, and add assertions before relying on it.",
            "steps": self.steps or [{"action": "open", "url": "/"}],
        }

    def save(self, out_path: str | Path, name: str | None = None) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.flow(name or out_path.stem), indent=2,
                                       ensure_ascii=False) + "\n", encoding="utf-8")
        return out_path


def attach(context: Any, recorder: Recorder) -> None:
    """Wire *recorder* into a Playwright *context* (binding + init script + navigation)."""
    context.expose_binding("_watRecord", lambda source, payload: recorder.on_event(payload))
    context.add_init_script(_RECORDER_JS)

    def _on_page(page: Any) -> None:
        page.on("framenavigated",
                lambda frame: recorder.on_navigation(frame.url) if frame.parent_frame is None else None)

    context.on("page", _on_page)
    for page in context.pages:
        _on_page(page)


def record_flow(config: WatConfig, out_path: str | Path) -> Path:
    """Open a headed browser, record until it is closed, then write the flow file."""
    from playwright.sync_api import sync_playwright

    recorder = Recorder(base_url=config.base_url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel=config.channel or None)
        context = browser.new_context()
        attach(context, recorder)
        page = context.new_page()
        try:
            page.goto(config.base_url)
        except Exception:
            pass  # base_url may not be reachable; the user can navigate manually
        print(f"Recording... interact with the browser, then close it to save {out_path}")
        try:
            while context.pages:
                context.pages[0].wait_for_timeout(500)
        except Exception:
            pass  # browser/context closed by the user - recording is done
    return recorder.save(out_path)
