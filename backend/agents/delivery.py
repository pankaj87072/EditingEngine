"""
agents/delivery.py
------------------
Turns script direction tags such as  [Excited, energetic]  into structured delivery metadata
and removes them from the spoken/captioned text.

    [Excited, energetic]
    "Bhai… agar tum bike lover ho, toh ye fact tumhe zaroor pata hona chahiye!"

becomes a scene with text="Bhai… agar tum bike lover ho, ..." and
emotion="excited", delivery="punchy", tts_energy=0.9, speech_speed=1.05.

Deterministic and LLM-free. The TTS providers translate this metadata into their own controls
(ElevenLabs voice settings / audio tags, Google speaking rate and pitch). Punctuation in the
text itself (… ? ! ,) is never touched because it drives natural pacing.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# word -> (emotion, delivery, energy, speed multiplier, pause_after seconds)
_LEXICON = {
    "excited": ("excited", None, 0.9, 1.05, 0.0), "energetic": (None, None, 0.9, 1.05, 0.0),
    "enthusiastic": ("excited", None, 0.85, 1.04, 0.0), "hyped": ("excited", None, 0.95, 1.08, 0.0),
    "punchy": (None, "punchy", 0.85, 1.05, 0.12), "urgent": ("urgent", "punchy", 0.9, 1.08, 0.0),
    "curious": ("curious", None, 0.6, 1.0, 0.0), "intrigued": ("curious", None, 0.6, 1.0, 0.0),
    "mysterious": ("mysterious", "suspense", 0.4, 0.93, 0.25), "secretive": ("mysterious", "suspense", 0.35, 0.92, 0.25),
    "suspense": ("suspense", "suspense", 0.45, 0.9, 0.35), "suspenseful": ("suspense", "suspense", 0.45, 0.9, 0.35),
    "dramatic": (None, "suspense", 0.7, 0.93, 0.3),
    "confident": ("confident", None, 0.7, 1.0, 0.0), "assured": ("confident", None, 0.65, 1.0, 0.0),
    "informative": (None, "informative", 0.55, 1.0, 0.0), "explanatory": (None, "informative", 0.5, 1.0, 0.0),
    "serious": ("serious", None, 0.55, 0.97, 0.2), "grave": ("serious", None, 0.5, 0.94, 0.25),
    "warning": (None, "warning", 0.7, 0.98, 0.2), "stern": ("serious", "warning", 0.65, 0.97, 0.2),
    "calm": ("calm", None, 0.3, 0.95, 0.2), "relaxed": ("calm", None, 0.3, 0.95, 0.15), "soothing": ("calm", "warm", 0.25, 0.93, 0.2),
    "authoritative": (None, "authoritative", 0.5, 0.98, 0.15), "commanding": (None, "authoritative", 0.65, 0.98, 0.15),
    "playful": ("playful", None, 0.75, 1.03, 0.0), "cheerful": ("playful", "warm", 0.75, 1.03, 0.0), "fun": ("playful", None, 0.75, 1.03, 0.0),
    "engaging": (None, None, 0.7, 1.02, 0.0), "friendly": ("friendly", "warm", 0.6, 1.0, 0.0), "warm": (None, "warm", 0.5, 0.98, 0.0),
    "whisper": ("calm", "whisper", 0.15, 0.9, 0.2), "whispering": ("calm", "whisper", 0.15, 0.9, 0.2),
    "sad": ("sad", None, 0.25, 0.92, 0.25), "angry": ("angry", None, 0.85, 1.03, 0.1),
}
_MODIFIERS = {  # speed / pause modifiers that do not carry an emotion
    "slower": (0.9, 0.0), "slow": (0.9, 0.0), "slowly": (0.9, 0.0), "faster": (1.08, 0.0), "fast": (1.08, 0.0), "quick": (1.06, 0.0),
    "pause": (1.0, 0.3), "pauses": (1.0, 0.3), "beat": (1.0, 0.25),
}
_DIRECTIVE_RE = re.compile(r"\[([^\[\]]{2,100})\]")
_QUOTES = "\"'“”‘’«»"


def parse_directive(raw: str) -> dict:
    """Interpret one direction string. Unknown words are ignored (kept in `directive` for debugging)."""
    tokens = [t for t in re.split(r"[,;/&]|\band\b|\s+", raw.lower()) if t]
    emotion: Optional[str] = None
    delivery: Optional[str] = None
    energies: List[float] = []
    speed_dev: List[float] = []                # deviations from 1.0; averaged so "excited, energetic" is not double counted
    pause_after, pause_before = 0.0, 0.0
    for t in tokens:
        t = t.strip(".:!?-–—()\"'")
        if t in _LEXICON:
            e, d, en, sp, pa = _LEXICON[t]
            emotion = emotion or e
            delivery = delivery or d
            energies.append(en)
            speed_dev.append(sp - 1.0)
            pause_after = max(pause_after, pa)
        elif t in _MODIFIERS:
            speed_dev.append(_MODIFIERS[t][0] - 1.0)
            pause_after = max(pause_after, _MODIFIERS[t][1])
    energy = round(sum(energies) / len(energies), 2) if energies else None
    if delivery is None and emotion in ("excited", "urgent"):
        delivery = "punchy" if (energy or 0) >= 0.85 else None
    return {
        "emotion": emotion or ("neutral" if energy is None else "engaged"),
        "delivery": delivery or "neutral",
        "tts_energy": energy,
        "speech_speed": round(max(0.8, min(1.2, 1.0 + (sum(speed_dev) / len(speed_dev) if speed_dev else 0.0))), 3),
        "pause_before": round(pause_before, 2),
        "pause_after": round(pause_after, 2),
        "directive": raw.strip(),
    }


def clean_spoken(text: str) -> str:
    """Remove wrapping quote marks and collapse whitespace. Punctuation inside the line is preserved."""
    t = re.sub(r"\s+", " ", text).strip()
    while t and t[0] in _QUOTES:
        t = t[1:].lstrip()
    while t and t[-1] in _QUOTES:
        t = t[:-1].rstrip()
    return t


def split_directive_blocks(script: str) -> List[Tuple[Optional[dict], str]]:
    """
    Split a script into (delivery | None, text) blocks at every [direction].
    Text before the first direction has delivery None. Empty blocks are dropped.
    Bracketed content without letters (e.g. "[1]") is ordinary text.
    """
    blocks: List[Tuple[Optional[dict], str]] = []
    current: Optional[dict] = None
    pos = 0
    pieces: List[str] = []
    for m in _DIRECTIVE_RE.finditer(script):
        if not re.search(r"[A-Za-z]", m.group(1)):
            continue
        pieces.append(script[pos:m.start()])
        txt = clean_spoken(" ".join(pieces))
        if txt:
            blocks.append((current, txt))
        pieces = []
        current = parse_directive(m.group(1))
        pos = m.end()
    pieces.append(script[pos:])
    txt = clean_spoken(" ".join(pieces))
    if txt:
        blocks.append((current, txt))
    return blocks


def has_directives(script: str) -> bool:
    return any(re.search(r"[A-Za-z]", m.group(1)) for m in _DIRECTIVE_RE.finditer(script))
