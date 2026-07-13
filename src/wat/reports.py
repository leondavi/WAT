"""Aggregate run reports for CI: JUnit XML and JSON.

Turns a list of :class:`~wat.runner.FlowResult` into a machine-readable artifact a CI
system can ingest (JUnit is understood by GitHub Actions, GitLab, Jenkins, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterable
from xml.etree import ElementTree as ET
from xml.dom import minidom

if TYPE_CHECKING:
    from .runner import FlowResult


def build_json(results: Iterable["FlowResult"]) -> str:
    """Serialize results as a JSON summary."""
    results = list(results)
    passed = sum(1 for r in results if r.returncode == 0)
    payload = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "flows": [
            {
                "name": r.name,
                "file": r.path.name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "source": r.source,
                "failed_step": r.failed_step,
                "message": r.message,
                "log_dir": str(r.log_dir) if r.log_dir else None,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)


def build_junit(results: Iterable["FlowResult"], suite_name: str = "wat") -> str:
    """Serialize results as a JUnit XML testsuite."""
    results = list(results)
    failures = sum(1 for r in results if r.returncode != 0)
    total_time = sum(r.duration_ms for r in results) / 1000.0

    suite = ET.Element("testsuite", {
        "name": suite_name,
        "tests": str(len(results)),
        "failures": str(failures),
        "errors": "0",
        "time": f"{total_time:.3f}",
    })
    for r in results:
        case = ET.SubElement(suite, "testcase", {
            "name": r.name,
            "classname": r.path.stem,
            "time": f"{r.duration_ms / 1000.0:.3f}",
        })
        if r.returncode != 0:
            msg = r.message or "flow failed"
            failure = ET.SubElement(case, "failure", {
                "message": msg,
                "type": r.source or "failure",
            })
            detail = [f"source: {r.source}", f"failed_step: {r.failed_step}", msg]
            if r.log_dir:
                detail.append(f"artifacts: {r.log_dir}")
            failure.text = "\n".join(str(d) for d in detail)

    raw = ET.tostring(suite, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def write_report(results: Iterable["FlowResult"], path: str | Path, fmt: str = "junit") -> Path:
    """Write a report to *path* in *fmt* ('junit' or 'json'). Returns the path."""
    results = list(results)
    content = build_json(results) if fmt == "json" else build_junit(results)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
