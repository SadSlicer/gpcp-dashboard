"""Public data API — routes to the active backend.

Two implementations exist:

- `data_sqlite`   : V15 local sqlite (default; same behavior as branch `va`)
- `data_postgres` : Supabase Postgres multi-tenant (used when SaaS mode is
                     active AND a user is authenticated)

Selection rule (at every attribute access):
    - if `supabase_client.is_saas_mode()` is True AND a user is logged in
      → route to `data_postgres`
    - else → route to `data_sqlite` (V15 fallback)

The public API is identical in both backends — `app.py`, `pro.py`,
`prices.py`, and `daily_update.py` just do `import data` and use
`data.foo()` without caring which backend is active.

How the dispatch works
----------------------
Python's PEP 562 module-level `__getattr__` is called whenever someone
accesses `data.something` that the dispatcher itself didn't define. We
forward the access to the active backend module. Function calls,
attribute reads, mutable globals (ASSETS, ISIN_BY_ASSET, …) all just work.

Important: `from data import X` is NOT supported in this design. All
call sites use `import data` then `data.X` — this is already the
convention in the codebase (verified for app.py, pro.py, prices.py,
daily_update.py before the refactor).
"""

from __future__ import annotations

import data_sqlite

# Cloud backend is optional — only loaded when needed (avoids a hard
# dependency on supabase-py for pure local dev).
_data_postgres = None
def _get_cloud():
    global _data_postgres
    if _data_postgres is None:
        import data_postgres  # noqa: WPS433
        _data_postgres = data_postgres
    return _data_postgres


def _active():
    """Decide which backend to use for the current request.

    Routing rule:
      - SaaS mode active (Supabase secrets present) AND a user is
        authenticated → cloud Postgres backend (`data_postgres`).
      - Otherwise → local sqlite backend (`data_sqlite`, V15 behavior).

    Any failure to determine SaaS state falls back safely to sqlite.
    """
    try:
        import supabase_client
        if not supabase_client.is_saas_mode():
            return data_sqlite
    except Exception:
        return data_sqlite
    try:
        import streamlit as st
        user = st.session_state.get("__saas_user")
        if user and user.get("id"):
            return _get_cloud()
    except Exception:
        pass
    return data_sqlite


def __getattr__(name: str):
    """Forward every attribute access to the active backend."""
    return getattr(_active(), name)


# Expose a tiny dispatcher introspection helper for diagnostics.
def _active_backend_name() -> str:
    mod = _active()
    return "data_postgres" if mod is not data_sqlite else "data_sqlite"
