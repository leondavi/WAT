"""Interpolation of {{var}} placeholders over the capture store."""

from __future__ import annotations

import pytest

from wat.errors import StepFailure
from wat.interpolate import interpolate, maybe_interpolate


def test_replaces_known_vars():
    assert interpolate("/user/{{id}}/x", {"id": "42"}) == "/user/42/x"


def test_multiple_vars():
    assert interpolate("{{a}}-{{b}}", {"a": "1", "b": "2"}) == "1-2"


def test_missing_var_raises_flow_authoring_error():
    with pytest.raises(StepFailure) as exc:
        interpolate("{{nope}}", {"id": "1"})
    assert exc.value.source == "flow_authoring"


def test_maybe_interpolate_passes_through_non_strings():
    assert maybe_interpolate(5, {}) == 5
    assert maybe_interpolate(["x"], {}) == ["x"]


def test_no_placeholder_is_identity():
    assert interpolate("plain", {}) == "plain"
