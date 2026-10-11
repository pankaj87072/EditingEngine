"""
agents/base_agent.py
--------------------
Abstract base class for all agents.
Enforces a consistent run() interface and wires in logging + error handling.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from core.exceptions import AgentError
from core.logging import get_logger


class BaseAgent(ABC):
    """
    Every agent:
      1. Has a unique name used in log messages.
      2. Exposes a single public method: run(**kwargs) -> Any
      3. Reports execution time automatically.
      4. Wraps exceptions in AgentError so callers get a uniform type.
    """

    # Subclasses override this
    agent_name: str = "BaseAgent"

    def __init__(self) -> None:
        self.logger = get_logger(self.agent_name)
        self._metadata: Dict[str, Any] = {}

    # ── Public interface ──────────────────────────────────────────────────────

    def run(self, **kwargs: Any) -> Any:
        """
        Entry point for every agent call.
        Measures timing, logs start/end, wraps exceptions.
        """
        self.logger.info(f"▶  Starting  [{self.agent_name}]")
        start = time.perf_counter()
        try:
            result = self._execute(**kwargs)
            elapsed = time.perf_counter() - start
            self.logger.info(
                f"✔  Completed [{self.agent_name}] in {elapsed:.2f}s"
            )
            return result
        except AgentError:
            # Already wrapped — re-raise as-is
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.logger.error(
                f"✘  Failed    [{self.agent_name}] after {elapsed:.2f}s — {exc}"
            )
            raise AgentError(
                message=f"{self.agent_name} failed: {exc}",
                detail=str(exc),
            ) from exc

    # ── Subclass contract ─────────────────────────────────────────────────────

    @abstractmethod
    def _execute(self, **kwargs: Any) -> Any:
        """Subclasses implement their logic here."""
        ...

    # ── Helpers available to subclasses ──────────────────────────────────────

    def _log_step(self, message: str) -> None:
        self.logger.debug(f"  ↳ {message}")

    def _store_meta(self, key: str, value: Any) -> None:
        """Store arbitrary metadata for debugging / introspection."""
        self._metadata[key] = value

    def get_metadata(self) -> Dict[str, Any]:
        return dict(self._metadata)
