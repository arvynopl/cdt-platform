#!/usr/bin/env python
"""scripts/run_e2e_server.py — throwaway backend for the Playwright E2E suite.

Creates a FRESH, seeded SQLite database and serves the FastAPI app on ``$PORT``
(default 8100). Everything is configured through environment variables set by
``frontend/playwright.config.ts``:

    CDT_DATABASE_URL        sqlite URL for the disposable test DB (required to
                            be sqlite — the script refuses anything else)
    CDT_RESEARCHER_PASSWORD researcher-dashboard key the /peneliti spec uses
    CDT_ADMIN_TOKEN         admin-summary token
    CDT_CORS_ORIGINS        the frontend origin under test
    CDT_BCRYPT_ROUNDS       lowered (e.g. 4) so register/login stay fast in CI
    PORT                    port to bind (default 8100)

This never touches Neon: it hard-fails on a non-sqlite URL and recreates the
file on every run, so each suite starts from a known-empty cohort.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make imports (config, database.*, app.main) resolve regardless of the cwd
# Playwright launches us from.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Standalone-friendly defaults; real env (from Playwright) always wins.
os.environ.setdefault("CDT_DATABASE_URL", "sqlite:///e2e_test.db")
os.environ.setdefault("CDT_RESEARCHER_PASSWORD", "devkey")
os.environ.setdefault("CDT_ADMIN_TOKEN", "devadmin")
os.environ.setdefault("CDT_BCRYPT_ROUNDS", "4")
os.environ.setdefault("SENTRY_DSN", "")


def _sqlite_file(url: str) -> Path:
    """Return the on-disk path for a ``sqlite:///`` URL, or exit if not sqlite."""
    if not url.startswith("sqlite"):
        sys.exit(f"run_e2e_server refuses a non-sqlite DB: {url!r}")
    tail = url.split("sqlite:///", 1)[-1]
    path = Path(tail)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path


def main() -> None:
    db_path = _sqlite_file(os.environ["CDT_DATABASE_URL"])
    # Normalise to an absolute URL so config + uvicorn agree no matter the cwd.
    os.environ["CDT_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    if db_path.exists():
        db_path.unlink()  # a clean cohort every run

    # Import only after the env is finalised (config reads it at import time).
    import uvicorn

    from database.seed import run_seed

    run_seed()  # init_db() create_all + seed stock catalog / market snapshots

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8100")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
