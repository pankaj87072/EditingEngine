# 🎬 AutoVideoGen — Automated AI Video Generation System

> **InVideo-style** vertical video generation engine powered by Python, FastAPI, modular AI agents, FFmpeg, and pluggable TTS — fully production-structured.

---

## 📋 Table of Contents

1. [Project Overview](#-project-overview)
2. [Architecture Explanation](#-architecture-explanation)
3. [Agent Workflow](#-agent-workflow-diagram)
4. [Project Structure](#-project-structure)
5. [Setup Instructions](#-setup-instructions)
6. [Running the System](#-running-the-system)
7. [FFmpeg Installation](#-ffmpeg-installation)
8. [Environment Variables](#-environment-variables)
9. [API Usage (curl examples)](#-api-usage)
10. [Switching TTS Providers](#-switching-tts-providers)
11. [Running Tests](#-running-tests)
12. [Docker Deployment](#-docker-deployment)

---

## 🎯 Project Overview

AutoVideoGen takes a **script** and a set of **short video clips** and automatically produces a 1–2 minute **vertical 9:16 MP4 video** ready for Instagram Reels, TikTok, or YouTube Shorts.

### What it produces

| Feature | Details |
|---------|---------|
| Format | 1080×1920 (9:16 vertical) |
| AI Voiceover | Google TTS or ElevenLabs |
| Subtitles | Word-level timed, center-burned |
| Transitions | Fade, Crossfade, Ken Burns Zoom |
| Output | Instagram-ready H.264 MP4, 4Mbps |

---

## 🏗️ Architecture Explanation

The system follows **Clean Architecture** with strict layer separation:

```
┌──────────────────────────────────────────────────────────┐
│                      FastAPI Layer                        │
│         api/routes/  ←  HTTP requests / responses        │
└─────────────────────────┬────────────────────────────────┘
                          │ dispatches job_id
┌─────────────────────────▼────────────────────────────────┐
│                    Task Queue Layer                       │
│      Celery Worker  or  BackgroundWorker (fallback)       │
└─────────────────────────┬────────────────────────────────┘
                          │ calls
┌─────────────────────────▼────────────────────────────────┐
│                    Service Layer                          │
│              services/video_service.py                   │
│         (Planner + Executor Orchestrator)                │
└──────┬──────────┬──────────┬──────────┬──────────┬───────┘
       │          │          │          │          │
  Agent 1    Agent 2    Agent 3    Agent 4    Agent 5
  Script     Scene      Audio      Subtitle   Video
  Segment    Mapping    Gen        Timing     Compose
       │          │          │          │          │
       └──────────┴──────────┴──────────┴──────────┘
                          │
                   utils/  core/  models/
              (FFmpeg, TTS, Config, Schemas)
```

### Layer Responsibilities

| Layer | Location | Responsibility |
|-------|----------|---------------|
| **Routes** | `api/routes/` | HTTP validation, auth, response shaping |
| **Services** | `services/` | Pipeline orchestration, job management |
| **Agents** | `agents/` | Single-responsibility AI processing units |
| **Utils** | `utils/` | FFmpeg commands, TTS providers (reusable) |
| **Core** | `core/` | Config, logging, exceptions |
| **Models** | `models/` | Pydantic schemas shared across layers |
| **Workers** | `workers/` | Celery task definitions + thread fallback |

---

## 🤖 Agent Workflow Diagram

```
User POST /generate
  │
  │  script + video clips
  ▼
┌─────────────────────────────────────────────┐
│         ScriptSegmentationAgent             │
│  • Split script into logical scenes         │
│  • Estimate duration per scene              │
│  • Extract keywords                         │
│  OUTPUT: List[ScriptScene]                  │
└──────────────────┬──────────────────────────┘
                   │ scenes
                   ▼
┌─────────────────────────────────────────────┐
│           SceneMappingAgent                 │
│  • Map each scene to the best clip          │
│  • Round-robin with no-repeat rule          │
│  • Probe real clip durations (ffprobe)      │
│  OUTPUT: List[SceneMappingResult]           │
└──────────────────┬──────────────────────────┘
                   │ scene_mappings
                   ▼
┌─────────────────────────────────────────────┐
│          AudioGenerationAgent               │
│  • Build full narration text                │
│  • Call TTS provider (Google / ElevenLabs)  │
│  • Return audio path + duration             │
│  OUTPUT: AudioResult                        │
└──────────────────┬──────────────────────────┘
                   │ audio_result
                   ▼
┌─────────────────────────────────────────────┐
│          SubtitleTimingAgent                │
│  • Use word timings if available            │
│  • Otherwise: estimate from audio duration  │
│  • Group words into 4-word cards            │
│  • Generate SRT-compatible entries          │
│  OUTPUT: List[SubtitleEntry]                │
└──────────────────┬──────────────────────────┘
                   │ subtitles
                   ▼
┌─────────────────────────────────────────────┐
│         VideoCompositionAgent               │
│  Stage 1: Scale clips → 1080×1920 (9:16)   │
│  Stage 2: Apply Ken Burns zoom effect       │
│  Stage 3: Add fade/crossfade transitions    │
│  Stage 4: Mux voiceover audio               │
│  Stage 5: Burn subtitles (ffmpeg)           │
│  Stage 6: Export Instagram-ready MP4        │
│  OUTPUT: /data/outputs/{job_id}/final.mp4  │
└─────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
video_gen_system/
│
├── main.py                          # App entry point
├── requirements.txt
├── .env.example
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
│
├── api/
│   ├── __init__.py
│   ├── app.py                       # FastAPI factory + middleware
│   └── routes/
│       ├── __init__.py
│       ├── video_routes.py          # POST /generate, GET /status, GET /result
│       └── health_routes.py         # GET /health
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py                # Abstract base — all agents inherit this
│   ├── script_segmentation_agent.py
│   ├── scene_mapping_agent.py
│   ├── audio_generation_agent.py
│   ├── subtitle_timing_agent.py
│   └── video_composition_agent.py
│
├── services/
│   ├── __init__.py
│   ├── video_service.py             # Pipeline orchestrator (Planner+Executor)
│   ├── job_service.py               # Job CRUD (JSON persistence)
│   └── storage_service.py           # File upload/output management
│
├── core/
│   ├── __init__.py
│   ├── config.py                    # Settings (pydantic-settings)
│   ├── logging.py                   # Colour logger
│   └── exceptions.py                # Custom exception hierarchy
│
├── utils/
│   ├── __init__.py
│   ├── ffmpeg_utils.py              # All FFmpeg commands (stateless functions)
│   └── tts/
│       ├── __init__.py              # TTS factory: get_tts_provider()
│       ├── base_tts.py              # Abstract TTS interface
│       ├── google_tts.py            # Google Cloud TTS + gTTS fallback
│       └── elevenlabs_tts.py        # ElevenLabs TTS
│
├── workers/
│   ├── __init__.py
│   ├── celery_app.py                # Celery task: process_video_job
│   └── background_worker.py         # Thread-pool fallback (no Redis needed)
│
├── models/
│   ├── __init__.py
│   └── schema.py                    # All Pydantic models + enums
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_script_segmentation.py
│   ├── test_subtitle_timing.py
│   └── test_api.py
│
└── data/                            # Runtime data (gitignored)
    ├── uploads/
    └── outputs/
```

---

## ⚙️ Setup Instructions

### Prerequisites

- Python 3.11+
- FFmpeg (see [FFmpeg Installation](#-ffmpeg-installation))
- Redis (for Celery) — optional, system works without it via BackgroundWorker

### Step 1 — Clone and enter the project

```bash
git clone <your-repo-url> video_gen_system
cd video_gen_system
```

### Step 2 — Create and activate a virtual environment

```bash
python -m venv venv

# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment

```bash
cp .env.example .env
# Open .env and fill in your values
```

Minimum required for development (uses gTTS free fallback):
```
TTS_PROVIDER=google
DEBUG=true
```

### Step 5 — Verify FFmpeg is installed

```bash
ffmpeg -version
ffprobe -version
```

---

## 🚀 Running the System

### Option A — No Redis (Development / Quick Start)

The system automatically falls back to a thread-based worker if Celery/Redis is unavailable.

```bash
# Terminal 1 — Start the API server
python main.py
# Server starts at http://localhost:8000
```

That's it. Jobs are processed in background threads automatically.

---

### Option B — With Celery + Redis (Production)

```bash
# Terminal 1 — Start Redis
redis-server

# Terminal 2 — Start FastAPI
python main.py

# Terminal 3 — Start Celery worker
celery -A workers.celery_app worker --loglevel=info --queues=video --concurrency=2
```

---

## 🎞️ FFmpeg Installation

### macOS (Homebrew)

```bash
brew install ffmpeg
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg -y
```

### Windows

1. Download from https://ffmpeg.org/download.html
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your PATH environment variable
4. Verify: `ffmpeg -version`

### Verify subtitle support

```bash
ffmpeg -filters | grep subtitles
# Should show: subtitles    VV->V  Render text subtitles onto input video.
```

---

## 🔑 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_PROVIDER` | `google` | TTS backend: `google` or `elevenlabs` |
| `GOOGLE_TTS_LANGUAGE` | `en-US` | Language code for Google TTS |
| `GOOGLE_TTS_VOICE` | `en-US-Neural2-D` | Voice name for Google Cloud TTS |
| `ELEVENLABS_API_KEY` | _(empty)_ | Your ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | ElevenLabs voice ID (Rachel) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `VIDEO_WIDTH` | `1080` | Output video width (px) |
| `VIDEO_HEIGHT` | `1920` | Output video height (px) |
| `VIDEO_FPS` | `30` | Output frames per second |
| `VIDEO_BITRATE` | `4M` | Output video bitrate |
| `DEFAULT_TRANSITION` | `fade` | Transition type: `fade`, `crossfade`, `zoom` |
| `ZOOM_INTENSITY` | `1.10` | Ken Burns zoom level (1.0 = no zoom) |
| `SUBTITLE_FONT_SIZE` | `60` | Subtitle font size |
| `MIN_SCENE_DURATION` | `3.0` | Minimum seconds per scene |
| `MAX_SCENE_DURATION` | `15.0` | Maximum seconds per scene |
| `WORDS_PER_SECOND` | `2.5` | TTS speaking rate for duration estimate |
| `DEBUG` | `false` | Enable debug mode + hot reload |

---

## 🌐 API Usage

### POST /generate — Start a video generation job

```bash
curl -X POST http://localhost:8000/generate \
  -F "script=Welcome to our amazing product. Today we reveal the future of technology. Our device has the best camera and longest battery life. Available in five colors starting this Friday." \
  -F "tts_provider=google" \
  -F "transition=fade" \
  -F "clips=@/path/to/clip1.mp4" \
  -F "clips=@/path/to/clip2.mp4" \
  -F "clips=@/path/to/clip3.mp4"
```

**Response (202 Accepted):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "Job a1b2c3d4... created. Poll GET /status/a1b2c3d4... for progress."
}
```

---

### GET /status/{job_id} — Poll processing progress

```bash
curl http://localhost:8000/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response:**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "progress": 60,
  "current_stage": "Generating subtitle timings",
  "created_at": "2025-01-15T10:30:00",
  "updated_at": "2025-01-15T10:30:45",
  "error": null
}
```

**Status values:** `pending` → `processing` → `completed` / `failed`

---

### GET /result/{job_id} — Get video URL

```bash
curl http://localhost:8000/result/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response (completed):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "output_url": "/result/a1b2c3d4.../download",
  "message": "Video is ready. Use the output_url to download."
}
```

---

### GET /result/{job_id}/download — Download the MP4

```bash
curl -L http://localhost:8000/result/a1b2c3d4-e5f6-7890-abcd-ef1234567890/download \
  -o my_video.mp4
```

---

### GET /health — System health check

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "ok",
  "app": "AutoVideoGen",
  "version": "1.0.0",
  "timestamp": "2025-01-15T10:00:00",
  "ffmpeg_available": true,
  "redis_available": true
}
```

---

## 🔌 Switching TTS Providers

### Use Google TTS (Free — gTTS fallback, no API key needed)

```env
TTS_PROVIDER=google
```

### Use Google Cloud TTS (Premium neural voices)

```bash
pip install google-cloud-texttospeech
```

```env
TTS_PROVIDER=google
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GOOGLE_TTS_VOICE=en-US-Neural2-D
```

### Use ElevenLabs (Most natural voices)

```bash
pip install elevenlabs
```

```env
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

You can also switch per-request via the API:
```bash
curl -X POST http://localhost:8000/generate \
  -F "tts_provider=elevenlabs" \
  ...
```

---

## 🧪 Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_script_segmentation.py -v

# Run with coverage
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

---

## 🐳 Docker Deployment

### Build and start everything

```bash
cp .env.example .env
# Edit .env with your values

docker compose up --build
```

This starts:
- **redis** on port 6379
- **api** on port 8000 (FastAPI)
- **worker** (Celery, 2 concurrent video jobs)

### Scale workers

```bash
docker compose up --scale worker=4
```

### Check logs

```bash
docker compose logs -f api
docker compose logs -f worker
```

---

## 📊 Processing Stages & Progress

| Stage | Progress | Agent |
|-------|----------|-------|
| Queued | 0% | — |
| Segmenting script | 10% | ScriptSegmentationAgent |
| Mapping clips to scenes | 25% | SceneMappingAgent |
| Generating AI voiceover | 40% | AudioGenerationAgent |
| Generating subtitle timings | 60% | SubtitleTimingAgent |
| Compositing video | 75% | VideoCompositionAgent |
| Export + cleanup | 90–100% | FFmpeg |

---

## 🔧 Extending the System

### Add a new TTS provider

1. Create `utils/tts/my_provider_tts.py` extending `BaseTTSProvider`
2. Add it to `_PROVIDER_MAP` in `utils/tts/__init__.py`
3. Add the enum value to `TTSProvider` in `models/schema.py`

### Add a new transition type

1. Add an enum value to `TransitionType` in `models/schema.py`
2. Handle the new case in `VideoCompositionAgent._concat_with_transition()`
3. Implement the FFmpeg filter in `utils/ffmpeg_utils.py`

### Replace JSON storage with a database

1. Implement the same interface as `JobService` using SQLAlchemy / Redis
2. Update `services/job_service.py`
3. No other code changes needed — services are injected by reference

---

## 📄 License

MIT License — free to use, modify, and distribute.
