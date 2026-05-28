"""
tests/test_vitals_extra.py
Extra coverage for app/vitals.py — branches missed by test_vitals.py.
"""
from unittest.mock import patch

import pytest

from app.vitals import (
    calculate_alert_threshold,
    get_patient_vitals,
    get_vital_trend,
    record_vitals,
)


class TestGetPatientVitals:

    @patch("app.vitals._execute_read", return_value=[{"id": 1}])
    def test_with_vital_type(self, mock_read):
        rows = get_patient_vitals("p001", vital_type="heart_rate", limit=50)
        assert rows == [{"id": 1}]
        sent_query, sent_params = mock_read.call_args[0]
        assert "v.patient_id = %s" in sent_query
        assert "v.vital_type = %s" in sent_query
        assert "LIMIT %s" in sent_query
        assert sent_params == ("p001", "heart_rate", 50)

    @patch("app.vitals._execute_read", return_value=[])
    def test_without_vital_type(self, mock_read):
        rows = get_patient_vitals("p001")
        assert rows == []
        sent_query, sent_params = mock_read.call_args[0]
        assert "vital_type" not in sent_query
        assert "LIMIT %s" in sent_query
        assert sent_params == ("p001", 100)


class TestCalculateAlertThresholdEdgeCases:

    def test_elderly_adjustment(self):
        t = calculate_alert_threshold("heart_rate", patient_age=80)
        assert t["high"] == 105
        assert t["low"] == 57

    def test_paediatric_adjustment(self):
        t = calculate_alert_threshold("heart_rate", patient_age=10)
        assert t["high"] == 110
        assert t["low"] == 55

    def test_has_condition_adds_to_high(self):
        t = calculate_alert_threshold("heart_rate", patient_age=40, has_condition=True)
        assert t["high"] == 110
        assert t["low"] == 60

    def test_elderly_with_condition_stacks(self):
        t = calculate_alert_threshold("heart_rate", patient_age=70, has_condition=True)
        assert t["high"] == 115
        assert t["low"] == 57

    def test_unknown_vital_type_raises(self):
        with pytest.raises(KeyError):
            calculate_alert_threshold("unicorn_pulse", patient_age=40)

    def test_all_known_vital_types(self):
        for vital in ["heart_rate", "blood_pressure_sys", "blood_pressure_dia",
                      "temperature", "spo2", "respiratory_rate"]:
            t = calculate_alert_threshold(vital, patient_age=40)
            assert "low" in t and "high" in t


class TestGetVitalTrend:

    @patch("app.vitals._execute_read",
           return_value=[{"min_val": 60, "max_val": 100, "avg_val": 80}])
    def test_with_rows(self, mock_read):
        result = get_vital_trend("p001", "heart_rate", hours=12)
        assert result == {"min": 60, "max": 100, "avg": 80}
        sent_query, sent_params = mock_read.call_args[0]
        assert "INTERVAL %s HOUR" in sent_query
        assert sent_params == ("p001", "heart_rate", 12)

    @patch("app.vitals._execute_read", return_value=[])
    def test_empty_rows(self, mock_read):
        result = get_vital_trend("p001", "heart_rate")
        assert result == {"min": None, "max": None, "avg": None}


class TestRecordVitalsAlertPath:

    @patch("app.vitals._execute_write", return_value="reading_999")
    def test_unknown_vital_type_no_alert(self, mock_write):
        """Unknown vital_type hits the KeyError branch in _check_alert_threshold."""
        result = record_vitals("p001", "unicorn_pulse", 999.0, "nurse_01")
        assert result["alert"] is False
        assert result["success"] is True

    @patch("app.vitals._execute_write", return_value="reading_111")
    def test_alert_writes_two_rows(self, mock_write):
        """High HR triggers _fire_alert — _execute_write called twice."""
        record_vitals("p001", "heart_rate", 200.0, "nurse_01")
        assert mock_write.call_count == 2
