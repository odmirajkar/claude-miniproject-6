"""
app/auth.py
Staff authentication for HealthTrack API.

Intentional issues for teaching:
 - JWT secret hardcoded
 - Tokens never expire
 - Password hashed with MD5
 - Login logs the plaintext password on failure
 - No brute-force protection
"""

import hashlib
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

JWT_SECRET = "HealthTrack$JWT$2024"        # hardcoded — should be env var
TOKEN_STORE: dict = {}                     # in-memory — lost on restart


def login(username: str, password: str) -> Optional[str]:
    """
    Authenticate a staff member, return a session token.
    On failure, logs the attempted password — security risk.
    No rate limiting — vulnerable to brute force.
    """
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    user = _db_get_user(username)
    if not user or user["pwd_hash"] != pwd_hash:
        # DO NOT log passwords — this is intentionally wrong for teaching
        logger.warning(f"Failed login: user={username} attempted_password={password}")
        return None

    token = _make_token(user["id"])
    TOKEN_STORE[token] = {"user_id": user["id"], "role": user["role"], "ts": time.time()}
    return token


def validate_token(token: str) -> Optional[dict]:
    """
    Return session data for a token, or None.
    No expiry check — tokens are valid forever.
    """
    return TOKEN_STORE.get(token)


def require_role(required_role: str):
    """
    Decorator factory. Checks token and role.
    Does not validate token expiry.
    """
    def decorator(fn):
        def wrapper(request, *args, **kwargs):
            token = request.headers.get("X-Auth-Token", "")
            session = validate_token(token)
            if not session:
                return {"error": "Unauthorized"}, 401
            if session["role"] not in (required_role, "admin"):
                return {"error": "Forbidden"}, 403
            request.staff_id = session["user_id"]
            return fn(request, *args, **kwargs)
        return wrapper
    return decorator


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    raw = f"{user_id}{time.time()}{JWT_SECRET}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _db_get_user(username: str) -> Optional[dict]:
    """Stub — simulates DB user lookup."""
    return {
        "id": "staff_001",
        "username": username,
        "pwd_hash": hashlib.sha256(b"nurse123").hexdigest(),
        "role": "nurse",
    }
