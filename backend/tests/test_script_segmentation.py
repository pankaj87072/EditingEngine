"""
tests/test_script_segmentation.py
-----------------------------------
Unit tests for ScriptSegmentationAgent.
"""

import pytest
from agents.script_segmentation_agent import ScriptSegmentationAgent
from core.exceptions import ScriptSegmentationError


@pytest.fixture
def agent() -> ScriptSegmentationAgent:
    return ScriptSegmentationAgent()


def test_basic_segmentation(agent, sample_script):
    scenes = agent.run(script=sample_script)
    assert len(scenes) >= 1
    for scene in scenes:
        assert scene.text.strip() != ""
        assert scene.word_count > 0
        assert scene.estimated_duration > 0


def test_empty_script_raises(agent):
    with pytest.raises(ScriptSegmentationError):
        agent.run(script="")


def test_whitespace_script_raises(agent):
    with pytest.raises(ScriptSegmentationError):
        agent.run(script="   \n  ")


def test_keywords_extracted(agent, sample_script):
    scenes = agent.run(script=sample_script)
    # At least some scenes should have keywords
    has_keywords = any(len(s.keywords) > 0 for s in scenes)
    assert has_keywords


def test_scene_index_sequential(agent, sample_script):
    scenes = agent.run(script=sample_script)
    for i, scene in enumerate(scenes):
        assert scene.scene_index == i


def test_duration_estimation(agent):
    # 25 words at 2.5 wps = 10s
    script = "word " * 25
    scenes = agent.run(script=script.strip())
    total_duration = sum(s.estimated_duration for s in scenes)
    assert abs(total_duration - 10.0) < 1.0


def test_long_script_splits_scenes(agent):
    long_script = ". ".join(["This is a long sentence with many words in it"] * 20)
    scenes = agent.run(script=long_script)
    # Should produce multiple scenes
    assert len(scenes) > 1


def test_metadata_stored(agent, sample_script):
    agent.run(script=sample_script)
    meta = agent.get_metadata()
    assert "scene_count" in meta
    assert "total_estimated_duration" in meta
    assert meta["scene_count"] >= 1
