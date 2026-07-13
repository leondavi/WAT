"""Aggregate report generation (JUnit XML + JSON) from FlowResults."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from wat.runner import FlowResult
from wat.reports import build_json, build_junit, write_report


def _results():
    return [
        FlowResult(path=Path("fl_a.json"), name="A", returncode=0, status="pass", duration_ms=120),
        FlowResult(path=Path("fl_b.json"), name="B", returncode=1, status="fail", duration_ms=300,
                   source="app", failed_step=4, message="element not found"),
    ]


def test_build_json_counts_and_flows():
    data = json.loads(build_json(_results()))
    assert data["total"] == 2 and data["passed"] == 1 and data["failed"] == 1
    b = next(f for f in data["flows"] if f["name"] == "B")
    assert b["status"] == "fail" and b["source"] == "app" and b["failed_step"] == 4


def test_build_junit_is_valid_xml_with_failure():
    xml = build_junit(_results())
    root = ET.fromstring(xml)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "2" and root.attrib["failures"] == "1"
    cases = root.findall("testcase")
    assert len(cases) == 2
    failed = [c for c in cases if c.find("failure") is not None]
    assert len(failed) == 1
    assert "element not found" in failed[0].find("failure").attrib["message"]


def test_write_report_junit_and_json(tmp_path):
    p1 = write_report(_results(), tmp_path / "out" / "r.xml", "junit")
    p2 = write_report(_results(), tmp_path / "r.json", "json")
    assert p1.exists() and "<testsuite" in p1.read_text()
    assert p2.exists() and json.loads(p2.read_text())["total"] == 2
