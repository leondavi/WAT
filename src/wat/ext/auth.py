"""Authentication extension: a pluggable login provider + credential loading.

The ``login`` action is dispatched to whatever provider an app registers via
:func:`wat.login_provider`. This module ships:

  * :class:`Credential` + :func:`load_credentials` — read a dev-login CSV.
  * :func:`find_credential` — pick a credential by role / email / username / index.
  * :class:`PhoenixAuthProvider` — a ready-made login flow for a standard Phoenix
    ``/users/log_in`` form that apps can subclass or instantiate directly.

Example (in an app plugin)::

    from wat import login_provider
    from wat.ext.auth import PhoenixAuthProvider
    login_provider(PhoenixAuthProvider(credentials="QA/dev_login_credentials.csv").login)
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..context import StepContext
from ..errors import StepFailure, SOURCE_FLOW_AUTHORING
from ..registry import register_action


@dataclass
class Credential:
    """A single test login. ``roles`` holds the ``|``-split multi-role list."""

    email: str = ""
    password: str = ""
    username: str = ""
    role: str = ""
    roles: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


def load_credentials(path: str | Path) -> list[Credential]:
    """Load credentials from a CSV with headers like email,password,role,roles,username."""
    rows: list[Credential] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            roles_raw = (row.get("roles") or row.get("role") or "").strip()
            rows.append(Credential(
                email=(row.get("email") or "").strip(),
                password=(row.get("password") or "").strip(),
                username=(row.get("username") or "").strip(),
                role=(row.get("role") or "").strip(),
                roles=[r for r in roles_raw.split("|") if r],
                extra={k: v for k, v in row.items()
                       if k not in {"email", "password", "username", "role", "roles"}},
            ))
    return rows


def find_credential(creds: list[Credential], *, role: str | None = None, email: str | None = None,
                    username: str | None = None, index: int | None = None) -> Credential:
    """Select a credential. Explicit email/username win; else filter by role (primary
    role first), else fall back to *index* into the (filtered) list."""
    if email:
        matches = [c for c in creds if c.email == email]
    elif username:
        matches = [c for c in creds if c.username == username]
    elif role:
        primary = [c for c in creds if c.role == role]
        matches = primary or [c for c in creds if role in c.roles]
    else:
        matches = list(creds)
    if not matches:
        raise StepFailure(f"no credential matched role={role} email={email} username={username}",
                          source=SOURCE_FLOW_AUTHORING)
    return matches[index or 0]


class PhoenixAuthProvider:
    """Login flow for a conventional Phoenix ``/users/log_in`` form.

    Subclass and override the class attributes (or pass them in) to fit an app's
    routes and selectors. Register its :meth:`login` via ``wat.login_provider``.
    """

    login_path = "/users/log_in"
    email_selector = "input[name='user[email]']"
    password_selector = "input[name='user[password]']"
    submit_selector = "button[type='submit']"

    def __init__(self, credentials: str | Path | None = None):
        self._credentials_path = credentials
        self._cache: list[Credential] | None = None

    def credentials(self, ctx: StepContext) -> list[Credential]:
        if self._cache is None:
            path = self._credentials_path or ctx.config.credentials_source
            if not path:
                raise StepFailure("no credentials source configured for login",
                                  source=SOURCE_FLOW_AUTHORING)
            root = Path(ctx.config.root)
            self._cache = load_credentials(root / path if not Path(path).is_absolute() else path)
        return self._cache

    def login(self, ctx: StepContext) -> None:
        cred = find_credential(
            self.credentials(ctx),
            role=ctx.field("role"), email=ctx.field("email"),
            username=ctx.field("username"), index=ctx.step.get("index"),
        )
        ctx.page.goto(ctx.url(self.login_path))
        ctx.page.locator(self.email_selector).fill(cred.email)
        ctx.page.locator(self.password_selector).fill(cred.password)
        ctx.page.locator(self.submit_selector).click()
        ctx.state["user"] = cred.email
        ctx.log.wat(f"logged in as {cred.email}")


@register_action("logout", group="auth",
                 description="Clear cookies and navigate to the configured logout/login path.")
def logout(ctx: StepContext) -> None:
    ctx.browser_context.clear_cookies()
    path = ctx.step.get("path", "/users/log_in")
    ctx.page.goto(ctx.url(path))
    ctx.state.pop("user", None)
