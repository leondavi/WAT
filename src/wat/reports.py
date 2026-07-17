"""Aggregate run reports: JUnit XML (CI), JSON (tooling), and a self-contained HTML page.

Turns a list of :class:`~wat.runner.FlowResult` into a shareable artifact. JUnit is
understood by GitHub Actions / GitLab / Jenkins; the HTML report is a single file (inline
CSS, embedded failure screenshots) a human can open with no server or network.
"""

from __future__ import annotations

import base64
import html
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


# ---------------------------------------------------------------------------
# HTML — a self-contained, human-facing report
# ---------------------------------------------------------------------------

# Inline styles so the report is one portable file (works as a CI artifact, offline,
# and in either light or dark theme).
_HTML_CSS = """
:root { color-scheme: light dark; --pass:#1a7f37; --fail:#cf222e; --muted:#57606a; --line:#d0d7de; --bg:#fff; --fg:#1f2328; }
@media (prefers-color-scheme: dark) { :root { --muted:#8b949e; --line:#30363d; --bg:#0d1117; --fg:#e6edf3; } }
* { box-sizing: border-box; } body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--fg); }
.wrap { max-width:1000px; margin:0 auto; padding:24px; }
h1 { font-size:20px; margin:0 0 4px; } .sub { color:var(--muted); margin:0 0 20px; }
.tiles { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
.tile { border:1px solid var(--line); border-radius:8px; padding:12px 16px; min-width:96px; }
.tile .n { font-size:22px; font-weight:700; } .tile .l { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
table { width:100%; border-collapse:collapse; } th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.badge { font-weight:700; font-size:12px; } .pass{color:var(--pass);} .fail{color:var(--fail);} .muted{color:var(--muted);}
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
details { margin-top:6px; } summary { cursor:pointer; color:var(--muted); }
img.shot { max-width:100%; border:1px solid var(--line); border-radius:6px; margin-top:8px; }
""".strip()


def _data_uri(png: Path, max_bytes: int = 3_000_000) -> str | None:
    """Return a base64 data URI for *png*, or None if absent/too large to embed."""
    try:
        raw = png.read_bytes()
    except OSError:
        return None
    if len(raw) > max_bytes:
        return None
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def build_html(results: Iterable["FlowResult"], suite_name: str = "wat") -> str:
    """Render results as a single self-contained HTML page (inline CSS + screenshots)."""
    results = list(results)
    passed = sum(1 for r in results if r.returncode == 0)
    failed = len(results) - passed
    total_time = sum(r.duration_ms for r in results) / 1000.0

    rows = []
    for r in results:
        status_cls = "pass" if r.returncode == 0 else "fail"
        status_txt = "PASS" if r.returncode == 0 else "FAIL"
        detail = ""
        if r.returncode != 0:
            bits = []
            if r.source:
                bits.append(f"<div><span class='muted'>source</span> <span class='mono'>{html.escape(r.source)}</span></div>")
            if r.failed_step is not None:
                bits.append(f"<div><span class='muted'>failed step</span> <span class='mono'>{r.failed_step}</span></div>")
            if r.message:
                bits.append(f"<div><span class='muted'>message</span> <span class='mono'>{html.escape(str(r.message))}</span></div>")
            if r.log_dir:
                bits.append(f"<div><span class='muted'>artifacts</span> <span class='mono'>{html.escape(str(r.log_dir))}</span></div>")
                shot = next(Path(r.log_dir).glob("*.failed.png"), None)
                uri = _data_uri(shot) if shot else None
                if uri:
                    bits.append(f"<img class='shot' alt='failure screenshot' src='{uri}'>")
            detail = ("<details open><summary>failure detail</summary>" + "".join(bits) + "</details>")
        rows.append(
            f"<tr><td><span class='badge {status_cls}'>{status_txt}</span></td>"
            f"<td>{html.escape(r.name)}<br><span class='mono muted'>{html.escape(r.path.name)}</span>{detail}</td>"
            f"<td class='mono'>{r.duration_ms} ms</td></tr>"
        )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>WAT report - {html.escape(suite_name)}</title><style>{_HTML_CSS}</style></head><body><div class='wrap'>"
        f"<h1>WAT report</h1><p class='sub'>{html.escape(suite_name)} - {len(results)} flow(s), {total_time:.2f}s</p>"
        "<div class='tiles'>"
        f"<div class='tile'><div class='n'>{len(results)}</div><div class='l'>total</div></div>"
        f"<div class='tile'><div class='n pass'>{passed}</div><div class='l'>passed</div></div>"
        f"<div class='tile'><div class='n fail'>{failed}</div><div class='l'>failed</div></div>"
        "</div>"
        "<table><thead><tr><th>status</th><th>flow</th><th>duration</th></tr></thead><tbody>"
        + "".join(rows) +
        "</tbody></table></div></body></html>"
    )


def write_report(results: Iterable["FlowResult"], path: str | Path, fmt: str = "junit") -> Path:
    """Write a report to *path* in *fmt* ('junit', 'json', or 'html'). Returns the path."""
    results = list(results)
    builders = {"json": build_json, "html": build_html, "junit": build_junit}
    content = builders.get(fmt, build_junit)(results)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
