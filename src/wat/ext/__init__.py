"""Bundled, opt-in WAT extensions.

Extensions are loaded by name via config ``extensions = ["liveview", "sql"]`` (see
:mod:`wat.plugins`). Each module registers extra actions/hooks on import. They are
reusable across apps that share a stack (e.g. any Phoenix LiveView app) but are not
part of the always-on core, so a plain website never pays for them.
"""
