# AutoVideoGen

Script + your own video clips → analysis → editing plan → FFmpeg → a finished 1080×1920 vertical Reel.
**The AI never generates footage and never touches video.** The rule engine builds a complete edit on its own; AI is an optional second layer that refines it.

```
backend/    FastAPI + FFmpeg (your original backend, extended additively)
frontend/   React + TypeScript + Vite + Tailwind + TanStack Query
```

## 1. Run it

```bash
# backend (Python 3.10+, FFmpeg + ffprobe on PATH; Redis optional → thread-worker fallback)
cd backend && pip install -r requirements.txt && cp .env.example .env
uvicorn main:app --reload --port 8000

# frontend
cd frontend && npm install && cp .env.example .env && npm run dev      # http://localhost:5173

# tests
cd backend && python -m pytest -q          # 213 tests; real-FFmpeg tests skip if ffmpeg is missing
```

**Nothing below is required to get a finished Reel.** With no API key, everything runs on rules.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_URL` (frontend) | `http://localhost:8000` | Backend URL |
| `ANTHROPIC_API_KEY` | empty | Enables the optional AI planner / vision |
| `PLANNER_ENABLED` / `PLANNER_MODEL` / `PLANNER_TIMEOUT` / `PLANNER_MAX_SHOTS` | `true` / haiku-4-5 / `25` / `40` | AI planner switch, model, timeout, cost cap (no AI call above N shots) |
| `VISION_ENABLED` / `VISION_MODEL` / `VISION_MAX_FRAMES` | `false` / haiku-4-5 / `3` | Optional keyframe descriptions |
| `ANALYZER_ENABLED` | `true` | Off = ffprobe-only metadata |
| `ANALYZER_MAX_SECONDS` / `ANALYZER_MAX_SAMPLES` | `90` / `48` | How much of each clip is sampled (sampled frames, never every frame) |
| `ANALYZER_SCENE_DETECT` / `ANALYZER_FACES` / `ANALYZER_SAVE_KEYFRAMES` | `true` | Cut detection; faces (only if OpenCV is installed); keyframe JPEGs |
| `ZOOM_PRESCALE` | `1.5` | Smoothness vs speed of zoom/pan (1.0 faster, 2.0 smoothest) |
| `QUALITY_FULL_DECODE` | `true` | Decode the output once to detect corruption |
| `AUTH_ENABLED` / `AUTH_SECRET` | `false` / auto | Optional accounts |
| `ELEVENLABS_API_KEY` | empty | Only for "Natural voice" |

Every editing number (shot lengths, zoom/speed limits, score weights, thresholds, per-style rules) lives in **`backend/core/editing_rules.py`**.

---

## 2. How the editing engine works

**Principle: build the rule engine first; AI makes it smarter.** Every stage below except the two marked *(optional AI)* is deterministic and works offline.

```
Upload clips
  → VideoAnalyzer            ffprobe + a few sampled low-res frames  (cached per clip)
  → (VisionAgent)            optional AI: ≤3 keyframes/clip → tags, shot type  (cached)  (optional AI)
  → ScriptSegmentationAgent  scenes + role / intent / energy / important words
  → EditingEngine            splits scenes into shots, scores every clip window, picks crop/motion/speed/joins
  → (EditingPlanAgent)       ONE compact AI call refines the plan                (cached)  (optional AI)
  → validate_plan()          clamps/repairs every value, with or without AI
  → Audio / TTS              Google or ElevenLabs → the REAL narration length
  → retime_plan()            shot lengths follow the voiceover (word timings if the provider has them)
  → SubtitleTimingAgent      phrase-based caption cards
  → VideoCompositionAgent    one FFmpeg pass per shot, join-aware concat, captions, mux
  → QualityService           resolution / fps / audio / decode / length / captions report
```

### 2.1 VideoAnalyzer (`agents/video_analyzer.py`)
Pure Python on ~6–48 sampled 96×96 frames per clip (no numpy/OpenCV needed). Per clip it records: duration, rotation-aware orientation, resolution, fps, codec; brightness, contrast, saturation, sharpness, dominant colours; motion per sample, camera-motion estimate (static/pan/tilt/moving/gentle), static vs moving; **scene cuts** (FFmpeg `scene` filter, with a sampled-frame fallback); **usable / boring / repeated ranges**; **best segments**; where the **subject** is (saliency, or faces if OpenCV is installed); near-duplicate frames (perceptual hash) within and across clips; keyframe JPEGs. Cached in `data/analysis_cache/<content-hash>.json` (key = size + head/middle/tail bytes + analyzer version), so a clip is analysed once. If probing or sampling fails the clip gets a neutral `degraded` analysis and the job still completes. A 12 s clip analyses in ~2 s; a cache hit takes milliseconds.

