"""
tests/test_routes.py
Flask-level coverage for app/routes.py and app/__init__.py.
"""
from unittest.mock import patch

import pytest

from app import create_app
from app.auth import TOKEN_STORE


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def auth_header():
    token = "test-token"
    TOKEN_STORE[token] = {"user_id": "nurse_07", "role": "nurse", "ts": 0}
    yield {"X-Auth-Token": token}
    TOKEN_STORE.pop(token, None)


class TestHealth:

    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestPostVital:

    def test_unauthorized_without_token(self, client):
        resp = client.post("/vitals/p001", json={"vital_type": "heart_rate",
                                                 "value": 72})
        assert resp.status_code == 401

    @patch("app.routes.record_vitals",
           return_value={"success": True, "reading_id": "r1", "alert": False})
    def test_authorized_post(self, mock_record, client, auth_header):
        resp = client.post("/vitals/p001",
                           json={"vital_type": "heart_rate", "value": 72},
                           headers=auth_header)
        assert resp.status_code == 201
        assert resp.get_json()["reading_id"] == "r1"
        mock_record.assert_called_once()


class TestGetVitals:

    def test_unauthorized_without_token(self, client):
        resp = client.get("/vitals/p001")
        assert resp.status_code == 401

    @patch("app.routes.get_patient_vitals", return_value=[{"id": 1}])
    def test_authorized_get(self, mock_get, client, auth_header):
        resp = client.get("/vitals/p001?type=heart_rate", headers=auth_header)
        assert resp.status_code == 200
        assert resp.get_json() == [{"id": 1}]
        mock_get.assert_called_once_with("p001", "heart_rate")


class TestVitalTrend:

    @patch("app.routes.get_vital_trend",
           return_value={"min": 60, "max": 100, "avg": 80})
    def test_trend_endpoint(self, mock_trend, client):
        resp = client.get("/vitals/p001/trend?type=heart_rate&hours=12")
        assert resp.status_code == 200
        assert resp.get_json()["avg"] == 80
        mock_trend.assert_called_once_with("p001", "heart_rate", 12)


class TestListAlerts:

    @patch("app.routes.get_active_alerts", return_value=[{"id": "a1"}])
    def test_list_all(self, mock_list, client):
        resp = client.get("/alerts/")
        assert resp.status_code == 200
        assert resp.get_json() == [{"id": "a1"}]
        mock_list.assert_called_once_with(None)

    @patch("app.routes.get_active_alerts", return_value=[])
    def test_list_with_ward(self, mock_list, client):
        resp = client.get("/alerts/?ward=ward_A")
        assert resp.status_code == 200
        mock_list.assert_called_once_with("ward_A")


class TestAckAlert:

    def test_unauthorized(self, client):
        resp = client.post("/alerts/a1/acknowledge")
        assert resp.status_code == 401

    @patch("app.routes.acknowledge_alert",
           return_value={"success": True, "alert_id": "a1"})
    def test_authorized(self, mock_ack, client, auth_header):
        resp = client.post("/alerts/a1/acknowledge", headers=auth_header)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        mock_ack.assert_called_once_with("a1", "nurse_07")


class TestEscalateAlert:

    @patch("app.routes.escalate_alert", return_value={"success": True})
    def test_escalate(self, mock_esc, client):
        resp = client.post("/alerts/a1/escalate", json={"reason": "HR spike"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        mock_esc.assert_called_once_with("a1", "HR spike")
