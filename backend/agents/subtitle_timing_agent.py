"""
agents/subtitle_timing_agent.py
--------------------------------
SubtitleTimingAgent
-------------------
Responsibility:
  - If the TTS provider returned word-level timings → use them directly.
  - Otherwise → evenly distribute words across the audio duration.
  - Group words into short subtitle blocks (3–5 words max).
  - Output SRT-compatible SubtitleEntry list.

Input kwargs:
    audio_result  (AudioResult):       From AudioGenerationAgent.
    scenes        (List[ScriptScene]): From ScriptSegmentationAgent.

Returns:
    List[SubtitleEntry]
"""

from __future__ import annotations

import math
from typing import List

from agents.base_agent import BaseAgent
from core.exceptions import SubtitleTimingError
from core import editing_rules as R
from models.schema import AudioResult, ScriptScene, SubtitleEntry, WordTiming


# Max words per subtitle card
_MAX_WORDS_PER_CARD = 4


class SubtitleTimingAgent(BaseAgent):
    agent_name = "SubtitleTimingAgent"

    def _execute(  # type: ignore[override]
        self,
        *,
        audio_result: AudioResult,
        scenes: List[ScriptScene],
        max_words: int = _MAX_WORDS_PER_CARD,
    ) -> List[SubtitleEntry]:

        if not scenes:
            raise SubtitleTimingError("No scenes provided.")
        if audio_result.duration <= 0:
            raise SubtitleTimingError("Audio duration must be > 0.")

        # ── Use provider word timings if available ────────────────────────────
        if audio_result.word_timings:
            self._log_step(
                f"Using provider word timings ({len(audio_result.word_timings)} words)"
            )
            entries = self._build_from_word_timings(audio_result.word_timings, max_words, self._scene_breaks(scenes, len(audio_result.word_timings)))
        else:
            self._log_step(
                "No provider timings — estimating from audio duration"
            )
            entries = self._build_estimated(scenes, audio_result, max_words)

        self._store_meta("subtitle_count", len(entries))
        self._log_step(f"Generated {len(entries)} subtitle entries")
        return entries

    # ── Phrase-based grouping ─────────────────────────────────────────────────

    @staticmethod
    def phrase_groups(words: List[str], max_words: int, breaks: frozenset = frozenset()) -> List[List[int]]:
        """
        Group word indices into caption cards that end on phrase boundaries
        (. ! ? ; : ,) or when max_words is reached, instead of a fixed N words.
        """
        groups: List[List[int]] = []
        cur: List[int] = []
        for i, w in enumerate(words):
            if i in breaks and cur:                      # a new scene starts here: never share a card across it
                groups.append(cur)
                cur = []
            cur.append(i)
            if len(cur) >= max_words or (w[-1:] in R.CAPTION_PAUSE_CHARS and len(cur) >= R.CAPTION_MIN_WORDS):
                groups.append(cur)
                cur = []
        if cur:
            if (groups and len(cur) < R.CAPTION_MIN_WORDS and len(groups[-1]) + len(cur) <= max_words
                    and cur[0] not in breaks):
                groups[-1] += cur
            else:
                groups.append(cur)
        return groups

    # ── Build from provider word timings ─────────────────────────────────────

    @staticmethod
    def _scene_breaks(scenes: List[ScriptScene], n_words: int) -> frozenset:
        """Word indices where a scene starts (only trusted when the word count matches the script)."""
        counts = [len(sc.text.split()) for sc in scenes]
        if sum(counts) != n_words:
            return frozenset()
        out, acc = set(), 0
        for c in counts[:-1]:
            acc += c
            out.add(acc)
        return frozenset(out)

    def _build_from_word_timings(
        self, word_timings: List[WordTiming], max_words: int = _MAX_WORDS_PER_CARD, breaks: frozenset = frozenset(),
    ) -> List[SubtitleEntry]:
        words = [w.word for w in word_timings]
        entries: List[SubtitleEntry] = []
        for card_idx, g in enumerate(self.phrase_groups(words, max_words, breaks)):
            entries.append(SubtitleEntry(
                index=card_idx,
                start_time=round(word_timings[g[0]].start_time, 3),
                end_time=round(word_timings[g[-1]].end_time, 3),
                text=" ".join(words[i] for i in g),
            ))
        return entries

    # ── Estimate from audio duration ──────────────────────────────────────────

    def _build_estimated(
        self,
        scenes: List[ScriptScene],
        audio: "AudioResult | float",
        max_words: int = _MAX_WORDS_PER_CARD,
    ) -> List[SubtitleEntry]:
        """
        No provider timings: spread words over the audio with pauses weighted at
        punctuation (same model the editing engine uses to place cuts).
        """
        from agents.editing_engine import word_start_times

        if not isinstance(audio, AudioResult):             # legacy call: plain duration
            audio = AudioResult(audio_path="", duration=float(audio), provider="google")  # type: ignore[arg-type]
        words = [w for sc in scenes for w in sc.text.split()]
        if not words:
            return []
        starts = word_start_times(scenes, audio)
        entries: List[SubtitleEntry] = []
        for card_idx, g in enumerate(self.phrase_groups(words, max_words, self._scene_breaks(scenes, len(words)))):
            start = starts[g[0]]
            end = starts[g[-1] + 1]
            entries.append(SubtitleEntry(
                index=card_idx,
                start_time=round(start, 3),
                end_time=round(max(start + 0.1, min(end, audio.duration) - 0.05), 3),
                text=" ".join(words[i] for i in g),
            ))
        return entries

    # ── SRT export helper (used by VideoCompositionAgent) ─────────────────────

    @staticmethod
    def to_srt(entries: List[SubtitleEntry]) -> str:
        """Convert SubtitleEntry list to SRT format string."""
        lines: List[str] = []
        for entry in entries:
            lines.append(str(entry.index + 1))
            lines.append(
                f"{_fmt_time(entry.start_time)} --> {_fmt_time(entry.end_time)}"
            )
            lines.append(entry.text)
            lines.append("")  # blank line between entries
        return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    """Format seconds → SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
