"""
modules/utils/log_config.py — Centralised logging configuration.

Call configure_logging() once at app startup (in app.py) to:
  - Write structured logs to  app.log  (rotating, max 5 MB × 3 backups)
  - Echo INFO+ to the console
  - Suppress noisy third-party loggers (SQLAlchemy echo, Streamlit internals)

Usage:
    from modules.utils.log_config import configure_logging
    configure_logging()          # call once at module level in app.py
    configure_logging(debug=True) # verbose mode — also logs DEBUG
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_configured = False

LOG_FILE = Path(__file__).parents[2] / "app.log"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(debug: bool = False) -> None:
    """Configure root logger with rotating file + console handlers.

    Safe to call multiple times — subsequent calls are no-ops.

    Args:
        debug: If True, sets root level to DEBUG (very verbose).
               If False (default), sets root level to INFO.
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    level = logging.DEBUG if debug else logging.INFO
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # --- Rotating file handler (5 MB × 3 backups) ---
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # --- Console handler (INFO+ only, even in debug mode) ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root.addHandler(console_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "Logging initialised — level=%s file=%s",
        logging.getLevelName(level),
        LOG_FILE,
    )
