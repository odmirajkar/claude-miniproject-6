"""
HealthTrack API
A patient vitals tracking backend for clinics.
"""
from flask import Flask
from .routes import vitals_bp, patients_bp, alerts_bp, health_bp


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-change-in-prod"
    app.register_blueprint(vitals_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(health_bp)
    return app
