"""Password hashing and session helpers for real-user accounts.

Stdlib only: hashlib.scrypt for password hashing (no bcrypt/passlib/argon2
dependency), hmac.compare_digest for timing-safe comparison. Sessions are
plain Starlette SessionMiddleware cookies (signed, not encrypted) — the
only thing stored in the session is the user's id.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return "salt_hex$hash_hex" for storage. A fresh random salt every call."""
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against a hash_password() string."""
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return hmac.compare_digest(actual, expected)


class NotAuthenticated(Exception):
    """Raised by require_user() when the request has no logged-in user.

    A FastAPI dependency can't return a RedirectResponse directly and have
    it replace the route's response, so app_routes/auth_routes install an
    exception handler that turns this into a redirect to /login.
    """


def current_user_id(request: Request) -> str | None:
    return request.session.get("user_id")


def log_in(request: Request, user_id: str) -> None:
    request.session["user_id"] = user_id


def log_out(request: Request) -> None:
    request.session.pop("user_id", None)


def require_user(request: Request) -> str:
    """FastAPI dependency: the current user's id, or raise NotAuthenticated."""
    user_id = current_user_id(request)
    if user_id is None:
        raise NotAuthenticated()
    return user_id
