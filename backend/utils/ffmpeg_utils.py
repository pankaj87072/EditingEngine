"""
utils/ffmpeg_utils.py
----------------------
Low-level FFmpeg / FFprobe command builders.
All subprocess calls to FFmpeg are centralised here.

This module is intentionally stateless — pure functions only.
Agents call these functions; they do NOT call FFmpeg directly.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from core.config import settings
from core.exceptions import VideoCompositionError
from core.logging import get_logger

logger = get_logger("FFmpegUtils")

# ── Helper ────────────────────────────────────────────────────────────────────

def _run(cmd: List[str], description: str = "") -> subprocess.CompletedProcess:
    """
    Execute an FFmpeg command.
    Raises VideoCompositionError if the process exits non-zero.
    """
    logger.debug(f"FFmpeg [{description}]: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5-minute hard timeout per operation
    )
    if result.returncode != 0:
        raise VideoCompositionError(
            f"FFmpeg failed [{description}]: {result.stderr[-500:]}"
        )
    return result


# ── Clip preparation ──────────────────────────────────────────────────────────

_CROP_X = {"left": "0", "center": "(iw-ow)/2", "right": "iw-ow"}


def scale_clip_to_vertical(
    input_path: str,
    output_path: str,
    start: float = 0.0,
    duration: Optional[float] = None,
    crop: str = "center",
    source_duration: Optional[float] = None,
) -> str:
    """
    Scale and crop a clip to 9:16 vertical format (1080×1920).
    Uses scale + crop to fill the frame without black bars.
    """
    w = settings.VIDEO_WIDTH
    h = settings.VIDEO_HEIGHT

    # scale=w*2:h*2 ensures we have enough pixels before crop
    crop_x = _CROP_X.get(crop, _CROP_X["center"])
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:{crop_x}:(ih-oh)/2"
    )

    # Optional per-scene trim. If the scene needs more footage than the clip has
    # left after `start`, loop the clip rather than freezing the last frame.
    pre: List[str] = []
    post: List[str] = []
    if duration is not None:
        avail = (source_duration if source_duration is not None else _get_duration(input_path)) - start
        if start > 0:
            pre += ["-ss", f"{start:.3f}"]
        if duration > avail + 0.05:
            pre = ["-stream_loop", "-1"]          # loop from the beginning
        post += ["-t", f"{duration:.3f}"]

    cmd = [
        "ffmpeg", "-y",
        *pre,
        "-i", input_path,
        "-vf", scale_filter,
        *post,
        "-r", str(settings.VIDEO_FPS),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-an",           # drop audio from source clips
        output_path,
    ]
    _run(cmd, "scale_clip")
    return output_path


def apply_ken_burns(input_path: str, output_path: str, duration: float, zoom: Optional[float] = None) -> str:
    """
    Apply Ken Burns (slow zoom-in) effect to a clip.
    Uses the zoompan filter with per-frame zoom calculation.
    """
    w = settings.VIDEO_WIDTH
    h = settings.VIDEO_HEIGHT
    fps = settings.VIDEO_FPS
    zoom = zoom if zoom is not None else settings.ZOOM_INTENSITY
    total_frames = max(1, int(duration * fps))

    # IMPORTANT: d=1 -> one output frame per input frame, so the video keeps playing.
    # (d=<all frames> repeated the FIRST frame for the whole clip.) Zoom is driven by `on`.
    zoom_filter = (
        f"scale={w * 2}:{h * 2},"
        f"zoompan="
        f"z='1+({zoom}-1)*min(on/{total_frames},1)':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d=1:"
        f"s={w}x{h}:"
        f"fps={fps}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", zoom_filter,
        "-t", str(duration),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-an",
        output_path,
    ]
    _run(cmd, "ken_burns")
    return output_path


# ── Transitions ───────────────────────────────────────────────────────────────

def add_fade_transition(input_path: str, output_path: str, duration: float) -> str:
    """
    Add fade-in at start and fade-out at end of a clip.
    duration: length of the fade in seconds.
    """
    try:
        total = _get_duration(input_path)
    except Exception:
        total = 5.0

    fade_out_start = max(0, total - duration)

    fade_filter = (
        f"fade=t=in:st=0:d={duration},"
        f"fade=t=out:st={fade_out_start:.3f}:d={duration}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", fade_filter,
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-an",
        output_path,
    ]
    _run(cmd, "fade_transition")
    return output_path


def create_crossfade_concat(
    clip_paths: List[str],
    output_path: str,
    fade_duration: float = 0.5,
) -> str:
    """
    Concatenate multiple clips with crossfade transitions between them.

    Uses the xfade filter chain:
    [0][1]xfade=transition=fade:duration=0.5:offset=<clip1_end - 0.5>[v01];
    [v01][2]xfade=...
    """
    if len(clip_paths) == 1:
        # Nothing to crossfade — copy single clip
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_paths[0],
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-an", output_path,
        ]
        _run(cmd, "single_clip_copy")
        return output_path

    # Build input flags
    inputs: List[str] = []
    for p in clip_paths:
        inputs += ["-i", p]

    # Probe durations
    durations = [_get_duration(p) for p in clip_paths]

    # Build xfade filter chain
    filter_parts: List[str] = []
    prev_label = "[0:v]"
    cumulative_offset = 0.0

    for i in range(1, len(clip_paths)):
        cumulative_offset += durations[i - 1] - fade_duration
        next_label = f"[v{i}]" if i < len(clip_paths) - 1 else "[vout]"
        filter_parts.append(
            f"{prev_label}[{i}:v]xfade=transition=fade:"
            f"duration={fade_duration}:offset={cumulative_offset:.3f}{next_label}"
        )
        prev_label = f"[v{i}]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-an", output_path,
    ]
    _run(cmd, "crossfade_concat")
    return output_path


# ── Subtitle overlay ──────────────────────────────────────────────────────────

# caption_style -> (font size, outline width, bold)
CAPTION_PRESETS = {
    "classic": (None, None, 0),   # None = use settings.* (previous behaviour)
    "bold":    (84, 5, 1),
    "soft":    (52, 2, 0),
}


def prepare_subtitles(
    srt_path: str,
    position: str = "bottom",
    caption_style: str = "classic",
    emphasis: Optional[List[str]] = None,
    punch: bool = False,
    zones: Optional[List[Tuple[float, float, int]]] = None,
) -> str:
    """
    Convert the SRT to an ASS file on a real 1080x1920 canvas (ffmpeg lays SRT out on 384x288, which makes
    FontSize/MarginV ~6x too big), apply emphasis / pop animation / per-card alignment overrides, and
    return the `subtitles=` filter string to use in any filter graph.
    """
    font = settings.SUBTITLE_FONT
    p_size, p_outline, bold = CAPTION_PRESETS.get(caption_style, CAPTION_PRESETS["classic"])
    font_size = p_size or settings.SUBTITLE_FONT_SIZE
    outline_width = p_outline or settings.SUBTITLE_OUTLINE_WIDTH
    # force_style uses legacy SSA numbering: 2 = bottom-centre, 6 = top-centre, 10 = middle-centre
    alignment, margin_v = {"center": (10, 0), "upper": (6, 260)}.get(position, (2, 200))
    style_str = (
        f"FontName={font},FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"Outline={outline_width},Bold={bold},Alignment={alignment},MarginV={margin_v}"
    )
    ass_path = str(Path(srt_path).with_suffix(".ass"))
    _run(["ffmpeg", "-y", "-i", srt_path, ass_path], "srt_to_ass")
    ass = Path(ass_path).read_text(encoding="utf-8")
    ass = ass.replace("PlayResX: 384", f"PlayResX: {settings.VIDEO_WIDTH}")
    ass = ass.replace("PlayResY: 288", f"PlayResY: {settings.VIDEO_HEIGHT}")
    if zones:
        ass = _apply_zones(ass, zones)
    if emphasis:
        ass = _emphasise_words(ass, emphasis, punch)
    Path(ass_path).write_text(ass, encoding="utf-8")
    return f"subtitles='{_escape_path(ass_path)}':force_style='{style_str}'"


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    position: str = "bottom",
    caption_style: str = "classic",
    emphasis: Optional[List[str]] = None,
    punch: bool = False,
    zones: Optional[List[Tuple[float, float, int]]] = None,
) -> str:
    """Burn captions into an existing video (multi-stage path; the single-pass path uses prepare_subtitles)."""
    sub_filter = prepare_subtitles(srt_path, position, caption_style, emphasis, punch, zones)
    _run(["ffmpeg", "-y", "-i", video_path, "-vf", sub_filter, "-c:v", "libx264", "-crf", "20", "-preset", "fast",
          "-c:a", "copy", output_path], "burn_subtitles")
    return output_path


# ── Audio mux ────────────────────────────────────────────────────────────────

def _emphasise_words(ass: str, words: List[str], punch: bool = False) -> str:
    """Highlight key words (gold, bold) inside ASS Dialogue lines."""
    import re

    clean = sorted({w.strip() for w in words if w and w.strip()}, key=len, reverse=True)
    if not clean:
        return ass
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in clean) + r")\b", re.IGNORECASE)
    out: List[str] = []
    for line in ass.split("\n"):
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)            # the 10th field is the text
            if len(parts) == 10:
                tag = "{\\b1\\c&H00D7FF&" + ("\\fscx100\\fscy100\\t(0,120,\\fscx122\\fscy122)\\t(120,260,\\fscx100\\fscy100)" if punch else "") + "}"
                parts[9] = pattern.sub(lambda m: tag + m.group(1) + "{\\r}", parts[9])
                line = ",".join(parts)
        out.append(line)
    return "\n".join(out)


def _apply_zones(ass: str, zones: List[Tuple[float, float, int]]) -> str:
    """Prefix Dialogue lines that start inside a zone with an {\\anN} alignment override."""
    def secs(ts: str) -> float:
        h, m, sec = ts.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)

    out: List[str] = []
    for line in ass.split("\n"):
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                try:
                    t = secs(parts[1])
                    an = next((z[2] for z in zones if z[0] <= t < z[1]), None)
                except ValueError:
                    an = None
                if an is not None:
                    parts[9] = "{\\an%d}" % an + parts[9]
                    line = ",".join(parts)
        out.append(line)
    return "\n".join(out)


def mux_audio_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    target_duration: Optional[float] = None,
) -> str:
    """
    Combine a (silent) video with an audio track.
    If video is shorter than audio → loop video.
    If audio is shorter than video → trim video.
    """
    video_dur = _get_duration(video_path)
    audio_dur = _get_duration(audio_path)

    if target_duration is None:
        target_duration = audio_dur   # Audio determines final length

    if video_dur < audio_dur:
        # Loop video to match audio length
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", video_path,
            "-i", audio_path,
            "-t", str(target_duration),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "aac", "-b:a", settings.AUDIO_BITRATE,
            "-shortest",
            output_path,
        ]
    else:
        # Trim video to audio duration
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-t", str(target_duration),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "aac", "-b:a", settings.AUDIO_BITRATE,
            output_path,
        ]

    _run(cmd, "mux_audio_video")
    return output_path


# ── Final export ──────────────────────────────────────────────────────────────

def export_final(
    video_path: str,
    output_path: str,
) -> str:
    """
    Re-encode to Instagram-ready MP4:
    - H.264 video, AAC audio
    - faststart flag for web streaming
    - Constrained to 4Mbps
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-c:v", "libx264",
        "-b:v", settings.VIDEO_BITRATE,
        "-maxrate", settings.VIDEO_BITRATE,
        "-bufsize", "8M",
        "-vf", f"scale={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}",
        "-r", str(settings.VIDEO_FPS),
        "-c:a", "aac",
        "-b:a", settings.AUDIO_BITRATE,
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    _run(cmd, "export_final")
    return output_path


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_duration(path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 5.0


def _escape_path(path: str) -> str:
    """Escape path for use in FFmpeg filter strings."""
    return path.replace("\\", "/").replace(":", "\\:")


# ══════════════════════════════════════════════════════════════════════════════
# Plan execution: one pass per shot, then a join-aware concat
# ══════════════════════════════════════════════════════════════════════════════

def _even(n: float) -> int:
    return int(round(n / 2.0)) * 2


def motion_filter(
    motion: str, zoom: float, duration: float, punch_at: Optional[float] = None, flip: bool = False,
) -> Optional[str]:
    """
    zoompan filter string for a motion preset, or None for a static shot.
    Uses d=1 (frames keep flowing) and the output frame counter `on` for all animation.
    """
    w, h, fps = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT, settings.VIDEO_FPS
    n = max(1, int(duration * fps))
    p = f"min(on/{n},1)"
    Z = max(1.0, zoom)
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"
    x, y = cx, cy
    if motion == "static" and punch_at is None:
        return None
    if motion == "pull_out":
        z = f"{Z}-({Z}-1)*{p}"
    elif motion == "dynamic_push":
        z = f"1+({Z}-1)*pow({p},0.6)"
    elif motion == "pan_h":
        z = f"{max(Z, 1.08)}"
        x = f"(iw-iw/zoom)*({'1-' if flip else ''}{p})"
    elif motion == "pan_v":
        z = f"{max(Z, 1.08)}"
        y = f"(ih-ih/zoom)*({'1-' if flip else ''}{p})"
    elif motion == "cinematic_drift":
        z = f"1+({Z}-1)*{p}"
        x = f"(iw-iw/zoom)*(0.35+0.3*{p})"
    elif motion == "punch":
        z = f"1+({Z}-1)*0.5*{p}"
    elif motion == "static":
        z = "1"
    else:                                   # push_in
        z = f"1+({Z}-1)*{p}"
    if punch_at is not None:                # short zoom pop centred on an emphasised word
        f0, win = punch_at * fps, max(3.0, 0.18 * fps)
        z = f"({z})+0.07*max(0,1-abs(on-{f0:.1f})/{win:.1f})"
    pre = settings.ZOOM_PRESCALE
    return (
        f"scale={_even(w * pre)}:{_even(h * pre)}:flags=bicubic,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps}"
    )


def render_shot(
    input_path: str,
    output_path: str,
    *,
    start: float = 0.0,
    duration: float = 3.0,
    speed: float = 1.0,
    crop: str = "center",
    crop_x: Optional[float] = None,
    motion: str = "static",
    zoom: float = 1.0,
    punch_at: Optional[float] = None,
    source_duration: Optional[float] = None,
    flip: bool = False,
) -> str:
    """
    Execute one planned shot in ONE ffmpeg pass:
    trim -> speed -> scale/crop to 1080x1920 (subject-safe) -> motion preset -> encode.
    """
    w, h, fps = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT, settings.VIDEO_FPS
    speed = max(0.5, min(2.0, speed or 1.0))
    src_needed = duration * speed
    avail = (source_duration if source_duration is not None else _get_duration(input_path)) - start

    pre: List[str] = []
    if src_needed > avail + 0.05:
        pre = ["-stream_loop", "-1"]                 # not enough footage: loop from the start
    elif start > 0:
        pre = ["-ss", f"{start:.3f}"]

    x_expr = f"(iw-ow)*{crop_x:.4f}" if crop_x is not None else _CROP_X.get(crop, _CROP_X["center"])
    filters: List[str] = []
    if abs(speed - 1.0) > 1e-3:
        filters.append(f"setpts=PTS/{speed:.4f}")
    filters.append(f"scale={w}:{h}:force_original_aspect_ratio=increase")
    filters.append(f"crop={w}:{h}:{x_expr}:(ih-oh)/2")
    filters.append(f"fps={fps}")
    mf = motion_filter(motion, zoom, duration, punch_at, flip)
    if mf:
        filters.append(mf)
    filters.append("setsar=1,format=yuv420p")

    cmd = [
        "ffmpeg", "-y", *pre, "-i", input_path,
        "-vf", ",".join(filters),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-r", str(fps),
        "-an", output_path,
    ]
    _run(cmd, "render_shot")
    return output_path


def concat_with_joins(
    clip_paths: List[str],
    joins: List[Tuple[str, float]],
    output_path: str,
) -> str:
    """
    Concatenate shots with a per-join transition. joins[i] is the join AFTER clip i:
    ("cut", 0) -> hard cut; ("dissolve"|"smoothleft"|"zoomin"|"fadeblack", seconds) -> xfade.
    Cuts and blends can be mixed in a single filter graph.
    """
    from core.editing_rules import XFADE_NAME

    fps = settings.VIDEO_FPS
    if len(clip_paths) == 1:
        _run(["ffmpeg", "-y", "-i", clip_paths[0], "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-an", output_path], "single_clip_copy")
        return output_path

    inputs: List[str] = []
    for p in clip_paths:
        inputs += ["-i", p]
    durs = [_get_duration(p) for p in clip_paths]

    parts = [f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},format=yuv420p,setsar=1[n{i}]" for i in range(len(clip_paths))]
    cur, cur_dur = "[n0]", durs[0]
    for i in range(1, len(clip_paths)):
        kind, d = joins[i - 1] if i - 1 < len(joins) else ("cut", 0.0)
        d = min(d, durs[i] / 2.5, cur_dur / 2.5)
        out = "[vout]" if i == len(clip_paths) - 1 else f"[c{i}]"
        if kind == "cut" or d < 0.05:
            parts.append(f"{cur}[n{i}]concat=n=2:v=1:a=0,fps={fps},format=yuv420p,setsar=1{out}")  # fps= resets the timebase xfade needs
            cur_dur += durs[i]
        else:
            parts.append(
                f"{cur}[n{i}]xfade=transition={XFADE_NAME.get(kind, 'fade')}:duration={d:.3f}:offset={cur_dur - d:.3f}{out}"
            )
            cur_dur += durs[i] - d
        cur = out
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(parts), "-map", "[vout]",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-an", output_path,
    ]
    _run(cmd, "concat_with_joins")
    return output_path


