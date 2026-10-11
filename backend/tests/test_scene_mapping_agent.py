"""
tests/test_scene_mapping_agent.py
----------------------------------
Unit tests for SceneMappingAgent.
Uses tmp_path fixture so no real clips are needed on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.scene_mapping_agent import SceneMappingAgent
from core.exceptions import SceneMappingError
from models.schema import ScriptScene


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def agent() -> SceneMappingAgent:
    return SceneMappingAgent()


@pytest.fixture
def scenes() -> list[ScriptScene]:
    return [
        ScriptScene(
            scene_index=i,
            text=f"Scene {i} text content goes here for testing purposes.",
            word_count=9,
            estimated_duration=3.6,
        )
        for i in range(5)
    ]


@pytest.fixture
def clip_files(tmp_path: Path) -> list[str]:
    """Create dummy mp4 files on disk (content doesn't matter for mapping tests)."""
    paths = []
    for i in range(3):
        p = tmp_path / f"clip_{i}.mp4"
        p.write_bytes(b"\x00" * 512)
        paths.append(str(p))
    return paths


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_no_clips_raises(agent, scenes):
    with pytest.raises(SceneMappingError, match="No video clips"):
        agent.run(scenes=scenes, clip_paths=[])


def test_no_scenes_raises(agent, clip_files):
    with pytest.raises(SceneMappingError, match="No scenes"):
        agent.run(scenes=[], clip_paths=clip_files)


def test_nonexistent_clips_raises(agent, scenes):
    """If all clip paths are invalid, agent should raise SceneMappingError."""
    with pytest.raises(SceneMappingError, match="None of the provided"):
        agent.run(scenes=scenes, clip_paths=["/nonexistent/clip.mp4"])


def test_mapping_count_equals_scene_count(agent, scenes, clip_files):
    """One mapping must be produced per scene regardless of clip count."""
    # Patch _probe_duration so we don't need real FFmpeg
    with patch.object(agent, "_probe_duration", return_value=5.0):
        mappings = agent.run(scenes=scenes, clip_paths=clip_files)

    assert len(mappings) == len(scenes)


def test_scene_index_preserved(agent, scenes, clip_files):
    """Each mapping's scene_index must match the corresponding scene."""
    with patch.object(agent, "_probe_duration", return_value=5.0):
        mappings = agent.run(scenes=scenes, clip_paths=clip_files)

    for scene, mapping in zip(scenes, mappings):
        assert mapping.scene_index == scene.scene_index


def test_no_consecutive_repeat_clips(agent, scenes, clip_files):
    """
    With >1 clip available, no two consecutive mappings should use
    the same clip file (the no-repeat rule).
    """
    with patch.object(agent, "_probe_duration", return_value=5.0):
        mappings = agent.run(scenes=scenes, clip_paths=clip_files)

    for i in range(1, len(mappings)):
        assert mappings[i].clip_path != mappings[i - 1].clip_path, (
            f"Consecutive repeat at index {i}: {mappings[i].clip_path}"
        )


def test_single_clip_maps_all_scenes(agent, scenes, tmp_path):
    """With only one clip, every scene must map to that clip."""
    single = tmp_path / "only.mp4"
    single.write_bytes(b"\x00" * 100)

    with patch.object(agent, "_probe_duration", return_value=6.0):
        mappings = agent.run(scenes=scenes, clip_paths=[str(single)])

    assert all(m.clip_path == str(single) for m in mappings)


def test_clip_duration_stored(agent, scenes, clip_files):
    """Probed clip duration should be stored in the mapping."""
    FAKE_DURATION = 7.5
    with patch.object(agent, "_probe_duration", return_value=FAKE_DURATION):
        mappings = agent.run(scenes=scenes, clip_paths=clip_files)

    for m in mappings:
        assert m.clip_duration == FAKE_DURATION


def test_scene_text_stored_in_mapping(agent, scenes, clip_files):
    """Mapping must carry the scene's text for downstream use."""
    with patch.object(agent, "_probe_duration", return_value=5.0):
        mappings = agent.run(scenes=scenes, clip_paths=clip_files)

    for scene, mapping in zip(scenes, mappings):
        assert mapping.scene_text == scene.text


def test_metadata_recorded(agent, scenes, clip_files):
    with patch.object(agent, "_probe_duration", return_value=5.0):
        agent.run(scenes=scenes, clip_paths=clip_files)

    meta = agent.get_metadata()
    assert meta["total_mappings"] == len(scenes)


def test_invalid_clips_filtered_out(agent, scenes, tmp_path):
    """Mix of valid + invalid paths — only valid clips are used."""
    valid = tmp_path / "real.mp4"
    valid.write_bytes(b"\x00" * 100)

    mixed = [str(valid), "/does/not/exist.mp4", "/also/fake.mp4"]

    with patch.object(agent, "_probe_duration", return_value=5.0):
        mappings = agent.run(scenes=scenes, clip_paths=mixed)

    # All mappings should reference only the valid clip
    assert all(m.clip_path == str(valid) for m in mappings)
