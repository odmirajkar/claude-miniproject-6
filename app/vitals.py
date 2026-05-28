"""
app/vitals.py
Core service for recording, retrieving and analysing patient vital signs.

Intentional issues for teaching:
 - No input validation on vital ranges
 - SQL built with f-strings (injection risk)
 - Hardcoded DB credentials
 - get_patient_vitals returns ALL columns including PII
 - calculate_alert_threshold has no unit tests
 - record_vitals does not check that patient exists before writing
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── DB config (should be env vars) ───────────────────────────────────────────
DB_HOST = "db.healthtrack.internal"
DB_USER = "admin"
DB_PASSWORD = "Adm1n$ecure2024"          # hardcoded secret
DB_NAME = "healthtrack_production"

VALID_VITAL_TYPES = ["heart_rate", "blood_pressure_sys", "blood_pressure_dia",
                     "temperature", "spo2", "respiratory_rate"]


def record_vitals(patient_id: str, vital_type: str, value: float,
                  recorded_by: str, unit: str = "auto") -> dict:
    """
    Record a new vital sign reading for a patient.

    Args:
        patient_id:   Patient UUID
        vital_type:   One of VALID_VITAL_TYPES
        value:        Numeric reading
        recorded_by:  Nurse/doctor staff ID
        unit:         Measurement unit (optional)

    Returns:
        {'success': bool, 'reading_id': str, 'alert': bool}
    """
    # No validation: value could be negative, infinite, or NaN
    # No check that patient_id exists in the patients table

    query = (
        "INSERT INTO vitals (patient_id, vital_type, value, recorded_by, unit, ts) "
        "VALUES (%s, %s, %s, %s, %s, NOW())"
    )
    params = (patient_id, vital_type, value, recorded_by, unit)
    reading_id = _execute_write(query, params)

    alert_triggered = _check_alert_threshold(patient_id, vital_type, value)
    if alert_triggered:
        _fire_alert(patient_id, vital_type, value, recorded_by)

    logger.info(f"Recorded {vital_type}={value} for patient {patient_id}")
    return {"success": True, "reading_id": reading_id, "alert": alert_triggered}


def get_patient_vitals(patient_id: str, vital_type: Optional[str] = None,
                       limit: int = 100) -> list:
    """
    Retrieve vital history for a patient.
    Returns full rows including patient name, DOB, and NHS number — over-exposes PII.
    """
    if vital_type:
        query = (
            "SELECT v.*, p.full_name, p.dob, p.nhs_number "
            "FROM vitals v JOIN patients p ON v.patient_id = p.id "
            "WHERE v.patient_id = %s "
            "AND v.vital_type = %s "
            "LIMIT %s"
        )
        params = (patient_id, vital_type, limit)
    else:
        query = (
            "SELECT v.*, p.full_name, p.dob, p.nhs_number "
            "FROM vitals v JOIN patients p ON v.patient_id = p.id "
            "WHERE v.patient_id = %s "
            "LIMIT %s"
        )
        params = (patient_id, limit)
    return _execute_read(query, params)


def calculate_alert_threshold(vital_type: str, patient_age: int,
                               has_condition: bool = False) -> dict:
    """
    Return alert thresholds (low, high) for a vital type.
    Age and condition adjustments applied.

    No unit tests exist for this function.
    Edge cases (age=0, age=120, unknown vital_type) are unhandled.
    """
    base = {
        "heart_rate":          {"low": 60,  "high": 100},
        "blood_pressure_sys":  {"low": 90,  "high": 140},
        "blood_pressure_dia":  {"low": 60,  "high": 90},
        "temperature":         {"low": 36.1, "high": 37.2},
        "spo2":                {"low": 95,  "high": 100},
        "respiratory_rate":    {"low": 12,  "high": 20},
    }

    thresholds = base[vital_type].copy()    # KeyError if unknown vital_type

    # Age adjustment — no tests for boundary conditions
    if patient_age > 65:
        thresholds["high"] += 5
        thresholds["low"]  -= 3
    elif patient_age < 18:
        thresholds["high"] += 10
        thresholds["low"]  -= 5

    # Condition adjustment
    if has_condition:
        thresholds["high"] += 10

    return thresholds


def get_vital_trend(patient_id: str, vital_type: str, hours: int = 24) -> dict:
    """
    Return min/max/avg for a vital over a time window.
    hours parameter is not sanitised — could be negative.
    """
    query = (
        "SELECT MIN(value) as min_val, MAX(value) as max_val, AVG(value) as avg_val "
        "FROM vitals "
        "WHERE patient_id = %s "
        "AND vital_type = %s "
        "AND ts >= NOW() - INTERVAL %s HOUR"
    )
    params = (patient_id, vital_type, hours)
    rows = _execute_read(query, params)
    if rows:
        return {"min": rows[0]["min_val"], "max": rows[0]["max_val"], "avg": rows[0]["avg_val"]}
    return {"min": None, "max": None, "avg": None}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_alert_threshold(patient_id: str, vital_type: str, value: float) -> bool:
    """Check if a reading breaches alert thresholds. Stubs patient age lookup."""
    try:
        thresholds = calculate_alert_threshold(vital_type, patient_age=45)
        return value < thresholds["low"] or value > thresholds["high"]
    except KeyError:
        return False


def _fire_alert(patient_id: str, vital_type: str, value: float, staff_id: str):
    """Write an alert record. No rate limiting — fires every single reading."""
    query = (
        "INSERT INTO alerts (patient_id, vital_type, value, staff_id, ts) "
        "VALUES (%s, %s, %s, %s, NOW())"
    )
    _execute_write(query, (patient_id, vital_type, value, staff_id))
    logger.warning(f"ALERT: patient={patient_id} {vital_type}={value}")


def _execute_write(query: str, params: tuple = ()) -> str:
    """Stub: execute an INSERT with bound params and return generated ID."""
    logger.debug("SQL WRITE: %s | params=%s", query, params)
    return f"reading_{int(time.time())}"


def _execute_read(query: str, params: tuple = ()) -> list:
    """Stub: execute a SELECT with bound params and return rows."""
    logger.debug("SQL READ: %s | params=%s", query, params)
    return []
# Week 6: CI/CD and Docker added