def assemble_narration(items: List[Tuple[str, Optional[float], float]], output_path: str) -> float:
    """
    Join per-scene voice files into ONE narration track (48 kHz mono PCM WAV, audio only).
    items: (file, trim_end_seconds | None, silence_after_seconds). Returns the exact output duration.
    """
    sr = settings.AUDIO_SAMPLE_RATE
    inputs: List[str] = []
    parts: List[str] = []
    for i, (path, trim, gap) in enumerate(items):
        inputs += ["-i", path]
        chain = f"[{i}:a]aresample={sr},aformat=sample_fmts=fltp:channel_layouts=mono"
        if trim:
            chain += f",atrim=end={trim:.3f},asetpts=PTS-STARTPTS"
        if gap > 0.001:
            chain += f",apad=pad_dur={gap:.3f}"
        parts.append(f"{chain}[a{i}]")
    parts.append("".join(f"[a{i}]" for i in range(len(items))) + f"concat=n={len(items)}:v=0:a=1[out]")
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[out]",
          "-c:a", "pcm_s16le", "-ar", str(sr), output_path], "assemble_narration")
    return _get_duration(output_path)


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE-PASS COMPOSITION: one filter graph, one video encode
# ══════════════════════════════════════════════════════════════════════════════

def motion_filter_fast(motion: str, zoom: float, duration: float, punch_at: Optional[float] = None, flip: bool = False) -> Optional[str]:
    """
    Same motion presets as motion_filter(), but built from a per-frame `scale` + `crop` instead of
    zoompan on a 1.5x intermediate. Works on the frame size that is already 1080x1920, so it is much
    cheaper. Returns None for a static shot.
    """
    w, h = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT
    T = max(duration, 0.1)
    Z = max(1.0, zoom)
    p = f"min(t/{T:.3f},1)"
    if motion == "static" and punch_at is None:
        return None
    x_expr, y_expr = "(iw-ow)/2", "(ih-oh)/2"
    if motion == "pull_out":
        z = f"{Z}-({Z}-1)*{p}"
    elif motion == "dynamic_push":
        z = f"1+({Z}-1)*pow({p},0.6)"
    elif motion == "pan_h":
        Zp = max(Z, 1.08)
        z = f"{Zp}"
        x_expr = f"(iw-ow)*({'1-' if flip else ''}{p})"
    elif motion == "pan_v":
        Zp = max(Z, 1.08)
        z = f"{Zp}"
        y_expr = f"(ih-oh)*({'1-' if flip else ''}{p})"
    elif motion == "cinematic_drift":
        z = f"1+({Z}-1)*{p}"
        x_expr = f"(iw-ow)*(0.35+0.3*{p})"
    elif motion == "punch":
        z = f"1+({Z}-1)*0.5*{p}"
    elif motion == "static":
        z = "1"
    else:                                   # push_in
        z = f"1+({Z}-1)*{p}"
    if punch_at is not None:
        z = f"({z})+0.07*max(0,1-abs(t-{punch_at:.3f})/0.18)"
    return (
        f"scale=w='trunc({w}*({z})/2)*2':h='trunc({h}*({z})/2)*2':eval=frame:flags=bicubic,"
        f"crop=w={w}:h={h}:x='{x_expr}':y='{y_expr}'"
    )