### 2.2 Script understanding (`agents/script_profile.py`)
No LLM. Each scene gets `role` (hook / intro / body / payoff / cta), `intent` (problem, product, action, result, emotion, people, place, screen, food), `energy` 0–1, nouns/verbs (heuristics, there is no POS tagger), `important_words` (caption emphasis) and a visual-intent vocabulary.

### 2.3 EditingEngine (`agents/editing_engine.py`)
For every scene it first decides **how many shots** (style shot length ± intensity; hook shots are short, CTA shots are calm) and cuts them on **phrase boundaries**. For every shot it scores every candidate `(clip, start)` window:

```
score = semantic_match + visual_relevance + motion_match + quality + duration_fit
      + variety + hook_bonus + continuity_bonus + boundary_bonus
      − repetition_penalty − boring_penalty − bad_crop_penalty − straddle_penalty
```
Weights are in `SCORE_WEIGHTS` and each style multiplies some of them (e.g. Storytelling triples continuity, Product Focus raises relevance and crop safety). Candidates start at a 0.5 s grid plus detected cut boundaries; windows that straddle a cut are penalised; windows used before (or in a near-duplicate clip) are heavily penalised, so **reused clips show different sections**. The top 3 alternatives and a plain-English `why` are stored with each shot.

Then, per shot: **smart crop** (`crop_x` positions the 9:16 window over the subject; landscape → portrait without cutting faces/subject), **motion preset** (static, push_in, pull_out, pan_h, pan_v, dynamic_push, punch, cinematic_drift) chosen from the style's pool by role, shot length and how much the footage already moves (it never compounds motion on busy footage), **zoom** (style × intensity × role), **speed** (0.85–1.2: slight speed-up on boring footage, slight slow-down on important high-motion moments), **punch-in** timed on an emphasised word, and the **join** after the shot (hard cut by default, dissolve / slide / zoom-blend where the style wants it, motion transitions only at role changes and at most one per N joins).

### 2.4 Editing styles (what the user picks)
| Style | Shots | Joins | Motion | Captions |
|---|---|---|---|---|
| Clean | 2.2–4.5 s | cuts | subtle push-in | 4 words |
| Social Punchy | 1.1–2.6 s | cuts + occasional slide | strong, punch on emphasis, speed-ups | 3 words, animated emphasis |
| Cinematic | 3.2–6.5 s | dissolves between scenes | slow drift/pan, slight slow-down | 5 words |
| Dynamic | 1.3–3.0 s | cuts + occasional zoom blend | strongest, pans | 3 words, animated emphasis |
| Storytelling | 2.8–5.5 s | dissolves, continuity preferred | gentle | 4 words |
| Product Focus | 2.0–4.0 s | short dissolves | restrained; crop safety weighted high | 4 words |

*Intensity* (Calm / Balanced / Dynamic) scales motion and shot length. *Caption style* (Classic / Bold / Soft) and *position* (Lower third / Middle / Upper safe area) are independent of the editing style. The API's old `transition` field still works as an optional override.

### 2.5 The optional AI planner (`agents/editing_plan_agent.py`)
Used only if `ANTHROPIC_API_KEY` is set, `PLANNER_ENABLED` is true and the plan has ≤ `PLANNER_MAX_SHOTS` shots. **Exactly one call per Reel**, `temperature 0`, strict JSON, cached by input hash.

*What it receives* (compact, no media): editing style and intensity; per clip — duration, orientation, quality, motion, camera, usable ranges, best segments, cut times, subject position, face count and (if vision is on) tags / shot type / description; per shot — role, text, duration, energy, intent, the engine's current choice and its two best alternatives.
*What it returns*: per shot (only those it wants to change) `clip, start, crop, motion, zoom, speed, effect, emphasis`.
*Validation, field by field* — anything invalid keeps the rules value:

