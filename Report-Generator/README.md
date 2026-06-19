# Artifact Report Generator

> **Created by:** Mokshith Balidi  
> **Created in:** January 2026  
> **Organization:** TW.2324  
> **Rights:** Mokshith Balidi holds all rights to this microservice.

---

FastAPI microservice that accepts a ZIP archive of automation artifacts and returns a self-contained HTML execution report. The service supports the current `sample.zip` structure used in this repo, preserves the existing FastAPI exports, and now includes stronger ZIP validation, safer HTML rendering, app-scoped AI clients, optional Redis rate limiting, and updated health semantics.

## What It Does

1. Accepts a `multipart/form-data` ZIP upload at `POST /api/v1/generate-report`.
2. Validates archive size, entry count, decompressed size, compression ratio, and required artifacts.
3. Parses step summaries, screenshots, script, video, timestamps, and optional repair metadata.
4. Optionally enriches step outcomes and the run narrative through Gemini, OpenAI, or Anthropic.
5. Returns a downloadable `text/html` report with embedded screenshots and video.

## Supported ZIP Formats

### Appium matrix bundle

Executor-Regenerator can return one outer ZIP for a runtime Appium device matrix. The outer ZIP contains `matrix_summary.json` plus one normal run directory per selected device:

```text
archive.zip
├── matrix_summary.json
├── pixel_7/
│   ├── final_script.py
│   ├── status.txt
│   └── success/
│       ├── summary.json
│       └── 0__step_.../
│           ├── step_summary.json
│           └── screenshot.png
├── oneplus_latest/
│   └── ...
└── iphone_latest/
    ├── final_script.py
    └── failures/
        ├── summary.json
        └── 2__step_.../attempt_1/
            ├── device_context.json
            ├── error.txt
            ├── dom.xml
            └── screenshot.png
```

The report parser reads each device folder separately and prefixes report steps with the device label.

### Current format

This is the format used by `sample.zip` in the repository.

```text
archive.zip
├── started_at.txt
├── finished_at.txt
├── final_script.py                # required
├── repair_report.json             # optional
└── success/
    ├── summary.json
    ├── video/
    │   └── execution.webm|mp4     # required
    ├── 0__step_0_xxxxx/
    │   ├── step_summary.json
    │   └── screenshot.png|jpg|jpeg|webp
    ├── 1__step_1_xxxxx/
    │   ├── step_summary.json
    │   └── screenshot.png|jpg|jpeg|webp
    └── ...
```

Example `step_summary.json`:

```json
{
  "step_index": 0,
  "step_name": "0__step_0_3fda4f10f510",
  "intent": "Navigate to https://example.com",
  "started_at": "2026-03-01T14:08:50.820645+00:00",
  "ended_at": "2026-03-01T14:08:53.114207+00:00",
  "duration_sec": 2.295,
  "url": "https://example.com",
  "attempts": 1,
  "max_retries": 1,
  "status": "passed"
}
```

### Legacy format

This format is still accepted for backward compatibility.

```text
archive.zip
├── report.json
├── final_script.py                # required
├── execution_video.mp4|webm       # required
├── repair_report.json             # optional
└── steps/
    ├── step-1/
    │   ├── summary.json
    │   └── screenshot.png|jpg|jpeg|webp
    └── ...
```

Example `report.json`:

```json
{
  "name": "Login Authentication Flow",
  "started_at": "2026-06-02T10:00:00Z",
  "finished_at": "2026-06-02T10:02:00Z"
}
```

## API Surface

The FastAPI exports remain:

- `POST /api/v1/generate-report`
- `GET /health/live`
- `GET /health/ready`
- `GET /health`

### `POST /api/v1/generate-report`

- Input: `multipart/form-data`
- Field: `file`
- Success: `200 OK`, `text/html; charset=utf-8`
- Error cases:
  - `400` invalid ZIP, malformed JSON, missing required artifacts, unsafe paths
  - `413` ZIP too large or decompressed content exceeds configured limits
  - `422` request validation failure
  - `429` rate limit exceeded
  - `500` unexpected internal failure

### Health endpoints

- `/health/live`: process liveness
- `/health/ready`: readiness probe, returns `503` when the filesystem is not writable
- `/health`: human-friendly service status

## Security and Hardening

The service now includes:

- Autoescaped Jinja rendering to prevent stored XSS from archive content.
- Safe URL handling; non-HTTP(S) links such as `javascript:` are dropped.
- Content Security Policy headers tuned for the generated report response.
- ZIP guards for:
  - maximum uploaded size
  - maximum archive entry count
  - maximum decompressed bytes
  - maximum compression ratio
  - maximum step count
  - per-file limits for screenshots, script, and video
- Required artifact enforcement:
  - `final_script.py`
  - execution video (`.webm` or `.mp4`)
- Duplicate ZIP entry detection.
- Unsafe path rejection.
- Optional Redis-backed rate limiting, with in-memory fallback.
- App-scoped AI provider reuse instead of constructing a new client per request.

## AI Behavior

Supported providers:

- `gemini`
- `openai`
- `anthropic`

