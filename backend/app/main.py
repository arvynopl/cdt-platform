"""app/main.py — FastAPI entry point for the CDT platform backend.

Run locally:
    uvicorn app.main:app --reload --port 8000

Ops posture (audit F9):
  * structured JSON logs to stdout (container-friendly; no local files),
  * per-request latency logging + ``X-Response-Time-Ms`` header,
  * optional Sentry: set ``SENTRY_DSN`` and errors/traces ship automatically,
  * ``/healthz`` liveness probe for uptime monitoring.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth as auth_router
from app.routers import profile as profile_router
from app.routers import researcher as researcher_router
from app.routers import simulation as simulation_router
from config import COOKIE_SECURE, CORS_ORIGINS, validate_api_config, validate_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging — structured JSON to stdout
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_cdt_json", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler._cdt_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(
        logging.DEBUG if os.environ.get("CDT_DEBUG") else logging.INFO
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _configure_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("CDT_ENV", "production"),
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.2")
            ),
            send_default_pii=False,  # UU PDP: no request bodies / user PII
        )
        logger.info("Sentry initialised")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_configure_logging()
_configure_sentry()
validate_config()
validate_api_config()

if not COOKIE_SECURE:
    logger.warning(
        "Cookies are NOT marked Secure (CDT_COOKIE_SECURE unset) — "
        "acceptable for local development only."
    )

app = FastAPI(
    title="CDT Platform API",
    version="0.2.0",
    description=(
        "Behavioral-bias detection backend (Cognitive Digital Twin). "
        "Domain layer ported unchanged from the research-validated "
        "TA-18222007 thesis-defense build; parity is CI-enforced."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    # PATCH is needed by /api/me/profile; without it the cross-origin
    # preflight from the Vercel frontend fails before the request is sent.
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=[
        "content-type",
        "x-csrf-token",
        # Key-gated researcher/admin endpoints authenticate on these request
        # headers; the browser only sends them cross-origin if CORS allows them.
        "x-researcher-key",
        "x-admin-token",
    ],
)


@app.middleware("http")
async def _latency_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
    if request.url.path != "/healthz":
        logger.info(
            "http %s %s -> %s in %.1f ms",
            request.method, request.url.path, response.status_code, elapsed_ms,
        )
    return response


@app.middleware("http")
async def _security_headers_middleware(request: Request, call_next):
    """Defense-in-depth response headers for the JSON API.

    Deliberately conservative so nothing breaks: the CSP is limited to
    ``frame-ancestors 'none'`` (anti-framing only — it does NOT set
    ``default-src``, so Swagger UI at /docs keeps loading its CDN assets).
    HSTS is emitted only when cookies are Secure (i.e. served over HTTPS in
    production); on plain-HTTP localhost it is omitted and browsers would
    ignore it anyway.
    """
    response = await call_next(request)
    response.headers.setdefault("x-content-type-options", "nosniff")
    response.headers.setdefault("x-frame-options", "DENY")
    response.headers.setdefault("referrer-policy", "no-referrer")
    response.headers.setdefault("content-security-policy", "frame-ancestors 'none'")
    if COOKIE_SECURE:
        response.headers.setdefault(
            "strict-transport-security",
            "max-age=63072000; includeSubDomains; preload",
        )
    return response


app.include_router(auth_router.router)
app.include_router(simulation_router.router)
app.include_router(profile_router.router)
app.include_router(profile_router.survey_router)
app.include_router(researcher_router.router)
app.include_router(researcher_router.admin_router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    """Liveness probe for uptime monitoring (audit F9)."""
    return {"status": "ok"}


if os.environ.get("CDT_ENV") != "production":
    # Sentry setup verification, development only: fly.toml pins
    # CDT_ENV=production, so this route never exists on the deployed app.
    @app.get("/sentry-debug", tags=["ops"], include_in_schema=False)
    def sentry_debug() -> None:
        raise ZeroDivisionError("sentry verification event (intentional)")