| Field | Rule |
|---|---|
| clip / start | must exist; window must lie inside usable footage; rejected if it reuses ≥50 % of an already-used section or repeats the previous clip |
| crop | landscape only, and rejected if it would cut the subject (face, vision or confident saliency) |
| motion | must be a known preset *and* sensible for the shot (length, role, how busy the footage is) |
| zoom / speed | clamped to 1.00–1.25 / 0.85–1.2; speed rejected if the clip has no footage left |
| emphasis | each word must literally appear in the shot's text; max 3 |
| effect | `none` or `punch` only |
| whole reply | not JSON / HTTP error / timeout / wrong shape → the rules plan is returned unchanged |

`validate_plan()` then guarantees every value handed to FFmpeg is valid, with or without AI. The AI refines; it never replaces.

### 2.6 Vision (optional, `agents/vision_agent.py`)
`VISION_ENABLED=true` sends at most 3 small keyframes (320 px JPEG) plus metadata per clip and gets back tags from a fixed vocabulary, shot type, subject position, a hook-worthy time and a caption-safe area. Output is sanitised, cached per clip hash + analyzer version + model, and used by semantic matching, relevance and crop safety. Without it, filename tokens and the measured metrics are used.

### 2.7 Timing, captions, execution
* **Timing:** Scene lengths are first estimated, then `retime_plan()` makes each shot last exactly as long as its words are spoken (TTS word timings when available, otherwise a punctuation-weighted estimate), plus the overlap of the blend that follows, so cuts land on the narration. The voiceover is never stretched.
* **Captions:** phrase-based cards (break on `. , ! ? ; :`, capped per style), highlighted gold + bold emphasis words, optional pop animation, three positions, and cards are moved off the subject when a shot's subject sits where the captions would be.
* **FFmpeg:** each shot is rendered in one pass (trim → speed → smart crop → motion → encode), shots are joined in one filter graph mixing hard cuts and blends, then voiceover is muxed and captions burned in. Output: 1080×1920, 30 fps, H.264, AAC, faststart.
* **Beat markers:** not implemented (no music yet). The engine already cuts on narration/phrase boundaries; supplying beat timestamps would be a new input to the same boundary scoring.

### 2.8 Seeing what it decided
* App: finished Reel → **How this was edited** (per shot: role, clip + time range, motion, zoom, speed, crop, join, highlighted words, the reason) and **Quality check**.
* API: `GET /result/{id}/plan` (also lists analysed clips) · `GET /result/{id}` includes `report` · on disk: `data/outputs/<id>/plan.json`, `report.json`.

---

## 3. Voice, emotion and performance

### 3.1 Script directions control the voice
```
[Excited, energetic]
"Bhai… agar tum bike lover ho, toh ye fact tumhe zaroor pata hona chahiye!"
[Build suspense, slower]
"toh bike ka weight… actually front wheel ki taraf shift hota hai."
```
A line in square brackets is **metadata, never speech or captions**. `agents/delivery.py` turns it into `emotion`, `delivery` (punchy, suspense, authoritative, warning, …), `speech_speed` (0.8–1.2), `tts_energy`, and pauses on the scene; each direction block becomes its own scene so emotion never bleeds across lines. Quotes around a line are stripped; Hinglish text and punctuation (… ? ! ,) are left untouched. The same energy also drives the editing (an excited line is cut and moved harder than a calm one). Scripts without directions behave exactly as before.

* **ElevenLabs** (REST, no SDK): emotion → `stability` / `style` / `speed` (excited = lower stability, higher style, faster; calm/serious/authoritative = steadier), `previous_text`/`next_text` for continuity, and the `/with-timestamps` endpoint so captions use **real character-level timing**. `ELEVENLABS_MODEL=eleven_v3` switches to inline audio tags (`[excited]`).
* **Google** (fallback): Cloud TTS if configured, otherwise gTTS; Indian English accent (`en-IN`, `co.in`), per-scene speaking rate and a small pitch shift for energy. No emotion beyond that (by design).
* **Selection:** `auto` (default) = ElevenLabs if a key is set, else Google. If ElevenLabs fails for *any* scene (after retries on 429/5xx/timeouts), the **whole** narration is regenerated with Google so a video never mixes two voices. Per-scene results are cached in `data/tts_cache`; up to `TTS_MAX_CONCURRENCY` scenes are synthesised in parallel.
* **Timing:** each scene's exact length is known, so word timings are exact (ElevenLabs) or estimated *inside* the scene's real duration (Google). Caption cards never cross a scene boundary.

### 3.2 Why it was slow, and what changed (measured)
Synthetic 10 s 1080p clips, 1 CPU core, stub TTS (no network in the build sandbox), same ~19 s Reel:

