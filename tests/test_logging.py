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


def test_prune_never_deletes_own_run_dir(tmp_path):
    # Regression for issue #3: run_id leads with the flow stem, so a NAME sort orders
    # runs alphabetically by flow -- not by recency. A run with an early-sorting stem
    # ("fl_aaa") whose runs/ dir already holds >= keep_runs later-sorting dirs would be
    # classified as "old" and have its own just-created dir deleted -> FileNotFoundError.
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    # Pre-existing runs whose names sort AFTER the current one but are OLDER on disk.
    for i in range(3):
        (runs_dir / f"fl_zzz_{i}-20260101T000000Z-1").mkdir()

    log = RunLogger(app="test", log_dir=str(tmp_path), flow_stem="fl_aaa", echo=False, keep_runs=3)
    try:
        # The current run dir must survive pruning...
        assert log.dir.exists()
        # ...and its channels must still be writable (the bug surfaced as a write to a
        # deleted dir raising FileNotFoundError).
        log.wat("still alive")
    finally:
        log.close()
    assert (log.dir / "wat.log").exists()
    assert "still alive" in (log.dir / "wat.log").read_text()
