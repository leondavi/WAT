"""Runner result interpretation, incl. surfacing assert_js diagnostic payloads (issue #2)."""

from __future__ import annotations

from wat.runner import _interpret


def test_pass_values():
    assert _interpret(None, None) == (True, None)
    assert _interpret(True, None) == (True, None)
    assert _interpret(False, None) == (False, None)


def test_dict_pass_true_with_extras_has_no_reason():
    passed, reason = _interpret({"pass": True, "note": "fyi"}, None)
    assert passed is True and reason is None


def test_dict_failure_surfaces_extra_fields():
    passed, reason = _interpret({"pass": False, "why": "no textarea", "label": "count-nodes"}, None)
    assert passed is False
    assert "returned" in reason
    assert "no textarea" in reason and "count-nodes" in reason


def test_dict_failure_combines_reason_and_object():
    passed, reason = _interpret({"pass": False, "reason": "bad", "reply": "hi"}, None)
    assert passed is False
    assert reason.startswith("bad | returned ")
    assert "reply" in reason and "hi" in reason


def test_dict_failure_reason_only_is_clean():
    # no extra fields -> keep the clean reason, don't append a redundant object
    passed, reason = _interpret({"pass": False, "reason": "no element matched"}, None)
    assert passed is False and reason == "no element matched"


def test_dict_failure_payload_is_truncated():
    passed, reason = _interpret({"pass": False, "reply": "x" * 1000}, None)
    assert passed is False and len(reason) <= 410 and reason.endswith("...")


def test_error_takes_precedence():
    class E(Exception):
        reason = "boom"

    assert _interpret(None, E()) == (False, "boom")
