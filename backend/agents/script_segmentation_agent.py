"""
agents/script_segmentation_agent.py
-------------------------------------
ScriptSegmentationAgent
-----------------------
Responsibility:
  - Receive raw script text.
  - Split it into logical scenes (sentences / natural pause groups).
  - Estimate duration of each scene based on word count.
  - Extract keywords from each scene for clip matching.

Input kwargs:
    script (str): Raw script text from the user.

Returns:
    List[ScriptScene]
"""

from __future__ import annotations

import re
from typing import List

from agents.base_agent import BaseAgent
from core.config import settings
from core.exceptions import ScriptSegmentationError
from agents.delivery import has_directives, split_directive_blocks
from agents.script_profile import enrich_scenes
from models.schema import ScriptScene


class ScriptSegmentationAgent(BaseAgent):
    agent_name = "ScriptSegmentationAgent"

    # Sentence-boundary split: end of sentence + optional whitespace
    _SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')

    def _execute(self, *, script: str) -> List[ScriptScene]:  # type: ignore[override]
        if not script or not script.strip():
            raise ScriptSegmentationError("Script text is empty.")

        # Scripts with "[Excited, energetic]" style directions: each direction block becomes its own
        # scene (emotion never bleeds across blocks) and the direction itself is never spoken/captioned.
        directed = has_directives(script)
        if directed:
            units = []
            for delivery, block_text in split_directive_blocks(script):
                est = self._estimate_duration(len(block_text.split()))
                texts = [block_text] if est <= settings.MAX_SCENE_DURATION else self._group_sentences(
                    self._split_into_sentences(block_text))
                units += [(t, delivery) for t in texts]
            if not units:
                raise ScriptSegmentationError("Script contains only directions and no spoken text.")
            self._log_step(f"Script directions found: {sum(1 for _, d in units if d)} directed scene(s)")
        else:
            raw_sentences = self._split_into_sentences(script.strip())
            self._log_step(f"Raw sentences extracted: {len(raw_sentences)}")
            # Group short sentences so each scene is ≥ MIN_SCENE_DURATION
            units = [(t, None) for t in self._group_sentences(raw_sentences)]
        self._log_step(f"Scene groups: {len(units)}")

        scenes: List[ScriptScene] = []
        for idx, (text, delivery) in enumerate(units):
            words = text.split()
            word_count = len(words)
            duration = self._estimate_duration(word_count)
            keywords = self._extract_keywords(words)
            scene = ScriptScene(
                scene_index=idx,
                text=text.strip(),
                word_count=word_count,
                estimated_duration=duration,
                keywords=keywords,
                **(delivery or {}),
            )
            scenes.append(scene)
            self._log_step(
                f"Scene {idx}: {word_count} words, ~{duration:.1f}s"
                f"{' [' + scene.emotion + '/' + scene.delivery + ']' if delivery else ''} — {text[:50]}..."
            )
        scenes = enrich_scenes(scenes)   # role / intent / energy / important words (no LLM)
        # A given direction is stronger evidence of intended energy than guessing from the text.
        scenes = [sc.model_copy(update={"energy": round(0.65 * sc.tts_energy + 0.35 * sc.energy, 2)})
                  if sc.tts_energy is not None else sc for sc in scenes]
        self._store_meta("scene_count", len(scenes))
        self._store_meta(
            "total_estimated_duration",
            sum(s.estimated_duration for s in scenes),
        )
        return scenes

    # ── Private helpers ───────────────────────────────────────────────────────

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split on sentence boundaries, keeping each sentence whole."""
        parts = self._SENTENCE_RE.split(text)
        # Remove empty strings
        return [p.strip() for p in parts if p.strip()]

    def _group_sentences(self, sentences: List[str]) -> List[str]:
        """
        Merge consecutive sentences until the group reaches
        MIN_SCENE_DURATION. This prevents 1-word scenes.
        """
        groups: List[str] = []
        buffer = ""

        for sentence in sentences:
            buffer = (buffer + " " + sentence).strip()
            wc = len(buffer.split())
            estimated = self._estimate_duration(wc)

            if estimated >= settings.MIN_SCENE_DURATION:
                # Check we haven't exceeded max
                if estimated <= settings.MAX_SCENE_DURATION:
                    groups.append(buffer)
                    buffer = ""
                else:
                    # Scene is too long — split at MAX boundary
                    chunks = self._split_long_scene(buffer)
                    groups.extend(chunks[:-1])
                    buffer = chunks[-1] if chunks else ""

        # Flush remaining text
        if buffer.strip():
            if groups:
                # Append leftover to last group rather than making a tiny scene
                groups[-1] = groups[-1] + " " + buffer
            else:
                groups.append(buffer)

        return groups

    def _split_long_scene(self, text: str) -> List[str]:
        """
        Break a too-long text into chunks of ≤ MAX_SCENE_DURATION.
        Splits on commas or natural word boundaries.
        """
        max_words = int(settings.MAX_SCENE_DURATION * settings.WORDS_PER_SECOND)
        words = text.split()
        chunks: List[str] = []

        while words:
            chunk_words = words[:max_words]
            words = words[max_words:]
            chunks.append(" ".join(chunk_words))

        return chunks

    def _estimate_duration(self, word_count: int) -> float:
        """Estimate reading/speaking time in seconds."""
        return round(word_count / settings.WORDS_PER_SECOND, 2)

    def _extract_keywords(self, words: List[str]) -> List[str]:
        """
        Simple keyword extraction: keep words longer than 4 chars,
        remove common stopwords, return unique lowercase list.
        """
        stopwords = {
            "this", "that", "with", "from", "have", "been", "will",
            "they", "their", "there", "when", "what", "which", "about",
            "your", "into", "some", "just", "than", "then", "also",
        }
        keywords = [
            w.lower().strip(".,!?;:\"'")
            for w in words
            if len(w) > 4 and w.lower() not in stopwords
        ]
        # De-duplicate while preserving order
        seen = set()
        unique: List[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:8]  # Top 8 keywords per scene
