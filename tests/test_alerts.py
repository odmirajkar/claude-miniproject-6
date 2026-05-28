"""
tests/test_alerts.py
Coverage for app/alerts.py — list, acknowledge, escalate.
"""
from unittest.mock import patch

from app import alerts
from app.alerts import acknowledge_alert, escalate_alert, get_active_alerts


class TestGetActiveAlerts:

    @patch("app.alerts._execute_read", return_value=[{"id": "a1"}])
    def test_without_ward(self, mock_read):
        assert get_active_alerts() == [{"id": "a1"}]
        sent_query = mock_read.call_args[0][0]
        assert "ward_id" not in sent_query

    @patch("app.alerts._execute_read", return_value=[])
    def test_with_ward(self, mock_read):
        assert get_active_alerts(ward_id="ward_A") == []
        sent_query = mock_read.call_args[0][0]
        assert "ward_id = 'ward_A'" in sent_query


class TestAcknowledgeAlert:

    @patch("app.alerts._execute_write")
    def test_returns_success(self, mock_write):
        result = acknowledge_alert("alert_42", "nurse_07")
        assert result == {"success": True, "alert_id": "alert_42"}
        sent_query = mock_write.call_args[0][0]
        assert "alert_42" in sent_query
        assert "ack_by='nurse_07'" in sent_query


class TestEscalateAlert:

    @patch("app.alerts._send_sms")
    def test_success_sends_sms(self, mock_sms):
        result = escalate_alert("alert_1", reason="HR > 180")
        assert result == {"success": True}
        body = mock_sms.call_args.kwargs.get("body") or mock_sms.call_args[0][1]
        assert "HR > 180" in body
        assert "alert_1" in body

    def test_not_found_returns_error(self, monkeypatch):
        monkeypatch.setattr(alerts, "_get_alert", lambda alert_id: None)
        result = escalate_alert("missing", reason="any")
        assert result == {"success": False, "error": "Not found"}


class TestStubs:

    def test_get_alert_stub_shape(self):
        a = alerts._get_alert("x")
        assert a["id"] == "x"
        assert "patient_id" in a

    def test_send_sms_does_not_raise(self):
        alerts._send_sms(on_call_number="+1", body="hi")
