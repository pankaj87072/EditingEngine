"""core/llm.py: minimal Anthropic Messages client on the standard library (no extra dependency)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Union

from core.config import settings

API_URL = "https://api.anthropic.com/v1/messages"


def available() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def call_messages(
    *, system: str, content: Union[str, List[dict]], model: str, max_tokens: int = 1500, timeout: float = 25.0,
) -> str:
    """One non-streaming call; returns the concatenated text. Raises RuntimeError on any failure."""
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": 0, "system": system,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": settings.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LLM HTTP {exc.code}") from exc
    except Exception as exc:                                 # timeouts, DNS, TLS ...
        raise RuntimeError(f"LLM request failed: {exc}") from exc
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def extract_json(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in model reply")
    obj = json.loads(text[a: b + 1])
    if not isinstance(obj, dict):
        raise ValueError("model reply is not a JSON object")
    return obj
