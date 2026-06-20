"""Supabase connection helper.

Reads SUPABASE_URL + SUPABASE_KEY from env / Streamlit secrets / .env.
Returns a single Client singleton so we don't open a new connection per
Streamlit rerun.

The same module exposes a `pg_connect()` helper for raw Postgres access
(used by the heavy data.py paths that need server-side SQL rather than
the REST-style PostgREST client).
"""

from __future__ import annotations

import os
from functools import lru_cache

try:
    from dotenv import load_dotenv
    load_dotenv()                       # pulls .env into env if present
except Exception:
    pass


def _secret(key: str, default: str | None = None) -> str | None:
    """Get a secret from Streamlit st.secrets, falling back to env var.

    Streamlit Cloud injects secrets via `st.secrets`; local dev uses .env.
    """
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:                                  # type: ignore[attr-defined]
            return st.secrets[key]                             # type: ignore[index]
    except Exception:
        pass
    return default


def supabase_url() -> str:
    url = _secret("SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL missing — set it in .env (local) or "
                            "Streamlit Cloud secrets (production).")
    return url


def supabase_anon_key() -> str:
    key = _secret("SUPABASE_ANON_KEY")
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY missing — set it in .env / "
                            "Streamlit Cloud secrets.")
    return key


def access_code() -> str:
    """The global gate code — admin rotates this in Streamlit Cloud secrets."""
    code = _secret("ACCESS_CODE")
    if not code:
        raise RuntimeError("ACCESS_CODE missing — set it in .env / "
                            "Streamlit Cloud secrets.")
    return code


def is_saas_mode() -> bool:
    """True iff every required SaaS secret is present.

    Used by app.py to decide whether to gate the dashboard behind the
    access-code + login flow, or to run in pure local mode (V15 behavior).
    """
    try:
        supabase_url()
        supabase_anon_key()
        access_code()
        return True
    except RuntimeError:
        return False


@lru_cache(maxsize=1)
def get_client():
    """Cached ANON client — for gate/auth operations only (no user data).

    WARNING: this is a single shared instance. Never use it for per-user
    data reads/writes: it has no authenticated session, so Row-Level
    Security (every policy is `user_id = auth.uid()`) would see a NULL uid
    and return zero rows. Data access must go through `get_user_client()`,
    which carries the logged-in user's JWT. Kept for backward compat.
    """
    from supabase import create_client
    return create_client(supabase_url(), supabase_anon_key())


def new_anon_client():
    """A FRESH anon client (not cached). Used for sign-in / sign-up / refresh
    so concurrent logins in the same Streamlit process never share a mutable
    auth session (which would risk one user's token leaking into another)."""
    from supabase import create_client
    return create_client(supabase_url(), supabase_anon_key())


@lru_cache(maxsize=128)
def _authed_client(access_token: str):
    """A client whose PostgREST calls carry `access_token` as the bearer JWT.

    Cached per access-token so (a) each user gets an isolated client object —
    no cross-tenant header races in the shared Streamlit process — and (b) we
    don't rebuild httpx sessions on every Streamlit rerun. When a token is
    refreshed the new token produces a new cache entry; old ones age out.

    The `apikey` header stays the anon key (Supabase requires it); only the
    `Authorization: Bearer` header is swapped to the user JWT, so RLS sees the
    real `auth.uid()`.
    """
    from supabase import create_client
    c = create_client(supabase_url(), supabase_anon_key())
    c.postgrest.auth(access_token)
    return c


def get_user_client():
    """Return a Supabase client scoped to the CURRENT authenticated user.

    Reads the JWT cached by `auth.require_auth()` in
    `st.session_state["__saas_user"]["_access_token"]`. Every `.table()` call
    on the returned client carries that JWT, so RLS isolates the user's rows
    server-side. Raises if called outside an authenticated session.
    """
    import streamlit as st
    user = st.session_state.get("__saas_user") or {}
    token = user.get("_access_token")
    if not token:
        raise RuntimeError(
            "No authenticated Supabase session — get_user_client() called "
            "before login. The cloud data backend requires require_auth() first."
        )
    return _authed_client(token)


def pg_connect():
    """Direct Postgres connection for heavy bulk operations.

    Supabase exposes the Postgres host at <project>.supabase.co with the
    `postgres` user. We need the DB password (different from the API key).
    """
    import psycopg2
    pw = _secret("SUPABASE_DB_PASSWORD")
    host = _secret("SUPABASE_DB_HOST")    # e.g. db.<ref>.supabase.co
    if not (pw and host):
        raise RuntimeError("SUPABASE_DB_HOST + SUPABASE_DB_PASSWORD required "
                            "for raw Postgres connections.")
    return psycopg2.connect(
        host=host, port=5432, dbname="postgres",
        user="postgres", password=pw, sslmode="require",
    )
