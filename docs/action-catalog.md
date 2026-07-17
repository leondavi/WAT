# WAT action & assertion catalog

_Generated from the registry (core + bundled extensions). Run `wat --print-actions` for your app's live set including plugins._

## Navigation & waiting

| action | required | description |
|---|---|---|
| `back` | — | Browser back. |
| `forward` | — | Browser forward. |
| `navigate` _(alias: goto)_ | `url` | Mid-flow navigation to base_url + url. |
| `open` | `url` | Navigate to base_url + url (typically step 0). |
| `reload` | — | Reload the current page. |
| `scroll_to` | `selector` | Scroll the element into view. |
| `sleep` | `seconds` | Fixed wait in seconds (discouraged; prefer wait_for/assert). |
| `wait_for` | `selector` | Wait for the selector to reach a state (default visible). |
| `wait_for_load_state` | — | Wait for load state: load | domcontentloaded | networkidle. |
| `wait_for_text` | `selector`, `value` | Wait until the selector's text contains value. |
| `wait_for_url` | `value` | Wait until the current URL contains value. |

## Interaction

| action | required | description |
|---|---|---|
| `blur` | `selector` | Blur the element. |
| `check` | `selector` | Check a checkbox/radio. |
| `clear` | `selector` | Clear an input. |
| `click` | `selector` | Click the first matching element. |
| `dblclick` | `selector` | Double-click the element. |
| `focus` | `selector` | Focus the element. |
| `hover` | `selector` | Hover the element. |
| `press` | `selector` | Press a key or chord (e.g. 'Enter', 'Control+A') on the element. |
| `real_drag` _(alias: drag_and_drop)_ | `from_selector`, `to_selector` | Mouse-driven drag from one element to another. |
| `right_click` | `selector` | Right-click (context menu) the element. |
| `select_option` | `selector` | Choose a <select> option by value or label. |
| `set_file` _(alias: upload)_ | `selector` | Upload file(s) to a file input; paths are repo-relative. |
| `submit` | `selector` | Submit the form containing the selector. |
| `type` _(alias: fill)_ | `selector`, `value` | Fill an input with value (fires input events; LiveView-friendly). |
| `uncheck` | `selector` | Uncheck a checkbox. |

## Browser & session

| action | required | description |
|---|---|---|
| `clear_cookies` | — | Clear all cookies. |
| `clear_storage` | — | Clear local + session storage. |
| `emulate` | — | Emulate offline / geolocation / color-scheme / media. |
| `get_storage` | `name` | Read a storage key into the capture store (needs store_as). |
| `handle_dialog` | — | Auto-handle the next dialog: accept | dismiss (with optional prompt text). |
| `save_storage_state` _(alias: save_auth)_ | — | Persist cookies + localStorage to a file for reuse via config.storage_state. |
| `set_cookie` | `name`, `value` | Add a cookie scoped to the base URL. |
| `set_storage` | `name`, `value` | Set a local/session storage key (area defaults to local). |
| `set_viewport` | `width`, `height` | Resize the viewport. |

## Network

| action | required | description |
|---|---|---|
| `assert_response` | `url`, `status` | Wait for a matching response and assert its status. |
| `mock` _(alias: route)_ | `url` | Stub responses for URLs matching a glob/regex pattern. |
| `unroute` | `url` | Remove a previously installed mock/route. |
| `wait_for_request` | `url` | Wait for a request whose URL matches the pattern. |
| `wait_for_response` | `url` | Wait for a response whose URL matches the pattern. |

## Capture & artifacts

| action | required | description |
|---|---|---|
| `capture` | `selector` | Read an element attribute/value/text into the capture store. |
| `pdf` | — | Save the page as a PDF (chromium only). |
| `save_store` | — | Dump the capture store to an artifact JSON file. |
| `screenshot` | — | Save a PNG to the artifacts dir. |
| `snapshot` | — | Save the accessibility tree snapshot as JSON. |
| `tail_log` | — | Read the tail of a log file into the [APP] channel. |

## Scripting

| action | required | description |
|---|---|---|
| `eval_js` _(alias: evaluate)_ | `script` | Evaluate JS (Promise-aware); result captured but not asserted. |
| `exec` | `command` | Run a guarded shell command (opt-in via config.allow_exec). |

## Assertions

| action | required | description |
|---|---|---|
| `assert_attribute` | `selector`, `attr` | Element attribute equals/contains value. |
| `assert_checked` | `selector` | Checkbox/radio is checked. |
| `assert_console_match` | `pattern` | Some console message matches a regex. |
| `assert_disabled` | `selector` | Element is disabled. |
| `assert_element` | `selector` | At least one element matches. |
| `assert_element_count` | `selector`, `count` | Exactly N elements match. |
| `assert_element_text` | `selector`, `value` | Element text contains value. |
| `assert_enabled` | `selector` | Element is enabled. |
| `assert_hidden` | `selector` | Element is absent or hidden. |
| `assert_js` | `script` | Evaluate JS; pass on truthy or {pass:true}. Promise-aware. |
| `assert_no_console_errors` | — | No console.error / uncaught page errors so far. |
| `assert_no_element` | `selector` | No element matches. |
| `assert_no_network_errors` | — | No 4xx/5xx or failed requests so far. |
| `assert_text_contains` | `value` | Page body text contains value. |
| `assert_text_matches` | `pattern` | Page body text matches a regex. |
| `assert_text_not_contains` | `value` | Page body text does not contain value. |
| `assert_title` | `value` | Page title contains value. |
| `assert_url_contains` | `value` | Current URL contains value. |
| `assert_url_matches` | `pattern` | Current URL matches a regex. |
| `assert_url_not_contains` | `value` | Current URL does not contain value. |
| `assert_value` | `selector`, `value` | Input value equals value. |
| `assert_visible` | `selector` | Element is visible. |

## LiveView (ext)

| action | required | description |
|---|---|---|
| `phx_push` | `event` | Push a LiveView event over the joined lv: channel. |
| `wait_for_lv` | — | Wait until Phoenix LiveView has settled (no pending events). |

## SQL / side-effects (ext)

| action | required | description |
|---|---|---|
| `docker_sql` | `query` | Run a SQL query via `docker exec <container> psql`. |
| `mix_run` | `expr` | Run `mix run -e <expr>` in the app root. |
| `sql` | `query` | Run a SQL query via psycopg2; optionally store the result. |

## Auth (ext)

| action | required | description |
|---|---|---|
| `logout` | — | Clear cookies and navigate to the configured logout/login path. |

