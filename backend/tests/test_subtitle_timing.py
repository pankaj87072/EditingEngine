"""
tests/test_subtitle_timing.py
-------------------------------
Unit tests for SubtitleTimingAgent.
"""

import pytest
from agents.subtitle_timing_agent import SubtitleTimingAgent, _fmt_time
from core.exceptions import SubtitleTimingError
from models.schema import AudioResult, ScriptScene, TTSProvider, WordTiming


@pytest.fixture
def agent() -> SubtitleTimingAgent:
    return SubtitleTimingAgent()


@pytest.fixture
def sample_scenes():
    return [
        ScriptScene(
            scene_index=0,
            text="Welcome to our amazing product showcase today.",
            word_count=7,
            estimated_duration=2.8,
        ),
        ScriptScene(
            scene_index=1,
            text="This is the future of mobile technology available now.",
            word_count=9,
            estimated_duration=3.6,
        ),
    ]


@pytest.fixture
def audio_result_no_timings():
    return AudioResult(
        audio_path="/tmp/test_audio.mp3",
        duration=10.0,
        provider=TTSProvider.GOOGLE,
        word_timings=[],
    )


@pytest.fixture
def audio_result_with_timings():
    timings = [
        WordTiming(word="Welcome", start_time=0.0, end_time=0.4),
        WordTiming(word="to", start_time=0.4, end_time=0.6),
        WordTiming(word="our", start_time=0.6, end_time=0.8),
        WordTiming(word="amazing", start_time=0.8, end_time=1.2),
        WordTiming(word="product", start_time=1.2, end_time=1.6),
        WordTiming(word="showcase", start_time=1.6, end_time=2.0),
    ]
    return AudioResult(
        audio_path="/tmp/test_audio.mp3",
        duration=2.0,
        provider=TTSProvider.GOOGLE,
        word_timings=timings,
    )


def test_estimated_subtitles(agent, sample_scenes, audio_result_no_timings):
    entries = agent.run(
        audio_result=audio_result_no_timings,
        scenes=sample_scenes,
    )
    assert len(entries) > 0
    for i, entry in enumerate(entries):
        assert entry.index == i
        assert entry.start_time >= 0
        assert entry.end_time > entry.start_time
        assert entry.text.strip() != ""


def test_provider_word_timings(agent, sample_scenes, audio_result_with_timings):
    entries = agent.run(
        audio_result=audio_result_with_timings,
        scenes=sample_scenes,
    )
    assert len(entries) > 0
    # Entries from provider timings should start at the word's actual timestamp
    assert entries[0].start_time == 0.0


def test_empty_audio_raises(agent, sample_scenes):
    bad_audio = AudioResult(
        audio_path="/tmp/test.mp3",
        duration=0.0,
        provider=TTSProvider.GOOGLE,
    )
    with pytest.raises(SubtitleTimingError):
        agent.run(audio_result=bad_audio, scenes=sample_scenes)


def test_srt_format(agent, sample_scenes, audio_result_no_timings):
    entries = agent.run(
        audio_result=audio_result_no_timings,
        scenes=sample_scenes,
    )
    srt = SubtitleTimingAgent.to_srt(entries)
    assert "00:00:00,000" in srt or "-->" in srt
    assert entries[0].text in srt


def test_fmt_time():
    assert _fmt_time(0.0) == "00:00:00,000"
    assert _fmt_time(61.5) == "00:01:01,500"
    assert _fmt_time(3661.123) == "01:01:01,123"


def test_max_words_per_card(agent, sample_scenes, audio_result_no_timings):
    entries = agent.run(
        audio_result=audio_result_no_timings,
        scenes=sample_scenes,
    )
    for entry in entries:
        assert len(entry.text.split()) <= 4  # _MAX_WORDS_PER_CARD
