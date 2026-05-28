"""
app/routes.py
Flask route definitions for HealthTrack API.
"""
from __future__ import annotations

from flask import Blueprint, request, jsonify
from .vitals import record_vitals, get_patient_vitals, get_vital_trend
from .alerts import get_active_alerts, acknowledge_alert, escalate_alert
from .auth import validate_token

vitals_bp   = Blueprint("vitals",   __name__, url_prefix="/vitals")
patients_bp = Blueprint("patients", __name__, url_prefix="/patients")
alerts_bp   = Blueprint("alerts",   __name__, url_prefix="/alerts")
health_bp   = Blueprint("health",   __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    """Liveness probe — used by Docker HEALTHCHECK and orchestrators."""
    return jsonify({"status": "ok"}), 200


def _get_staff_id(req) -> str | None:
    token = req.headers.get("X-Auth-Token", "")
    session = validate_token(token)
    return session["user_id"] if session else None


@vitals_bp.route("/<patient_id>", methods=["POST"])
def post_vital(patient_id):
    staff_id = _get_staff_id(request)
    if not staff_id:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    result = record_vitals(
        patient_id=patient_id,
        vital_type=data.get("vital_type"),
        value=data.get("value"),
        recorded_by=staff_id,
    )
    return jsonify(result), 201


@vitals_bp.route("/<patient_id>", methods=["GET"])
def get_vitals(patient_id):
    staff_id = _get_staff_id(request)
    if not staff_id:
        return jsonify({"error": "Unauthorized"}), 401
    vital_type = request.args.get("type")
    rows = get_patient_vitals(patient_id, vital_type)
    return jsonify(rows), 200


@vitals_bp.route("/<patient_id>/trend", methods=["GET"])
def vital_trend(patient_id):
    vital_type = request.args.get("type", "heart_rate")
    hours = int(request.args.get("hours", 24))
    return jsonify(get_vital_trend(patient_id, vital_type, hours))


@alerts_bp.route("/", methods=["GET"])
def list_alerts():
    ward = request.args.get("ward")
    return jsonify(get_active_alerts(ward))


@alerts_bp.route("/<alert_id>/acknowledge", methods=["POST"])
def ack_alert(alert_id):
    staff_id = _get_staff_id(request)
    if not staff_id:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(acknowledge_alert(alert_id, staff_id))


@alerts_bp.route("/<alert_id>/escalate", methods=["POST"])
def esc_alert(alert_id):
    data = request.get_json()
    return jsonify(escalate_alert(alert_id, data.get("reason", "")))