| | Before | After |
|---|---|---|
| 1 clip, total | 281.2 s | **52.4 s** |
| 2 clips, total | 275.4 s | **56.7 s** |
| 4 clips, total | 266.2 s | **56.7 s** |
| Composition (FFmpeg) | ~260–266 s | ~45 s |
| Video encodes per Reel | **10** (one per shot, then concat, mux, subtitles, export) | **1** |
| ffmpeg / ffprobe processes | 18 / 10 | 9 / 3 |
| Output | 1080×1920, 30 fps, H.264, AAC 44.1 kHz **mono** | 1080×1920, 30 fps, H.264, AAC 48 kHz **stereo**, loudness-normalised |

Causes: every shot was encoded, then concatenated (encode), muxed (encode), had subtitles burned (encode) and was exported again with the slow default preset (encode) → 6 shots + 4 more full-video encodes, each lossy. Now `compose_single_pass()` builds trim → speed → smart crop → motion → joins → captions → audio mix as **one filter graph and one encode**; if it ever fails the old multi-stage path takes over automatically. Analysis now decodes each clip once (frame sampling and cut detection share a decode), runs clips in parallel (bounded), and only makes keyframe JPEGs when vision needs them. Output validation decodes the file's first and last seconds instead of the whole file (12.0 s → 3.3 s on a 38 s Reel).

Not measured: real TTS latency (no network in the sandbox) and a multi-core machine; on more cores the encode step should shrink further. The test clips are worst-case high-entropy video, so file size hit the 12 Mbps cap (≈27 MB); ordinary footage is far smaller. Set `VIDEO_MAXRATE` / `VIDEO_CRF` to taste.

### 3.3 Music ducking
If `BACKGROUND_MUSIC_PATH` points to a file it is mixed under the narration with a sidechain compressor (music at `MUSIC_VOLUME`, ducked while the voice speaks, back up in pauses). There is no upload UI for music yet.

## 4. API
`POST /generate` (multipart: `script`, `clips[]`, `tts_provider`, `editing_style`, `intensity`, `caption_style`, `subtitle_position` = bottom|center|upper, optional legacy `transition`) · `GET /status/{id}` · `GET /result/{id}` · `/result/{id}/stream` (Range) · `/result/{id}/download` · `/result/{id}/plan` · `GET /jobs` · `POST /jobs/{id}/cancel` · `DELETE /jobs/{id}` · `/auth/*` (only with `AUTH_ENABLED`). All still run through the existing BackgroundWorker / Celery path.

## 5. Bugs found and fixed in the original code
1. **Zoom froze every clip.** `zoompan` was run with `d=<all frames>` on video input, which repeats the *first frame* for the whole clip (verified: a red→blue clip stayed red). Now `d=1` with the zoom driven by the frame counter.
2. **Captions were ~6× too large** (FFmpeg lays SRT out on a 384×288 canvas). Now rendered on a real 1080×1920 canvas.
3. Frame hashes were stored as floats (precision loss, broke duplicate detection and cache round-trips); now hex strings.
4. Script directions like `[Excited]` were read aloud and shown in captions; the TTS call was one request for the whole script with a fixed flat voice setting; ElevenLabs needed an SDK that is not installed by default and its failure did not fall back to Google; captions could straddle a pause between scenes.

## 6. Limits and what is not verified
* **No OCR**, so on-screen text is not detected (`on_screen_text` is always null). Object information only exists if vision is enabled.
* **Faces** use OpenCV Haar cascades *only if OpenCV is installed*; that code path is untested in the build environment (it was not installed). Without it, subject position comes from saliency, a rougher estimate.
* **ElevenLabs is untested against the live API** (REST request/response handling, retries, alignment parsing and the emotion mapping are covered with mocked HTTP only). `eleven_v3` audio tags are also unverified. Hinglish pronunciation depends on the voice you choose: set `ELEVENLABS_VOICE_ID` to an Indian-accent voice.
* **Not exercised for real:** the live AI planner and vision calls (the sandbox had no network; they are unit-tested with mocked replies, including hostile ones), real Google/ElevenLabs TTS, Redis/Celery, TTS word-timing end-to-end (the stubbed TTS returned none), and the UI in real browsers/phones. Two full renders (Social Punchy, Cinematic) completed with real FFmpeg and passed the quality check.
* Style presets are tunable heuristics, not a promise of performance on any platform.
* Cancel stops between steps, not mid-FFmpeg-command. Accounts are minimal (no email verification, reset or rate limiting; CORS is `*`).
