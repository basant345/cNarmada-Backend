"""
OTP-based authentication API for cNARMADA Data Download section.

Routes:
  POST /api/auth/send-otp    — Send a 6-digit OTP to the given email
  POST /api/auth/verify-otp  — Verify OTP, return a signed session token

OTP storage: SQLite (auth.db alongside visits.db).
OTP expiry:  8 minutes.
Email:       Resend HTTP API (works on Render free tier).
Token:       HMAC-SHA256 signed, 24-hour TTL, stored in auth.db for server-side invalidation.
"""

import os
import re
import hmac
import uuid
import json
import random
import hashlib
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ── DB path: same directory as visits.db ──────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), "auth.db")

# ── Config from environment (set in .env / Render env vars) ───────────────
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SECRET_KEY     = os.environ.get("AUTH_SECRET_KEY", "cnarmada-secret-change-in-prod-2025")

OTP_EXPIRY_MINUTES = 8
TOKEN_EXPIRY_HOURS = 24

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ── DB helpers ─────────────────────────────────────────────────────────────
def _get_conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS otp_store (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            otp        TEXT NOT NULL,
            name       TEXT,
            expires_at DATETIME NOT NULL,
            used       INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token      TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            name       TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        );
    """)
    conn.commit()
    return conn


def _clean_expired(conn):
    """Purge expired OTPs and sessions (housekeeping)."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM otp_store WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
    conn.commit()


# ── Token helpers ──────────────────────────────────────────────────────────
def _make_token(email: str) -> str:
    """Generate a random token signed with HMAC so it can't be forged."""
    raw = uuid.uuid4().hex
    sig = hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify_token_signature(token: str) -> bool:
    """Check the HMAC signature only — DB lookup still needed for expiry."""
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


