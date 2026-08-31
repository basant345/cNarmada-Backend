# -*- coding: utf-8 -*-
"""
auth_guard.py  --  server-side access control for gated data endpoints.

The download gate lives HERE, not in the frontend. Hiding a button in React
stops nobody: the browser can re-request any open endpoint directly. Every
rule below is enforced on the server, on every request.

Provides:
    require_iiti_user       decorator - rejects anyone without a valid session
    optional_user           decorator - attaches the user if present, never blocks
    current_user()          the authenticated user for this request, or None
    lookup_bearer_session() resolve the Authorization header directly
    domain_allowed(email)   institutional-domain check
    make_download_token()   short-lived signed URL token for <a href> downloads
    verify_download_token()
"""
import hashlib
import hmac
import os
import re
import sqlite3
import time
from datetime import datetime
from functools import wraps

from flask import g, jsonify, request

# Same database the OTP flow writes sessions into.
_DB_PATH = os.path.join(os.path.dirname(__file__), "routes", "auth.db")

# Fail closed. A missing secret must stop the app, never fall back to a
# published default, or every token in the wild becomes forgeable.
SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "AUTH_SECRET_KEY is not set. Refusing to start with a default secret. "
        "Set it in .env locally and in the host's environment in production."
    )

# Comma-separated, overridable without a code change.
ALLOWED_EMAIL_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "iiti.ac.in").split(",")
    if d.strip()
]

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

DOWNLOAD_TOKEN_TTL_SECONDS = 300


def domain_allowed(email: str) -> bool:
    """
    True when the address belongs to an allowed institutional domain.

    Matches the domain exactly, or as a subdomain of it, so that
    'cse.iiti.ac.in' passes while 'iiti.ac.in.attacker.com' does not.
    Comparing with a plain 'endswith("iiti.ac.in")' would accept both and
    is the usual way this check gets broken.
    """
    if not email or not _EMAIL_RE.match(email.strip()):
        return False
    domain = email.strip().lower().rsplit("@", 1)[1]
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS)


def _bearer_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def _lookup_session(token: str):
    """Resolve a bearer token to a live session row, or None."""
    if not token:
        return None
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT token, email, name, expires_at FROM auth_sessions WHERE token = ?",
            (token,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None

    try:
        if datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.utcnow():
            return None
    except (ValueError, TypeError):
        return None

    # Re-check the domain on every request rather than trusting the token.
    # If ALLOWED_EMAIL_DOMAINS is tightened later, sessions issued under the
    # old rule stop working immediately instead of outliving the change.
    if not domain_allowed(row["email"]):
        return None

    return {"email": row["email"], "name": row["name"]}


def lookup_bearer_session():
    """
    Resolve the request's Authorization header to a session, or None.
    Public helper for routes that must do their own check rather than use
    the decorator (the report download accepts a signed link as well).
    """
    return _lookup_session(_bearer_token())


def current_user():
    return getattr(g, "cnarmada_user", None)


def optional_user(fn):
    """Attach the user when one is present. Never blocks the request."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        g.cnarmada_user = _lookup_session(_bearer_token())
        return fn(*args, **kwargs)
    return wrapper


def require_iiti_user(fn):
    """Reject the request unless a valid institutional session is present."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _lookup_session(_bearer_token())
        if not user:
            g.cnarmada_user = None
            return jsonify({
                "error": "authentication_required",
                "message": "Sign in with your IIT Indore email address to download this dataset.",
                "allowed_domains": ALLOWED_EMAIL_DOMAINS,
            }), 401
        g.cnarmada_user = user
        return fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Signed download tokens
#
# A plain <a href="..."> cannot carry an Authorization header, so protected
# file links use a short-lived signed query parameter instead. The token is
# bound to one filename and one user, so it cannot be reused for a different
# file or shared usefully for long.
# ---------------------------------------------------------------------------
def make_download_token(email: str, filename: str) -> str:
    expires = int(time.time()) + DOWNLOAD_TOKEN_TTL_SECONDS
    payload = f"{email}|{filename}|{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{expires}.{sig}"


def verify_download_token(token: str, email: str, filename: str) -> bool:
    if not token or "." not in token:
        return False
    expires_str, sig = token.split(".", 1)
    try:
        expires = int(expires_str)
    except ValueError:
        return False
    if expires < time.time():
        return False
    payload = f"{email}|{filename}|{expires}"
    expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(expected, sig)
