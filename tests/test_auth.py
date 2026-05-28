"""
tests/test_auth.py
Coverage for app/auth.py — login, token validation, role decorator.
"""
import hashlib
from unittest.mock import MagicMock

from app import auth
from app.auth import TOKEN_STORE, login, require_role, validate_token


def setup_function(_fn):
    TOKEN_STORE.clear()


class TestLogin:

    def test_success_returns_token(self):
        token = login("nurse_alice", "nurse123")
        assert token is not None
        assert token in TOKEN_STORE
        assert TOKEN_STORE[token]["role"] == "nurse"

    def test_wrong_password_returns_none(self):
        token = login("nurse_alice", "wrong-password")
        assert token is None

    def test_user_not_found_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth, "_db_get_user", lambda u: None)
        assert login("ghost", "anything") is None


class TestValidateToken:

    def test_known_token(self):
        token = login("nurse_alice", "nurse123")
        session = validate_token(token)
        assert session is not None
        assert session["role"] == "nurse"

    def test_unknown_token(self):
        assert validate_token("not-a-real-token") is None


class TestRequireRole:

    def _request_with_token(self, token):
        req = MagicMock()
        req.headers = {"X-Auth-Token": token}
        return req

    def test_missing_token_returns_401(self):
        @require_role("nurse")
        def handler(req):
            return "ok"

        body, status = handler(self._request_with_token(""))
        assert status == 401
        assert body == {"error": "Unauthorized"}

    def test_wrong_role_returns_403(self):
        token = "tok-doctor"
        TOKEN_STORE[token] = {"user_id": "d1", "role": "doctor", "ts": 0}

        @require_role("nurse")
        def handler(req):
            return "ok"

        body, status = handler(self._request_with_token(token))
        assert status == 403
        assert body == {"error": "Forbidden"}

    def test_admin_can_pass_any_role(self):
        token = "tok-admin"
        TOKEN_STORE[token] = {"user_id": "a1", "role": "admin", "ts": 0}

        @require_role("nurse")
        def handler(req):
            return "ok"

        assert handler(self._request_with_token(token)) == "ok"

    def test_matching_role_allows_call(self):
        token = "tok-nurse"
        TOKEN_STORE[token] = {"user_id": "n1", "role": "nurse", "ts": 0}

        @require_role("nurse")
        def handler(req):
            assert req.staff_id == "n1"
            return "ok"

        assert handler(self._request_with_token(token)) == "ok"


class TestMakeToken:

    def test_token_is_sha256_hex(self):
        token = auth._make_token("staff_001")
        assert len(token) == 64
        int(token, 16)  # must be valid hex


class TestDbGetUserStub:

    def test_stub_shape(self):
        u = auth._db_get_user("anyone")
        assert u["pwd_hash"] == hashlib.sha256(b"nurse123").hexdigest()
        assert u["role"] == "nurse"
