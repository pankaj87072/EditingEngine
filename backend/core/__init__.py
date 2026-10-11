"""
core/
-----
Cross-cutting concerns: config, logging, exceptions.
"""
from core.config import settings
from core.logging import get_logger, setup_logging

__all__ = ["settings", "get_logger", "setup_logging"]
