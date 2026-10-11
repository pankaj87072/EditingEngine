"""
core/exceptions.py
------------------
Domain-specific exceptions used throughout the system.
Catching these lets the API layer return precise HTTP status codes.
"""

from typing import Optional


class VideoGenBaseError(Exception):
    """Root exception — all custom errors inherit from this."""

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r})"


# ── Job / Storage ─────────────────────────────────────────────────────────────

class JobNotFoundError(VideoGenBaseError):
    """Raised when a job_id does not exist in storage."""


class JobAlreadyExistsError(VideoGenBaseError):
    """Raised when attempting to create a duplicate job."""


class StorageError(VideoGenBaseError):
    """File system / storage operation failed."""


class JobCancelledError(VideoGenBaseError):
    """Raised inside the pipeline when the user cancelled the job."""


# ── Agent errors ──────────────────────────────────────────────────────────────

class AgentError(VideoGenBaseError):
    """Generic agent failure — subclass for specific agents."""


class ScriptSegmentationError(AgentError):
    """ScriptSegmentationAgent could not parse the script."""


class SceneMappingError(AgentError):
    """SceneMappingAgent failed to map clips to scenes."""


class AudioGenerationError(AgentError):
    """AudioGenerationAgent / TTS provider call failed."""


class SubtitleTimingError(AgentError):
    """SubtitleTimingAgent could not generate timings."""


class VideoCompositionError(AgentError):
    """VideoCompositionAgent / FFmpeg command failed."""


# ── TTS ──────────────────────────────────────────────────────────────────────

class TTSProviderError(AudioGenerationError):
    """TTS provider returned an error or is mis-configured."""


class UnsupportedTTSProviderError(TTSProviderError):
    """The requested TTS provider is not implemented."""


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationError(VideoGenBaseError):
    """Input validation failed before processing starts."""


class UnsupportedFileTypeError(ValidationError):
    """Uploaded file has an unsupported MIME type or extension."""
