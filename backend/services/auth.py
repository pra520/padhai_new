"""Accounts and sessions.

Optional by design: the app works fully as a guest. Signing in just means the
uploaded material, generated analyses and sticky notes follow you between
visits instead of expiring.

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user random salt — never
in plain text, never reversible. Session tokens are 32 random bytes and live in
an HttpOnly cookie so page scripts can't read them.
"""
import hashlib
import hmac
import re
import secrets
import time
import uuid

from services import db

ITERATIONS = 210_000
SESSION_DAYS = 30
COOKIE = "padhai_session"
# Honoured on read so the rename does not sign existing users out.
LEGACY_COOKIE = "studyai_session"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


class AuthError(RuntimeError):
    """Something the user needs to fix (bad email, wrong password, …)."""


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), ITERATIONS
    ).hex()


def _check(password: str, salt: str, expected: str) -> bool:
    return hmac.compare_digest(_hash(password, salt), expected)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _validate(email: str, password: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("That doesn't look like an email address.")
    if len(password or "") < 8:
        raise AuthError("Use a password of at least 8 characters.")
    if len(password) > 200:
        raise AuthError("That password is too long.")
    return email


def signup(email: str, password: str, name: str = "") -> tuple[dict, str]:
    email = _validate(email, password)
    if db.one("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("An account with that email already exists — try signing in.")

    salt = secrets.token_hex(16)
    user_id = uuid.uuid4().hex[:16]
    db.write(
        "INSERT INTO users (id, email, name, pw_hash, pw_salt, created) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, (name or "").strip()[:60] or email.split("@")[0],
         _hash(password, salt), salt, db.now()),
    )
    return _public(db.one("SELECT * FROM users WHERE id = ?", (user_id,))), _new_session(user_id)


def login(email: str, password: str) -> tuple[dict, str]:
    email = (email or "").strip().lower()
    row = db.one("SELECT * FROM users WHERE email = ?", (email,))
    # Always run the KDF so a missing account and a wrong password take the
    # same time — otherwise the response time leaks which emails are registered.
    salt = row["pw_salt"] if row else secrets.token_hex(16)
    expected = row["pw_hash"] if row else "0" * 64
    if not _check(password or "", salt, expected) or not row:
        raise AuthError("Email or password is incorrect.")
    return _public(row), _new_session(row["id"])


def _public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"]}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _new_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = db.now()
    db.write(
        "INSERT INTO sessions (token, user_id, created, expires) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + SESSION_DAYS * 86400),
    )
    return token


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    row = db.one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires > ?",
        (token, time.time()),
    )
    return _public(row) if row else None


def logout(token: str | None) -> None:
    if token:
        db.write("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired() -> None:
    db.write("DELETE FROM sessions WHERE expires < ?", (time.time(),))
