#!/usr/bin/env bash
# Thin POSIX wrapper (macOS / Linux) around install.py.
# It only locates a Python 3.10+ interpreter and hands off; all real logic lives
# in install.py so there is a single, testable source of truth.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer python3, then python; require >= 3.10.
py=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
      py="$candidate"
      break
    fi
  fi
done

if [ -z "$py" ]; then
  echo "[wat-install] ❌ No Python 3.10+ found on PATH. Install one and retry." >&2
  exit 1
fi

exec "$py" "$here/install.py" "$@"