# ── Email helper ───────────────────────────────────────────────────────────
def _send_otp_email(to_email: str, name: str, otp: str):
    """Send OTP via Resend HTTP API (works on Render free tier)."""
    display_name = name.strip() if name else "Researcher"

    if not RESEND_API_KEY:
        raise Exception("RESEND_API_KEY not configured")

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Inter',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:32px 0;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;border:1px solid #e2e8f0;
                    box-shadow:0 4px 24px rgba(0,0,0,0.07);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(90deg,#0e7490,#0369a1);
                     padding:28px 36px;text-align:center;">
            <div style="color:#ffffff;font-size:22px;font-weight:700;
                        letter-spacing:0.5px;">cNARMADA</div>
            <div style="color:#a5f3fc;font-size:12px;text-transform:uppercase;
                        letter-spacing:2px;margin-top:4px;">IIT Indore · Data Access</div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px;">
            <p style="color:#0f172a;font-size:17px;font-weight:600;margin:0 0 12px;">
              Hello, {display_name}!
            </p>
            <p style="color:#475569;font-size:15px;line-height:1.7;margin:0 0 28px;">
              Your one-time password (OTP) for accessing the cNARMADA Data Download
              section is:
            </p>

            <!-- OTP Box -->
            <div style="text-align:center;margin:0 0 28px;">
              <span style="display:inline-block;background:#f0f9ff;
                           border:2px solid #0e7490;border-radius:12px;
                           padding:16px 40px;font-size:38px;font-weight:800;
                           letter-spacing:10px;color:#0e7490;font-family:monospace;">
                {otp}
              </span>
            </div>

            <p style="color:#64748b;font-size:14px;line-height:1.7;margin:0 0 8px;">
              ⏱ This OTP expires in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.
              Do not share it with anyone.
            </p>
            <p style="color:#64748b;font-size:14px;line-height:1.7;margin:0;">
              If you did not request this, please ignore this email.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:18px 36px;
                     border-top:1px solid #e2e8f0;text-align:center;">
            <p style="color:#94a3b8;font-size:12px;margin:0;">
              Centre for Narmada River Basin Management Studies<br>
              IIT Indore · Ministry of Jal Shakti, Government of India
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    payload = json.dumps({
        "from": "cNARMADA IIT Indore <onboarding@resend.dev>",
        "to": [to_email],
        "subject": "Your cNARMADA Data Access OTP",
        "html": html_body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "cnarmada-backend/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status not in (200, 201):
                raise Exception(f"Resend API error: {resp.status}")
    except urllib.error.HTTPError as e:
        raise Exception(f"Resend API error: {e.code} {e.read().decode()}")


# ── POST /api/auth/send-otp ───────────────────────────────────────────────
@auth_bp.route("/send-otp", methods=["POST"])
def send_otp():
    """
    Body JSON: { "email": "...", "name": "..." }
    Generates a 6-digit OTP, stores it, and emails it.
    Rate-limited: max 3 active OTPs per email within the expiry window.
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name  = (data.get("name")  or "").strip()

    if not email:
        return jsonify({"error": "email is required"}), 400
    if not _EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email address"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) < 2:
        return jsonify({"error": "Name must be at least 2 characters"}), 400

    if not RESEND_API_KEY:
        return jsonify({"error": "Email service not configured. Contact the administrator."}), 503

    conn = _get_conn()
    try:
        _clean_expired(conn)

        # Rate-limit: max 3 pending OTPs per email
        now = datetime.utcnow()
        active = conn.execute(
            "SELECT COUNT(*) FROM otp_store WHERE email=? AND used=0 AND expires_at>?",
            (email, now.strftime("%Y-%m-%d %H:%M:%S"))
        ).fetchone()[0]
        if active >= 3:
            return jsonify({"error": "Too many OTP requests. Please wait a few minutes."}), 429

        # Generate OTP
        otp     = str(random.randint(100000, 999999))
        expires = (now + timedelta(minutes=OTP_EXPIRY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "INSERT INTO otp_store (email, otp, name, expires_at) VALUES (?,?,?,?)",
            (email, otp, name, expires)
        )
        conn.commit()
    finally:
        conn.close()

    # Send email (outside DB transaction)
    try:
        _send_otp_email(email, name, otp)
    except Exception as exc:
        return jsonify({"error": f"Failed to send email: {str(exc)}"}), 502

    return jsonify({
        "message": f"OTP sent to {email}. Valid for {OTP_EXPIRY_MINUTES} minutes.",
        "email":   email,
    }), 200


# ── POST /api/auth/verify-otp ─────────────────────────────────────────────
@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    """
    Body JSON: { "email": "...", "otp": "123456" }
    Returns: { "token": "...", "name": "...", "email": "..." }
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    otp   = (data.get("otp")   or "").strip()

    if not email or not otp:
        return jsonify({"error": "email and otp are required"}), 400

    conn = _get_conn()
    try:
        _clean_expired(conn)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        row = conn.execute(
            """SELECT id, name FROM otp_store
               WHERE email=? AND otp=? AND used=0 AND expires_at>?
               ORDER BY id DESC LIMIT 1""",
            (email, otp, now)
        ).fetchone()

        if not row:
            return jsonify({"error": "Invalid or expired OTP. Please request a new one."}), 401

        # Mark OTP as used
        conn.execute("UPDATE otp_store SET used=1 WHERE id=?", (row["id"],))

        # Create session token
        token      = _make_token(email)
        name       = row["name"] or ""
        expires_at = (
            datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "INSERT INTO auth_sessions (token, email, name, expires_at) VALUES (?,?,?,?)",
            (token, email, name, expires_at)
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "token":   token,
        "email":   email,
        "name":    name,
        "expires": expires_at,
        "message": "OTP verified successfully. Access granted.",
    }), 200


# ── POST /api/auth/verify-token ───────────────────────────────────────────
@auth_bp.route("/verify-token", methods=["POST"])
def verify_token():
    """
    Body JSON: { "token": "..." }
    Frontend calls this on page load to silently re-validate a stored token.
    Returns: { "valid": true/false, "email": "...", "name": "..." }
    """
    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()

    if not token or not _verify_token_signature(token):
        return jsonify({"valid": False}), 200

    conn = _get_conn()
    try:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            "SELECT email, name FROM auth_sessions WHERE token=? AND expires_at>?",
            (token, now)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"valid": False}), 200

    return jsonify({"valid": True, "email": row["email"], "name": row["name"]}), 200
