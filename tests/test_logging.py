"""RunLogger: per-run directory, source tags, channel separation, run.json."""

from __future__ import annotations

from wat.logging import RunLogger


def test_channels_write_tagged_lines(tmp_path):
    with RunLogger(app="test", log_dir=str(tmp_path), flow_stem="fl_x", echo=False) as log:
        log.wat("engine message")
        log.browser("console.error: boom")
        log.app("server line")
        log.step({"index": 0, "action": "open", "status": "ok", "duration_ms": 3})
        run_dir = log.dir

    wat_log = (run_dir / "wat.log").read_text()
    browser_log = (run_dir / "browser.log").read_text()
    app_log = (run_dir / "app.log").read_text()

    assert "[WAT] engine message" in wat_log
    assert "[BROWSER] console.error: boom" in browser_log
    assert "[APP] server line" in app_log
    # channels are separated: the browser line is NOT in wat.log
    assert "boom" not in wat_log
    assert (run_dir / "steps.jsonl").read_text().strip().startswith("{")


def test_run_json_written(tmp_path):
    with RunLogger(app="test", log_dir=str(tmp_path), flow_stem="fl_x", echo=False) as log:
        path = log.write_json("run.json", {"result": "pass"})
    assert path.exists()
    assert '"result": "pass"' in path.read_text()


def test_prune_keeps_recent_runs(tmp_path):
    stems = [f"fl_{i:02d}" for i in range(5)]
    for s in stems:
        RunLogger(app="test", log_dir=str(tmp_path), flow_stem=s, echo=False, keep_runs=3).close()
    runs = sorted((tmp_path / "runs").iterdir())
    assert len(runs) <= 3
