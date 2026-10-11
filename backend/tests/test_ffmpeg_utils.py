"""
tests/test_ffmpeg_utils.py
---------------------------
Unit tests for utils/ffmpeg_utils.py.

All subprocess / FFmpeg calls are mocked so tests run without
FFmpeg installed. Tests validate:
  - Correct command construction
  - Error wrapping
  - Duration fallback behaviour
"""

from __future__ import annotations

import pathlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core.exceptions import VideoCompositionError
from utils import ffmpeg_utils


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_completed_process(returncode=0, stdout="", stderr=""):
    """Build a fake subprocess.CompletedProcess object."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


# ── _run ──────────────────────────────────────────────────────────────────────

class TestRunHelper:
    def test_success_returns_process(self):
        with patch("utils.ffmpeg_utils.subprocess.run") as mock_run:
            mock_run.return_value = make_completed_process(returncode=0)
            result = ffmpeg_utils._run(["ffmpeg", "-version"], "test")
            assert result.returncode == 0

    def test_nonzero_raises_video_composition_error(self):
        with patch("utils.ffmpeg_utils.subprocess.run") as mock_run:
            mock_run.return_value = make_completed_process(
                returncode=1,
                stderr="Error: codec not found",
            )
            with pytest.raises(VideoCompositionError) as exc_info:
                ffmpeg_utils._run(["ffmpeg", "-bad-flag"], "bad call")
            assert "bad call" in str(exc_info.value)


# ── scale_clip_to_vertical ────────────────────────────────────────────────────

class TestScaleClip:
    def test_calls_ffmpeg_with_correct_resolution(self, tmp_path):
        out = str(tmp_path / "scaled.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run:
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.scale_clip_to_vertical("input.mp4", out)

        cmd = mock_run.call_args.args[0]
        # Must contain the target resolution
        filter_str = " ".join(cmd)
        assert "1080" in filter_str
        assert "1920" in filter_str

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "scaled.mp4")
        with patch("utils.ffmpeg_utils._run"):
            result = ffmpeg_utils.scale_clip_to_vertical("input.mp4", out)
        assert result == out


# ── add_fade_transition ───────────────────────────────────────────────────────

class TestFadeTransition:
    def test_fade_filter_in_command(self, tmp_path):
        out = str(tmp_path / "faded.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run, \
             patch("utils.ffmpeg_utils._get_duration", return_value=5.0):
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.add_fade_transition("in.mp4", out, duration=0.5)

        cmd = mock_run.call_args.args[0]
        filter_str = " ".join(cmd)
        assert "fade=t=in" in filter_str
        assert "fade=t=out" in filter_str

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "faded.mp4")
        with patch("utils.ffmpeg_utils._run"), \
             patch("utils.ffmpeg_utils._get_duration", return_value=5.0):
            result = ffmpeg_utils.add_fade_transition("in.mp4", out, 0.5)
        assert result == out


# ── apply_ken_burns ───────────────────────────────────────────────────────────

class TestKenBurns:
    def test_zoompan_filter_present(self, tmp_path):
        out = str(tmp_path / "zoomed.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run:
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.apply_ken_burns("in.mp4", out, duration=5.0)

        cmd = mock_run.call_args.args[0]
        assert any("zoompan" in arg for arg in cmd)

    def test_duration_controls_total_frames(self, tmp_path):
        """
        The zoom is paced over duration × fps frames. d must be 1: with d=<all frames> zoompan repeated
        the FIRST frame for the whole clip (the video froze), so the zoom ramp is driven by `on` instead.
        """
        from core.config import settings
        out = str(tmp_path / "zoomed.mp4")
        duration = 6.0
        expected_frames = int(duration * settings.VIDEO_FPS)

        with patch("utils.ffmpeg_utils._run") as mock_run:
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.apply_ken_burns("in.mp4", out, duration=duration)

        cmd_str = " ".join(mock_run.call_args.args[0])
        assert ":d=1:" in cmd_str
        assert f"on/{expected_frames}" in cmd_str


# ── mux_audio_video ───────────────────────────────────────────────────────────

class TestMuxAudioVideo:
    def test_maps_both_streams(self, tmp_path):
        out = str(tmp_path / "muxed.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run, \
             patch("utils.ffmpeg_utils._get_duration", side_effect=[10.0, 12.0]):
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.mux_audio_video("video.mp4", "audio.mp3", out)

        cmd = mock_run.call_args.args[0]
        cmd_str = " ".join(cmd)
        # Both video and audio streams must be mapped
        assert "0:v:0" in cmd_str
        assert "1:a:0" in cmd_str

    def test_loops_video_when_shorter_than_audio(self, tmp_path):
        """If video < audio, -stream_loop should be in the command."""
        out = str(tmp_path / "muxed.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run, \
             patch("utils.ffmpeg_utils._get_duration", side_effect=[3.0, 12.0]):
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.mux_audio_video("short.mp4", "long.mp3", out)

        cmd_str = " ".join(mock_run.call_args.args[0])
        assert "stream_loop" in cmd_str


# ── burn_subtitles ────────────────────────────────────────────────────────────

class TestBurnSubtitles:
    def test_subtitles_filter_in_command(self, tmp_path):
        srt = tmp_path / "subs.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        out = str(tmp_path / "subbed.mp4")

        def fake_run(cmd, label=""):
            # first call is the SRT -> ASS conversion; emulate ffmpeg's 384x288 output
            if cmd[-1].endswith(".ass"):
                pathlib.Path(cmd[-1]).write_text("PlayResX: 384\r\nPlayResY: 288\r\n", encoding="utf-8")
            return make_completed_process()

        with patch("utils.ffmpeg_utils._run", side_effect=fake_run) as mock_run:
            ffmpeg_utils.burn_subtitles("video.mp4", str(srt), out, position="center", caption_style="bold")

        cmd_str = " ".join(mock_run.call_args.args[0])
        assert "subtitles=" in cmd_str
        assert "Alignment=10" in cmd_str          # middle-centre (legacy SSA numbering)
        assert "Bold=1" in cmd_str
        ass = (tmp_path / "subs.ass").read_text()
        assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass  # real output canvas


# ── export_final ──────────────────────────────────────────────────────────────

class TestExportFinal:
    def test_faststart_flag_present(self, tmp_path):
        out = str(tmp_path / "final.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run:
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.export_final("input.mp4", out)

        cmd_str = " ".join(mock_run.call_args.args[0])
        assert "faststart" in cmd_str

    def test_yuv420p_pixel_format(self, tmp_path):
        out = str(tmp_path / "final.mp4")
        with patch("utils.ffmpeg_utils._run") as mock_run:
            mock_run.return_value = make_completed_process()
            ffmpeg_utils.export_final("input.mp4", out)

        cmd_str = " ".join(mock_run.call_args.args[0])
        assert "yuv420p" in cmd_str


# ── _get_duration fallback ────────────────────────────────────────────────────

class TestGetDuration:
    def test_returns_probed_duration(self):
        with patch("utils.ffmpeg_utils.subprocess.run") as mock_run:
            mock_run.return_value = make_completed_process(stdout="7.500000\n")
            dur = ffmpeg_utils._get_duration("video.mp4")
        assert dur == 7.5

    def test_falls_back_to_5_on_bad_output(self):
        with patch("utils.ffmpeg_utils.subprocess.run") as mock_run:
            mock_run.return_value = make_completed_process(stdout="N/A\n")
            dur = ffmpeg_utils._get_duration("video.mp4")
        assert dur == 5.0
