"""Data-driven flows: the `matrix` top-level key (validation + case expansion)."""

from __future__ import annotations

import json

from wat.schema import flow_matrix, validate_flow
from wat.runner import _load_cases


# -- schema / validation -----------------------------------------------------

def test_flow_matrix_returns_rows_or_empty():
    assert flow_matrix({"matrix": [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]
    assert flow_matrix({}) == []
    assert flow_matrix({"matrix": "nope"}) == []  # malformed -> [] (validation reports it)


def test_matrix_vars_available_to_every_step():
    flow = {"matrix": [{"role": "admin", "landing": "/admin"}],
            "steps": [{"action": "assert_url_contains", "value": "{{landing}}"}]}
    assert validate_flow(flow) == []


def test_matrix_must_be_non_empty_list_of_objects():
    assert any("matrix" in e for e in validate_flow({"matrix": "x", "steps": [{"action": "reload"}]}))
    assert any("matrix" in e for e in validate_flow({"matrix": [], "steps": [{"action": "reload"}]}))


# -- runner case expansion (no browser) -------------------------------------

def _write(dir_path, name, payload):
    p = dir_path / name
    p.write_text(json.dumps(payload))
    return p


def test_load_cases_without_matrix_is_single_case(tmp_path):
    path = _write(tmp_path, "fl_plain.json", {"steps": [{"action": "reload"}]})
    cases = _load_cases(path)
    assert len(cases) == 1
    assert cases[0]["initial_store"] == {} and cases[0]["stem_suffix"] == ""
    assert cases[0]["case_label"] is None


def test_load_cases_expands_matrix_rows(tmp_path):
    path = _write(tmp_path, "fl_grid.json", {
        "matrix": [{"heading": "Alpha"}, {"heading": "Beta"}],
        "steps": [{"action": "assert_element_text", "selector": "#t", "value": "{{heading}}"}],
    })
    cases = _load_cases(path)
    assert [c["initial_store"] for c in cases] == [{"heading": "Alpha"}, {"heading": "Beta"}]
    assert [c["stem_suffix"] for c in cases] == [".case0", ".case1"]
    assert [c["case_label"] for c in cases] == ["heading=Alpha", "heading=Beta"]
