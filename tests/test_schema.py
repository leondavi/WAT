"""Schema: canonicalization, validation, and label handling."""

from __future__ import annotations

import json

import pytest

import wat  # noqa: F401 — registers core actions used by the validator
from wat.errors import SchemaError
from wat.schema import canonicalize_step, flow_labels, load_flow, validate_flow


def test_text_alias_maps_to_value():
    step = canonicalize_step({"action": "type", "selector": "#x", "text": "hi"})
    assert step["value"] == "hi"


def test_real_drag_legacy_selector_aliases():
    step = canonicalize_step({"action": "real_drag", "source_selector": "#a", "target_selector": "#b"})
    assert step["from_selector"] == "#a" and step["to_selector"] == "#b"
    # a real_drag flow using legacy field names now validates
    assert validate_flow({"steps": [step]}) == []


def test_sleep_ms_alias_maps_to_seconds():
    step = canonicalize_step({"action": "sleep", "ms": 500})
    assert step["seconds"] == 0.5
    assert validate_flow({"steps": [step]}) == []


def test_js_alias_maps_to_script():
    step = canonicalize_step({"action": "eval_js", "js": "return 1"})
    assert step["script"] == "return 1"
    assert validate_flow({"steps": [step]}) == []


def test_canonicalize_requires_action():
    with pytest.raises(SchemaError):
        canonicalize_step({"selector": "#x"})


def test_validate_flow_ok():
    flow = {"steps": [
        {"action": "open", "url": "/"},
        {"action": "capture", "selector": "#t", "var": "tok"},
        {"action": "navigate", "url": "/x/{{tok}}"},
    ]}
    assert validate_flow(flow) == []


def test_validate_unknown_action():
    errors = validate_flow({"steps": [{"action": "frobnicate"}]})
    assert any("unknown action" in e for e in errors)


def test_validate_missing_required_field():
    errors = validate_flow({"steps": [{"action": "click"}]})  # needs selector
    assert any("missing required field 'selector'" in e for e in errors)


def test_validate_unresolved_variable():
    errors = validate_flow({"steps": [{"action": "navigate", "url": "/x/{{missing}}"}]})
    assert any("before it is captured" in e for e in errors)


def test_validate_ignores_comment_field_vars():
    # {{tok}} appears only in a doc comment -> not treated as a live reference.
    flow = {"steps": [{"action": "open", "url": "/", "comment": "later use {{tok}}"}]}
    assert validate_flow(flow) == []


def test_validate_ignores_script_field_vars():
    # {{column}} inside a script is literal app-template content, not a WAT var.
    flow = {"steps": [{"action": "eval_js", "script": "el.value = 'the {{column}} data'"}]}
    assert validate_flow(flow) == []


def test_sleep_duration_alias_maps_to_seconds():
    step = canonicalize_step({"action": "sleep", "duration": 500})
    assert step["seconds"] == 0.5
    assert validate_flow({"steps": [step]}) == []


def test_load_flow_rejects_bad_name(tmp_path):
    bad = tmp_path / "not_a_flow.json"
    bad.write_text(json.dumps({"steps": []}))
    with pytest.raises(SchemaError):
        load_flow(bad)


def test_load_flow_requires_steps(tmp_path):
    f = tmp_path / "fl_empty.json"
    f.write_text(json.dumps({"name": "x", "steps": []}))
    with pytest.raises(SchemaError):
        load_flow(f)


def test_flow_labels_string_and_list():
    assert flow_labels({"label": "a/b"}) == ["a/b"]
    assert flow_labels({"label": ["a", "b"]}) == ["a", "b"]
    assert flow_labels({}) == []


# -- `use` sub-flow composition ---------------------------------------------

def _write(dir_path, name, steps, **top):
    import json as _json

    p = dir_path / name
    p.write_text(_json.dumps({"steps": steps, **top}))
    return p


def test_use_inlines_subflow_steps(tmp_path):
    _write(tmp_path, "fl_frag.json", [{"action": "click", "selector": "#a"}])
    parent = _write(tmp_path, "fl_parent.json", [
        {"action": "open", "url": "/"},
        {"use": "fl_frag.json"},
        {"action": "assert_element", "selector": "#done"},
    ])
    flow = load_flow(parent)
    assert [s["action"] for s in flow["steps"]] == ["open", "click", "assert_element"]


def test_nested_use_expands_recursively(tmp_path):
    _write(tmp_path, "fl_inner.json", [{"action": "reload"}])
    _write(tmp_path, "fl_mid.json", [{"action": "back"}, {"use": "fl_inner.json"}])
    parent = _write(tmp_path, "fl_top.json", [{"use": "fl_mid.json"}, {"action": "forward"}])
    assert [s["action"] for s in load_flow(parent)["steps"]] == ["back", "reload", "forward"]


def test_use_cycle_detected(tmp_path):
    _write(tmp_path, "fl_a.json", [{"use": "fl_b.json"}])
    _write(tmp_path, "fl_b.json", [{"use": "fl_a.json"}])
    with pytest.raises(SchemaError, match="cycle"):
        load_flow(tmp_path / "fl_a.json")


def test_use_missing_file_errors(tmp_path):
    parent = _write(tmp_path, "fl_parent.json", [{"use": "fl_nope.json"}])
    with pytest.raises(SchemaError):
        load_flow(parent)


def test_validate_sees_expanded_flow(tmp_path):
    # A var captured in the parent and referenced inside the fragment must validate
    # clean once inlined (produced-before-used holds across the merge).
    _write(tmp_path, "fl_use_var.json", [{"action": "navigate", "url": "/x/{{tok}}"}])
    parent = _write(tmp_path, "fl_cap.json", [
        {"action": "capture", "selector": "#t", "var": "tok"},
        {"use": "fl_use_var.json"},
    ])
    assert validate_flow(load_flow(parent)) == []
