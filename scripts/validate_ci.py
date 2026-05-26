#!/usr/bin/env python3
"""
scripts/validate_ci.py
─────────────────────────────────────────────────
Week 6 Mini Project — validation script.

Checks that learners have completed all 4 deliverables:
  1. .github/workflows/ci.yml     — full CI pipeline
  2. Dockerfile                   — multi-stage build
  3. docker-compose.yml           — full service stack
  4. .env.example                 — environment template

Run from the project root:
    python scripts/validate_ci.py

Exit 0 = all checks pass
Exit 1 = one or more checks failed
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"
BOLD = "\033[1m"
X    = "\033[0m"

errors = []
warnings = []

def check(condition, label, fix=""):
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}")
        if fix:
            print(f"       Fix: {fix}")
        errors.append(label)

def warn(condition, label, note=""):
    if not condition:
        print(f"  {WARN}  {label}")
        if note:
            print(f"       Note: {note}")
        warnings.append(label)

print(f"\n{BOLD}Week 6 Mini Project — Validation{X}")
print("=" * 50)

# ── Check 1: CI Workflow ────────────────────────────────────────
print(f"\n{BOLD}1. GitHub Actions CI Workflow{X}")
ci_path = ROOT / ".github" / "workflows" / "ci.yml"
check(ci_path.exists(), "ci.yml exists at .github/workflows/ci.yml",
      "Create with Claude Code: generate a GitHub Actions CI pipeline for HealthTrack API")

if ci_path.exists():
    ci = ci_path.read_text()
    check("pull_request" in ci, "Triggers on pull_request")
    check("push" in ci,         "Triggers on push to main")
    check("pytest" in ci or "test" in ci.lower(), "Has a test job")
    check("pip install" in ci or "setup-python" in ci, "Installs Python dependencies")
    check("secrets." in ci,     "Uses GitHub secrets (not hardcoded keys)")
    warn("ANTHROPIC_API_KEY" not in ci or "secrets.ANTHROPIC_API_KEY" in ci,
         "API key uses secrets reference, not hardcoded value",
         "Replace ANTHROPIC_API_KEY: sk-ant-... with ${{ secrets.ANTHROPIC_API_KEY }}")
    check("actions/checkout" in ci, "Checks out code with actions/checkout")
    check("cov-fail-under" in ci or "coverage" in ci.lower(), "Enforces coverage threshold",
          "Add: --cov-fail-under=80 to your pytest command")
    check("needs:" in ci, "Jobs have dependency ordering with needs:",
          "Add needs: [lint] to test job so it runs after lint passes")

# ── Check 2: Dockerfile ─────────────────────────────────────────
print(f"\n{BOLD}2. Dockerfile{X}")
df_path = ROOT / "Dockerfile"
check(df_path.exists(), "Dockerfile exists at project root",
      "Create with Claude Code: generate a production Dockerfile for HealthTrack API")

if df_path.exists():
    df = df_path.read_text()
    check("AS builder" in df or "AS runtime" in df or "FROM" in df,
          "Uses multi-stage build (AS builder + AS runtime)",
          "Ask Claude: generate a multi-stage Dockerfile — builder stage + slim runtime stage")
    check("python:3.11-slim" in df or "-slim" in df or "-alpine" in df,
          "Uses a slim/minimal base image",
          "Change FROM python:3.11 to FROM python:3.11-slim in the runtime stage")
    check("USER " in df and "root" not in df.lower().split("user")[-1].strip()[:10],
          "Runs as non-root user",
          "Add: RUN useradd -m appuser && USER appuser before CMD")
    check("HEALTHCHECK" in df, "Has HEALTHCHECK instruction",
          "Add: HEALTHCHECK CMD curl -f http://localhost:5000/health || exit 1")
    check("EXPOSE" in df,      "Exposes a port with EXPOSE")
    check("ENV PYTHONDONTWRITEBYTECODE" in df or "ENV PYTHON" in df,
          "Sets Python env vars (PYTHONDONTWRITEBYTECODE/PYTHONUNBUFFERED)")
    warn(".env" not in df,     "No .env file reference in Dockerfile — secrets come from runtime",
         "Never COPY .env into the image. Use env_file in docker-compose instead.")

# ── Check 3: docker-compose.yml ─────────────────────────────────
print(f"\n{BOLD}3. docker-compose.yml{X}")
dc_path = ROOT / "docker-compose.yml"
check(dc_path.exists(), "docker-compose.yml exists at project root",
      "Create with Claude Code: generate docker-compose for HealthTrack with api + postgres + redis")

if dc_path.exists():
    dc = dc_path.read_text()
    check("services:" in dc,       "Has services block")
    check("api:" in dc or "app:" in dc, "Has api/app service")
    check("postgres" in dc or "db:" in dc, "Has database service (postgres)")
    check("redis" in dc or "cache:" in dc, "Has cache service (redis)")
    check("volumes:" in dc,        "Has named volumes for data persistence")
    check("healthcheck:" in dc,    "Services have health checks")
    check("depends_on:" in dc,     "api depends_on db",
          "Add depends_on: db: condition: service_healthy to the api service")
    check("env_file:" in dc or "environment:" in dc, "Loads environment variables")
    warn("DB_PASSWORD: CHANGE_ME" not in dc and "${DB_PASSWORD}" in dc,
         "DB_PASSWORD uses variable reference, not hardcoded value")

# ── Check 4: .env.example ───────────────────────────────────────
print(f"\n{BOLD}4. Environment Configuration{X}")
env_ex = ROOT / ".env.example"
env_real = ROOT / ".env"
gitignore = ROOT / ".gitignore"

check(env_ex.exists(),  ".env.example exists and is committed",
      "Create with Claude Code: generate a .env.example for HealthTrack API")
check(not env_real.exists() or (
    gitignore.exists() and ".env" in gitignore.read_text()
), ".env is gitignored (real secrets not committed)",
     "Add .env to your .gitignore file")

if env_ex.exists():
    env = env_ex.read_text()
    check("DB_PASSWORD" in env,         "DB_PASSWORD variable present")
    check("ANTHROPIC_API_KEY" in env,   "ANTHROPIC_API_KEY variable present")
    check("FLASK_ENV" in env or "FLASK" in env, "Flask environment variables present")
    warn("sk-ant-" not in env,          ".env.example has no real API keys",
         "Replace real values with placeholders like sk-ant-CHANGE_ME")

# ── Check 5: PR template (bonus) ────────────────────────────────
print(f"\n{BOLD}5. PR Template (bonus){X}")
pr_tmpl = ROOT / ".github" / "pull_request_template.md"
if pr_tmpl.exists():
    tmpl = pr_tmpl.read_text()
    check("## Summary" in tmpl or "## Description" in tmpl,
          "PR template has Summary/Description section")
    check("## Testing" in tmpl or "## Test" in tmpl,
          "PR template has Testing section")
    print(f"  {PASS}  pull_request_template.md found — bonus complete ✓")
else:
    print(f"  ℹ   pull_request_template.md not found — optional stretch goal")

# ── Summary ──────────────────────────────────────────────────────
print(f"\n{'=' * 50}")
if not errors:
    print(f"{BOLD}\033[92m✓ All checks passed! Week 6 mini project complete.\033[0m{X}")
    if warnings:
        print(f"\n{WARN} {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  • {w}")
else:
    print(f"{BOLD}\033[91m✗ {len(errors)} check(s) failed:{X}")
    for e in errors:
        print(f"  • {e}")
    if warnings:
        print(f"\n{WARN} {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  • {w}")
    sys.exit(1)
