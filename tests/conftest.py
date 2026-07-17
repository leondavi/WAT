"""Test fixtures: a lightweight fake page/driver so the real action handlers can be
exercised with no browser. This is the key to testing the *shipped* code path rather
than a stub that can drift from it.
"""

from __future__ import annotations

from typing import Any

import pytest

from wat.config import WatConfig
from wat.context import StepContext


class FakeLocator:
    """Canned element responses. Records interaction calls for assertions in tests."""

    def __init__(self, *, count: int = 1, text: str = "", visible: bool = True,
                 enabled: bool = True, checked: bool = False,
                 attrs: dict | None = None, value: str = ""):
        self._count = count
        self._text = text
        self._visible = visible
        self._enabled = enabled
        self._checked = checked
        self._attrs = attrs or {}
        self._value = value
        self.calls: list[tuple[str, tuple, dict]] = []

    # query methods used by assertions
    def count(self) -> int: return self._count
    def inner_text(self) -> str: return self._text
    def text_content(self) -> str: return self._text
    def is_visible(self) -> bool: return self._visible
    def is_enabled(self) -> bool: return self._enabled
    def is_checked(self) -> bool: return self._checked
    def get_attribute(self, name: str): return self._attrs.get(name)
    def input_value(self) -> str: return self._value

    # refinements
    def filter(self, **kw) -> "FakeLocator": return self
    def nth(self, i: int) -> "FakeLocator": return self
    def wait_for(self, **kw) -> None: self.calls.append(("wait_for", (), kw))

    # interactions (recorded)
    def _record(self, name):
        def fn(*a, **k):
            self.calls.append((name, a, k))
        return fn

    def __getattr__(self, name):  # click/fill/check/etc. become recorders
        return self._record(name)


class FakePage:
    """Minimal Playwright-Page stand-in for unit tests."""

    def __init__(self, *, url: str = "http://test/", title: str = "", body: str = "",
                 locators: dict[str, FakeLocator] | None = None, evaluate_result: Any = None):
        self._url = url
        self._title = title
        self._locators = locators or {}
        self._body = body
        self.evaluate_result = evaluate_result
        self.calls: list[tuple[str, Any]] = []

    @property
    def url(self) -> str: return self._url

    def title(self) -> str: return self._title
    def content(self) -> str: return self._body

    def locator(self, selector: str) -> FakeLocator:
        if selector == "body":
            return FakeLocator(text=self._body)
        return self._locators.get(selector, FakeLocator(count=0, text=""))

    def get_by_test_id(self, tid: str) -> FakeLocator:
        return self._locators.get(tid, FakeLocator(count=0))

    def goto(self, url: str, **kw) -> None: self._url = url; self.calls.append(("goto", url))
    def evaluate(self, expr: str, arg: Any = None): return self.evaluate_result
    def wait_for_timeout(self, ms: float) -> None: self.calls.append(("wait", ms))


class FakeDriver:
    def __init__(self, console_errors=None, network_failures=None, matches=None):
        self.page = None
        self.context = None
        self._console_errors = console_errors or []
        self.network_failures = network_failures or []
        self._matches = matches or []

    def console_errors(self): return self._console_errors
    def console_matches(self, pattern): return self._matches


class FakeContext:
    """Minimal Playwright BrowserContext stand-in; records storage_state saves."""

    def __init__(self):
        self.saved_to: str | None = None

    def storage_state(self, path: str | None = None):
        self.saved_to = path
        return {"cookies": [], "origins": []}

    def clear_cookies(self, *a, **k): pass
    def add_cookies(self, *a, **k): pass


class NullLog:
    dir = None
    def wat(self, *a, **k): pass
    def browser(self, *a, **k): pass
    def app(self, *a, **k): pass
    def step(self, *a, **k): pass
    def write_json(self, *a, **k): pass


def make_ctx(step: dict, *, page: FakePage | None = None, driver: FakeDriver | None = None,
             config: WatConfig | None = None, store: dict | None = None,
             browser_context: Any = None) -> StepContext:
    page = page or FakePage()
    driver = driver or FakeDriver()
    driver.page = page
    return StepContext(page=page, browser_context=browser_context, driver=driver,
                       config=config or WatConfig(wait_ms=200), flow={}, flow_stem="fl_test",
                       log=NullLog(), store=store if store is not None else {}, step=step)


@pytest.fixture
def ctx_factory():
    return make_ctx
