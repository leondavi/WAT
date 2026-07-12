"""Flow migration: field normalization + review flags."""

from __future__ import annotations

import wat  # noqa: F401 — registers core actions
from wat.migrate import migrate_flow, migrate_step


def test_text_is_renamed_to_value():
    step, notes = migrate_step({"action": "type", "selector": "#x", "text": "hi"})
    assert step["value"] == "hi" and "text" not in step
    assert notes == []


def test_legacy_locator_mapped_and_flagged():
    step, notes = migrate_step({"action": "click", "by": "link_text", "selector": "Home"})
    assert step["by"] == "text"
    assert any("link_text" in n for n in notes)


def test_async_assert_js_flagged():
    _, notes = migrate_step({"action": "assert_js", "script": "arguments[0]()"})
    assert any("Promise" in n for n in notes)


def test_unknown_action_flagged_for_plugin():
    _, notes = migrate_step({"action": "open_messages_class", "class_code": "X"})
    assert any("needs an extension or app plugin" in n for n in notes)


def test_known_plugin_action_not_flagged_when_registered():
    from wat import plugins

    plugins.load(["sql"])
    _, notes = migrate_step({"action": "sql", "query": "select 1"})
    assert not any("needs an extension" in n for n in notes)


def test_migrate_flow_collects_report():
    flow = {"steps": [
        {"action": "open", "url": "/"},
        {"action": "frobnicate"},
    ]}
    new_flow, report = migrate_flow(flow)
    assert len(new_flow["steps"]) == 2
    assert any(r["action"] == "frobnicate" for r in report)