def _bufsize(maxrate: str) -> str:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM]?)", maxrate.strip())
    return f"{float(m.group(1)) * 2:g}{m.group(2)}" if m else "24M"


def compose_single_pass(
    *,
    shots: List[dict],
    audio_path: str,
    subtitle_filter: Optional[str],
    output_path: str,
    music_path: Optional[str] = None,
) -> str:
    """
    Build the whole Reel in ONE ffmpeg run: per-shot trim -> speed -> smart crop -> motion, hard cuts and
    blends in one graph, captions, voiceover (normalised) with optional ducked music, then ONE H.264/AAC
    encode with faststart. Nothing is written to disk in between.

    Each shot dict: clip, start, duration, speed, crop, crop_x, motion, zoom, punch_at, source_duration,
                    flip, join (kind after this shot), join_dur.
    """
    from core.editing_rules import XFADE_NAME

    w, h, fps, sr = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT, settings.VIDEO_FPS, settings.AUDIO_SAMPLE_RATE
    inputs: List[str] = []
    parts: List[str] = []
    for i, sh in enumerate(shots):
        d, speed = sh["duration"], max(0.5, min(2.0, sh.get("speed") or 1.0))
        src = d * speed
        avail = (sh.get("source_duration") or _get_duration(sh["clip"])) - sh["start"]
        if src > avail + 0.05:
            inputs += ["-stream_loop", "-1", "-t", f"{src:.3f}", "-i", sh["clip"]]     # not enough footage: loop
        elif sh["start"] > 0:
            inputs += ["-ss", f"{sh['start']:.3f}", "-t", f"{src:.3f}", "-i", sh["clip"]]
        else:
            inputs += ["-t", f"{src:.3f}", "-i", sh["clip"]]
        crop_x = sh.get("crop_x")
        x = f"(iw-ow)*{crop_x:.4f}" if crop_x is not None else _CROP_X.get(sh.get("crop", "center"), _CROP_X["center"])
        chain = [f"setpts=(PTS-STARTPTS)/{speed:.4f}", f"fps={fps}",
                 f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic", f"crop={w}:{h}:{x}:(ih-oh)/2"]
        mf = (motion_filter_fast if settings.MOTION_ENGINE == "scale" else motion_filter)(
            sh.get("motion", "static"), sh.get("zoom", 1.0), d, sh.get("punch_at"), sh.get("flip", False))
        if mf:
            chain.append(mf)
        chain += [f"trim=duration={d:.3f}", "setpts=PTS-STARTPTS", "setsar=1", "format=yuv420p"]
        parts.append(f"[{i}:v]" + ",".join(chain) + f"[v{i}]")

    # joins: hard cuts and blends mixed in one chain
    cur, cur_dur = "[v0]", shots[0]["duration"]
    for i in range(1, len(shots)):
        kind, jd = shots[i - 1].get("join", "cut"), shots[i - 1].get("join_dur", 0.0)
        jd = min(jd, shots[i]["duration"] / 2.5, cur_dur / 2.5)
        out = f"[j{i}]"
        if kind == "cut" or jd < 0.05:
            parts.append(f"{cur}[v{i}]concat=n=2:v=1:a=0,fps={fps},format=yuv420p,setsar=1{out}")
            cur_dur += shots[i]["duration"]
        else:
            parts.append(f"{cur}[v{i}]xfade=transition={XFADE_NAME.get(kind, 'fade')}:duration={jd:.3f}:offset={cur_dur - jd:.3f}{out}")
            cur_dur += shots[i]["duration"] - jd
        cur = out
    total = cur_dur
    vlabel = cur
    if subtitle_filter:
        parts.append(f"{vlabel}{subtitle_filter}[vs]")
        vlabel = "[vs]"

    # audio: narration (+ optional ducked music)
    n_idx = len(shots)
    inputs += ["-i", audio_path]
    nar = f"[{n_idx}:a]aresample={sr},aformat=channel_layouts=stereo"
    if settings.AUDIO_NORMALIZE:
        nar += f",loudnorm=I=-16:TP=-1.5:LRA=11,aresample={sr}"       # loudnorm resamples to 192 kHz internally
    nar += f",apad=whole_dur={total:.3f}"
    if music_path:
        inputs += ["-stream_loop", "-1", "-i", music_path]
        m_idx = n_idx + 1
        parts.append(nar + ",asplit=2[n1][n2]")
        parts.append(f"[{m_idx}:a]aresample={sr},aformat=channel_layouts=stereo,volume={settings.MUSIC_VOLUME}[mus]")
        parts.append("[mus][n1]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[duck]")
        parts.append("[n2][duck]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        parts.append(nar + "[aout]")

    graph = ";".join(parts)
    cmd = ["ffmpeg", "-y", *inputs]
    if len(graph) > 12000:                                    # keep the command line short (Windows limit)
        script = Path(output_path).with_suffix(".graph.txt")
        script.write_text(graph, encoding="utf-8")
        cmd += ["-filter_complex_script", str(script)]
    else:
        cmd += ["-filter_complex", graph]
    cmd += [
        "-map", vlabel, "-map", "[aout]",
        "-c:v", "libx264", "-preset", settings.VIDEO_PRESET, "-crf", str(settings.VIDEO_CRF),
        "-maxrate", settings.VIDEO_MAXRATE, "-bufsize", _bufsize(settings.VIDEO_MAXRATE),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", settings.AUDIO_BITRATE, "-ar", str(sr),
        "-movflags", "+faststart", "-t", f"{total:.3f}", output_path,
    ]
    _run(cmd, "compose_single_pass")
    return output_path
