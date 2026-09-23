"""
Structured logging.

Every log line carries: timestamp, logger name (used as the "source"),
level, and message. Call `get_logger(__name__)` from any module instead of
`logging.getLogger` directly, so the formatting and file handler are
guaranteed to be attached exactly once.

Secrets are never logged. Connectors must log *that* a key is missing, not
the key itself, and must never log full API keys, access tokens, or
credentials — only whether they are present ("configured" / "missing").
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.core.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-32s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("lead_engine")
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"lead_engine.{name}")
