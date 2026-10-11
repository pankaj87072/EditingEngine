"""
core/logging.py
---------------
Centralised logging configuration.
All modules get a pre-configured logger via get_logger().
"""

import logging
import sys
from typing import Optional


# ── Formatter ────────────────────────────────────────────────────────────────
class ColourFormatter(logging.Formatter):
    """Adds colour codes to log levels for terminal readability."""

    GREY    = "\x1b[38;20m"
    YELLOW  = "\x1b[33;20m"
    RED     = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    GREEN   = "\x1b[32;20m"
    RESET   = "\x1b[0m"

    LEVEL_COLOURS = {
        logging.DEBUG:    GREY,
        logging.INFO:     GREEN,
        logging.WARNING:  YELLOW,
        logging.ERROR:    RED,
        logging.CRITICAL: BOLD_RED,
    }

    FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, self.RESET)
        formatter = logging.Formatter(
            f"{colour}{self.FORMAT}{self.RESET}",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        return formatter.format(record)


def setup_logging(level: str = "INFO") -> None:
    """Call once at application startup to configure root logger."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers on hot-reload
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColourFormatter())
        root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ["httpx", "httpcore", "multipart", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger — use in every module."""
    return logging.getLogger(name)
