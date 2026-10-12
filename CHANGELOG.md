# Changelog

All notable changes to WAT are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and WAT adheres to
[Semantic Versioning](https://semver.org/): from 1.0.0 on, the flow schema in
`CONTRACT.md`, the CLI flags, and the public plugin API (`wat.register_action`,
`register_hook`, `login_provider`, `reset_hook`, `StepContext`) are stable within a
major version.

## [1.0.1] - 2026-10-12

### Added
- `--force-base-url` (config `base_url_override = true`, env `WAT_BASE_URL_OVERRIDE=1`):
  the configured `base_url` wins over a flow's own `base_url` key, so flows that record
  a dev address can run against another server (CI port, worktree, staging) without
  rewriting them. Off by default; `wat --doctor` reports which base URL wins (#13).

### Fixed
- The flow start log line now shows the base URL the flow actually runs against.

## [1.0.0] - 2026-10-12

First stable release.

### Added
- Shared per-app JS helpers: config `helpers = "flows/helpers.js"` is injected into
  every page via `add_init_script` and checked by `--validate-only` / `--doctor` (#7).
- Reset-hook outcomes: a `@reset_hook` can report a skip (`False` or
  `{"pass": false, "reason": ...}`); a skipped reset becomes a flow WARNING in
  `run.json`, the `--all` summary, and JUnit/JSON/HTML reports. New `reset_required`
  flow key / config default fails the flow instead (#8).
- `wat.ext.liveview.wait_for_join` (retrying, `reset_join_timeout_ms`,
  `reset_join_attempts`) and `push_event` helpers (#8).
- `visual_require_baseline` option so CI fails on a missing visual baseline.
- `wat --version`.
- CI: Python 3.10 in the test matrix and a negative-control flow that must fail.
- README rewrite (motivation, architecture, extension guide) and LICENSE file.

### Fixed
- `retry`, `optional`, and `soft` now apply to Playwright errors such as locator
  timeouts, not only to failed assertions.
- A throwing `if` / `skip_if` predicate fails the step (`flow_authoring`) instead of
  silently skipping it.
- `assert_js` / dict results with `pass` of `null`, `0`, or `""` now fail.
- `after_flow` hooks are run (on pass and fail).
- Ctrl+C stops a run instead of being recorded as one failed flow.
- `--all`: a malformed flow is reported as a failed result instead of aborting the run
  without a report; `--workers N --fail-fast` starts no new flows after a failure.
- Run-dir pruning no longer deletes artifacts from the current invocation.
- `assert_attribute` without `value` asserts the attribute is present.
- Recorder never writes typed passwords into flows; live step logging masks
  credential-like values.
- Python 3.10: `wat.toml` / `[tool.wat]` were silently ignored (now uses `tomli`).

### Changed
- Live step announcements use ASCII `->` instead of a Unicode arrow.

## [0.1.0]

Initial development version.

[1.0.1]: https://github.com/leondavi/WAT/releases/tag/v1.0.1
[1.0.0]: https://github.com/leondavi/WAT/releases/tag/v1.0.0
