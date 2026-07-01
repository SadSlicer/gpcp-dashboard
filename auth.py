"""Auth UI for the SaaS deployment.

Flow on each visit:
  1.  Visitor lands → Sign in / Sign up form (Supabase Auth, email + password)
  2.  Logged in → main dashboard runs (st.session_state.user_id is set)

(The old global "Code d'accès" gate was removed — per-account login alone now
guards access, and Supabase RLS isolates each user's data.)

Public API:
  require_auth() — call at the very top of app.py. Returns the
                   authenticated user dict when access is granted; otherwise
                   renders the gate / login UI and calls `st.stop()`.

Designed so app.py only needs:

    import auth
    user = auth.require_auth()       # blocks until logged in
    # ... rest of dashboard (data.py reads use user["id"])
"""

from __future__ import annotations

import streamlit as st

import supabase_client


# Streamlit session-state keys (avoid collisions with the rest of the app)
_SK_GATE_OK   = "__saas_gate_passed"
_SK_USER      = "__saas_user"            # dict {id, email, is_admin}
_SK_MODE      = "__saas_auth_mode"       # "signin" | "signup"


# ----------------------------------------------------------------------
# Login / Signup (Supabase Auth)
# ----------------------------------------------------------------------

def _render_auth_form():
    """Sign in / Sign up form once the gate has been passed."""
    st.set_page_config(
        page_title="GPCP — Connexion",
        page_icon="●",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    if _SK_MODE not in st.session_state:
        st.session_state[_SK_MODE] = "signin"
    mode = st.session_state[_SK_MODE]

    st.markdown(
        """
        <div style="text-align:center; padding:60px 0 20px">
          <div style="font-size:34px; font-weight:700; letter-spacing:-0.02em">
            GPCP Portfolio Terminal
          </div>
          <div style="color:#7A7D85; font-size:13px; margin-top:8px">
            Sign in to access your portfolios
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_signin, tab_signup = st.tabs(["Sign in", "Create an account"])

    # Fresh anon client per attempt — never share a mutable auth session
    # between concurrent users in the same Streamlit process.
    sb = supabase_client.new_anon_client()

    with tab_signin:
        email = st.text_input("Email", key="__saas_signin_email")
        password = st.text_input("Password", type="password",
                                  key="__saas_signin_password")
        if st.button("Sign in", type="primary", width="stretch",
                      key="__saas_signin_btn"):
            try:
                resp = sb.auth.sign_in_with_password(
                    {"email": email.strip(), "password": password}
                )
                user = resp.user
                if user is None:
                    st.error("Invalid credentials.")
                else:
                    _record_user(user, resp.session)
                    st.rerun()
            except Exception as exc:
                st.error(f"Sign-in failed: {exc}")

    with tab_signup:
        email_s = st.text_input("Email", key="__saas_signup_email")
        password_s = st.text_input("Password (min. 8 characters)",
                                    type="password", key="__saas_signup_password")
        password_c = st.text_input("Confirm",
                                    type="password", key="__saas_signup_confirm")
        if st.button("Create my account", type="primary", width="stretch",
                      key="__saas_signup_btn"):
            if password_s != password_c:
                st.error("Passwords do not match.")
            elif len(password_s) < 8:
                st.error("8 characters minimum.")
            else:
                try:
                    resp = sb.auth.sign_up(
                        {"email": email_s.strip(), "password": password_s}
                    )
                    if resp.user is None or resp.session is None:
                        st.warning("Account created — check your inbox "
                                    "to confirm if verification is enabled.")
                    else:
                        _record_user(resp.user, resp.session)
                        st.success("Welcome! Signing you in…")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Sign-up failed: {exc}")

    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#7A7D85;font-size:13px;margin-bottom:8px'>"
        "Just want to take a look?</div>",
        unsafe_allow_html=True,
    )
    if st.button("👁  Explore the demo (read-only)", width="stretch",
                  key="__saas_demo_btn"):
        st.session_state["__demo_mode"] = True
        st.rerun()


def _record_user(supabase_user, session) -> None:
    """Cache the user info + JWT in session_state for the dashboard.

    The access/refresh tokens are what make the cloud data backend work:
    `data_postgres` reads them (via `supabase_client.get_user_client()`) so
    every query carries this user's JWT and RLS returns their rows. Without
    them the dashboard would render against an anon role and see nothing.
    """
    access_token = getattr(session, "access_token", None) if session else None
    refresh_token = getattr(session, "refresh_token", None) if session else None
    expires_at = getattr(session, "expires_at", None) if session else None

    # Read the profile row (auto-created by the trigger) using a client that
    # carries this user's JWT — otherwise RLS hides the row.
    is_admin = False
    if access_token:
        try:
            sb = supabase_client._authed_client(access_token)
            prof = (sb.table("app_user_profile")
                      .select("is_admin, display_name")
                      .eq("user_id", supabase_user.id).execute())
            if prof.data:
                is_admin = bool(prof.data[0].get("is_admin", False))
        except Exception:
            pass

    st.session_state[_SK_USER] = {
        "id": supabase_user.id,
        "email": supabase_user.email,
        "is_admin": is_admin,
        "_access_token": access_token,
        "_refresh_token": refresh_token,
        "_expires_at": expires_at,
    }


def _ensure_fresh_session() -> None:
    """Refresh the access token if it is expired (or within 60 s of expiry).

    Supabase access tokens last ~1 h. Streamlit reruns call this on every
    interaction, so an actively-used session never carries a stale token.
    If the refresh fails (revoked / very old refresh token) the user is
    bounced back to the login form.
    """
    import time
    user = st.session_state.get(_SK_USER)
    if not user:
        return
    refresh_token = user.get("_refresh_token")
    expires_at = user.get("_expires_at") or 0
    if not refresh_token:
        return
    if time.time() < float(expires_at) - 60:
        return  # still valid
    try:
        anon = supabase_client.new_anon_client()
        res = anon.auth.refresh_session(refresh_token)
        sess = getattr(res, "session", None)
        if sess and getattr(sess, "access_token", None):
            user["_access_token"] = sess.access_token
            user["_refresh_token"] = sess.refresh_token
            user["_expires_at"] = sess.expires_at
            st.session_state[_SK_USER] = user
        else:
            st.session_state.pop(_SK_USER, None)
    except Exception:
        # Refresh failed — force a clean re-login rather than silently
        # serving an anon (empty) dashboard.
        st.session_state.pop(_SK_USER, None)


# ----------------------------------------------------------------------
# Public API used by app.py
# ----------------------------------------------------------------------

def require_auth() -> dict:
    """Block-until-authenticated. Returns {id, email, is_admin}.

    The global access-code gate was removed — visitors land straight on the
    per-account sign in / sign up. Supabase Auth still isolates every user's
    data via RLS, so per-account login stays."""
    # Demo mode: no login — a synthetic read-only user (the data dispatcher
    # routes to the frozen demo backend).
    if st.session_state.get("__demo_mode"):
        return {"id": "demo", "email": "demo", "is_admin": False}
    if _SK_USER not in st.session_state:
        _render_auth_form()
        st.stop()
    # Keep the JWT fresh so cloud data reads never fall back to anon (empty).
    _ensure_fresh_session()
    if _SK_USER not in st.session_state:   # refresh failed → re-login
        _render_auth_form()
        st.stop()
    return st.session_state[_SK_USER]


def current_user() -> dict | None:
    return st.session_state.get(_SK_USER)


def sign_out() -> None:
    """Sign the user out and reset the gate."""
    try:
        supabase_client.get_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.pop(_SK_USER, None)
    st.session_state.pop(_SK_GATE_OK, None)
    st.rerun()
