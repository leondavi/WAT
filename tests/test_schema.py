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
