"""SQL / side-effect extension: seed and inspect app state from a flow.

Opt in with ``extensions = ["sql"]`` (installs the ``sql`` extra for psycopg2).
These actions let a flow set up or clean up database fixtures and run app tasks:

  * ``sql``        — run a query via psycopg2 against a DSN.
  * ``docker_sql`` — run a query via ``docker exec <container> psql``.
  * ``mix_run``    — run ``mix run -e <expr>`` in the app root.

Connection details come from the step (``dsn``/``container``/``db``/``user``) with
env-var fallbacks, so nothing app-specific is hard-coded in the framework.
"""

from __future__ import annotations

import os
import subprocess

from ..context import StepContext
from ..errors import StepFailure, SOURCE_APP
from ..registry import register_action


@register_action("sql", required=("query",), group="sql",
                 description="Run a SQL query via psycopg2; optionally store the result.")
def sql(ctx: StepContext) -> None:
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover - depends on the [sql] extra
        raise StepFailure("action 'sql' needs the [sql] extra (psycopg2)", source=SOURCE_APP) from exc

    dsn = ctx.field("dsn") or os.environ.get("WAT_DB_DSN", "postgresql://postgres:postgres@localhost/postgres")
    query = ctx.field("query", required=True)
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall() if cur.description else []
    finally:
        conn.close()
    ctx.log.wat(f"sql affected/returned {len(rows)} row(s)")
    if ctx.step.get("store_as"):
        ctx.store[ctx.step["store_as"]] = rows


@register_action("docker_sql", required=("query",), group="sql",
                 description="Run a SQL query via `docker exec <container> psql`.")
def docker_sql(ctx: StepContext) -> None:
    container = ctx.field("container") or os.environ.get("WAT_DB_CONTAINER", "db")
    db = ctx.field("db") or os.environ.get("WAT_DB_NAME", "postgres")
    user = ctx.field("user") or os.environ.get("WAT_DB_USER", "postgres")
    query = ctx.field("query", required=True)
    cmd = ["docker", "exec", container, "psql", "-U", user, "-d", db, "-t", "-A", "-c", query]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise StepFailure(f"docker_sql failed: {proc.stderr.strip()}", source=SOURCE_APP)
    ctx.log.app(f"docker_sql -> {proc.stdout.strip()[:200]}")
    if ctx.step.get("store_as"):
        ctx.store[ctx.step["store_as"]] = proc.stdout.strip()


@register_action("mix_run", required=("expr",), group="sql",
                 description="Run `mix run -e <expr>` in the app root.")
def mix_run(ctx: StepContext) -> None:
    expr = ctx.field("expr", required=True)
    proc = subprocess.run(["mix", "run", "-e", expr], cwd=ctx.config.root,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise StepFailure(f"mix_run failed: {proc.stderr.strip()}", source=SOURCE_APP)
    ctx.log.app(f"mix_run -> {proc.stdout.strip()[:200]}")
