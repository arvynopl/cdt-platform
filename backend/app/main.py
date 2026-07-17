"""app/main.py — FastAPI entry point for the CDT platform backend.

Fase 0 scope: application skeleton + health endpoint only. Domain routes
(auth, sessions, rounds, profiles, feedback) land in Fase 1 per the
implementation plan.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from config import validate_config

logger = logging.getLogger(__name__)

validate_config()

app = FastAPI(
    title="CDT Platform API",
    version="0.1.0",
    description=(
        "Behavioral-bias detection backend (Cognitive Digital Twin). "
        "Domain layer ported unchanged from the research-validated "
        "TA-18222007 thesis-defense build."
    ),
)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    """Liveness probe for the platform's uptime monitoring (audit F9)."""
    return {"status": "ok"}