AI is used for:

- per-step summaries
- an overall execution narrative

If the provider times out or step enrichment fails, the service still returns the report. If provider initialization fails at startup, the app falls back to a no-op AI provider so report generation remains available.

## Configuration

Copy `.env.example` to `.env` and set the values you need.

Important settings:

```env
ENVIRONMENT=dev
DEBUG=true
API_PREFIX=/api/v1

AI_ENABLED=true
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=30
RATE_LIMIT_BACKEND=memory
REDIS_URL=
TRUST_FORWARDED_IP=false

MAX_ZIP_SIZE_MB=500
MAX_ZIP_ENTRIES=2000
MAX_DECOMPRESSED_SIZE_MB=1024
MAX_COMPRESSION_RATIO=100
MAX_STEP_COUNT=500
MAX_SCREENSHOT_SIZE_MB=15
MAX_VIDEO_SIZE_MB=250
MAX_SCRIPT_SIZE_KB=1024

API_KEY_ENABLED=true
API_KEY=replace-with-a-real-api-key
API_KEY_HEADER=X-API-Key
```

Notes:

- `ENVIRONMENT` must be one of `dev`, `staging`, or `prod`.
- Set `RATE_LIMIT_BACKEND=redis` and `REDIS_URL` to enable shared rate limiting across replicas.
- If deploying behind a reverse proxy like **GCP Cloud Run** or an AWS Load Balancer, set `TRUST_FORWARDED_IP=true` so the rate limiter can correctly identify client IPs.
- `.dockerignore` excludes `.env`, local samples, tests, and virtual environments from image builds.

## Local Development

### Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Test

```bash
python -m pytest -q
```

## Sample Request

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/generate-report" \
     -H "X-API-Key: your-api-key" \
     -F "file=@sample.zip" \
     -o output_report.html
```

## Docker

The Docker build now uses a multi-stage image and only copies the runtime `app/` code into the final container.

```bash
docker build -t artifact-report-generator:latest .
docker run -d -p 8000:8000 --env-file .env --name report-generator artifact-report-generator:latest
```

## Test Coverage

The test suite now covers:

- current ZIP format parsing
- legacy ZIP format parsing
- required artifact enforcement
- safe HTML escaping and URL sanitization
- end-to-end HTML generation for `sample.zip`
- report route behavior
- readiness and liveness endpoints

## Project Structure

```text
app/
├── core/
├── middleware/
├── models/
├── routes/
├── services/
│   └── ai/
├── templates/
└── workflows/
tests/
sample.zip
```

## Operational Notes

- The generated report is self-contained; screenshots and video are embedded as Base64.
- The HTML is returned with `Content-Disposition: attachment; filename=report.html`.
- The service preserves the existing FastAPI route surface while upgrading validation, resilience, and rendering safety behind it.

> [!WARNING]
> **Known Limitation - Scalability Risk (Needs Fixing!)**
> Because this microservice embeds execution videos directly into the HTML via Base64 encoding, large videos (up to `MAX_VIDEO_SIZE_MB=250`) will cause massive memory spikes (~1GB+ RAM per concurrent request). This can lead to Out-Of-Memory (OOM) crashes under heavy load. 
> **Future Fix required:** Upload videos to cloud storage (e.g., AWS S3, Google Cloud Storage) and insert the public URL into the report, instead of Base64 embedding.

> [!IMPORTANT]  
> **Deploying on Google Cloud Run (or other proxies): `TRUST_FORWARDED_IP`**
> 
> **The Problem (In Layman's Terms):**
> Imagine your server is a person working in an office, and the **Rate Limiter** is your rule: *"I will only accept 30 letters per minute from any single sender."*
> 
> - **Without a Proxy (Localhost):** The mail carrier (the user) hands a letter directly to you. You can look at the return address on the envelope (their IP address) and know exactly who sent it.
> - **With a Proxy (Google Cloud Run, AWS, Nginx):** All mail goes to the building's front desk receptionist first. The receptionist takes the letter, puts it inside a *new* envelope, writes the original sender's return address on a sticky note (a header called `X-Forwarded-For`), and hands it to you.
> 
> If you don't tell your system about the receptionist, you will look at the envelope, assume the *receptionist* is the one sending you thousands of letters, and you will ban the receptionist—blocking **everyone's** mail from getting through! Furthermore, if a prankster bypasses the front desk, walks up to you directly, and slaps a fake sticky note on their own envelope, you might accidentally trust it and ban an innocent person (IP Spoofing).
> 
> **The Solution:**
> By default, `TRUST_FORWARDED_IP=false`. The system looks strictly at whoever physically handed over the letter, ignoring any sticky notes. This prevents spoofing when running locally.
> 
> If you are deploying to **Google Cloud Run** (or AWS Load Balancer, Cloudflare, etc.), you **MUST** set `TRUST_FORWARDED_IP=true` in your `.env` variables. This tells the application: *"Yes, I have a trusted front desk receptionist. It is safe to trust the sticky note (`X-Forwarded-For`) to identify the real senders, and you should use that to rate limit them."*
