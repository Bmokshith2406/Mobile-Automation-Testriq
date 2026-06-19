# Automation Script Generator

> **Author:** Mokshith Balidi | **Organization:** TW.2324  
> **Created:** January 2026 | All rights reserved.

An LLM-powered microservice that converts structured test case specifications into
executable automation scripts for **Playwright**, **Selenium**, **Cypress**, and **Appium**.

---

## Table of Contents

1. [Overview](#overview)
2. [What's New — Enhanced Edition](#whats-new--enhanced-edition)
3. [Architecture](#architecture)
4. [Prerequisites](#prerequisites)
5. [Quick Start](#quick-start)
6. [Configuration Reference](#configuration-reference)
7. [API Reference](#api-reference)
8. [Security](#security)
9. [Docker Deployment](#docker-deployment)
10. [Testing](#testing)
11. [Project Structure](#project-structure)
12. [Changelog](#changelog)

---

## Overview

### What it does

1. Accepts a structured test case (steps, prerequisites, teardown steps, target framework) via HTTP.
2. Builds a **Canonical Intermediate Representation (CIR)** — a structured, framework-agnostic action graph.
3. Validates the CIR and runs LLM-based verification loops using framework-specific constraint rules.
4. Generates framework-specific, executable code and returns it as a downloadable script file.

### Supported frameworks

| Framework | Language | File Extension | Notes |
|---|---|---|---|
| Playwright | Python | `.py` | Full async support, semantic locator API |
| Selenium | Python | `.py` | WebDriver-based |
| Cypress | JavaScript | `.js` | Config-managed video recording |
| Appium | Python | `.py` | Mobile/native, iOS Class Chain, Android UIAutomator2 |

### Key capabilities

- **Parallel LLM calls** via `asyncio.Semaphore` — classification, extraction, and verification run concurrently
- **Structured output mode** — when a JSON Schema is provided, Gemini uses `response_schema` and OpenAI uses `json_schema` response format; schema is transparently adapted per provider
- **Robust JSON recovery** — multi-layer fallback: structured output → `JSONDecoder.raw_decode()` → JSON block extraction → key-value mapping recovery → trailing-comma repair → `ast.literal_eval`
- **Automatic quota failover** — on Gemini 429/quota errors the provider transparently retries on the fallback model without surfacing the switch to callers
- **Batch processing** — up to 50 test cases in a single request with configurable parallelism
- **Streaming** — real-time progress updates via Server-Sent Events (SSE)
- **Cross-device matrix** — one request generates a ZIP of Playwright scripts across browsers and mobile simulators
- **In-memory cache** with optional Redis — LRU eviction, TTL, concurrency-safe; Redis cache uses `SCAN` cursors (non-blocking)
- **Redis rate limiting** — falls back to in-memory when Redis is unavailable
- **HMAC-signed webhooks** — completion notifications with exponential back-off retries
- **Circuit breaker** — automatic LLM provider failover (exactly one failure recorded per breach)
- **Prometheus-compatible metrics** endpoint
- **SSRF protection** on all outbound webhook URLs
- **File cleanup** background task — auto-deletes generated scripts after a configurable TTL
- **Generation timeout** — configurable hard timeout with HTTP 504 on breach
- **JSON structured logging** — machine-readable log output selectable via `LOG_FORMAT=json`

---

## What's New — Enhanced Edition

This is the Enhanced Edition of Automation Script Generator. It includes a comprehensive audit with 55+ bug fixes and architectural enhancements applied across 11 implementation phases. The API is versioned under `/v1/`. All changes preserve request/response semantics.

---

### CIR Model Expansion (Phase 1)

#### New Action Types (11 added, total: 17)

| New Type | Description |
|---|---|
| `hover` | Mouse hover over element |
| `scroll` | Directional scroll with configurable amount |
| `drag_drop` | Drag element to a target location |
| `upload_file` | File upload via input element |
| `keyboard` | Keyboard shortcut or key combination |
| `switch_frame` | Switch execution context into an iframe |
| `switch_window` | Switch to another browser window/tab |
| `execute_script` | Inject and run JavaScript in page context |
| `double_click` | Double-click on element |
| `right_click` | Right-click (context menu) on element |
| `wait_for` | Explicit wait with configurable condition and timeout |

#### New Assertion Types (10 added, total: 16)

`attribute_equals`, `attribute_contains`, `element_count`, `element_enabled`, `element_disabled`, `element_checked`, `element_unchecked`, `element_value`, `list_contains`, `page_source_contains`

#### New Wait Conditions (7 added, total: 12)

`clickable`, `presence`, `text_present`, `count_equals`, `staleness`, `network_idle`, `load_state`

#### New Locator Strategies (3 added for mobile, total: 15)

`ios_class_chain`, `ios_predicate_string`, `android_data_matcher`

#### New CIRAction Fields

13 new optional fields on `CIRAction` to support the expanded action vocabulary:  
`drag_target`, `key_combination`, `frame_locator`, `window_index`, `script_expression`, `scroll_direction`, `scroll_amount`, `file_path_to_upload`, `wait_for_condition`, `wait_for_timeout`, `attribute_name`, `expected_count`

---

### CIR Builder Upgrades (Phase 2)

- **Prerequisites through full pipeline** — complex prerequisites (non-URL descriptions) now route through the full `_build_block()` LLM pipeline instead of being silently dropped to a bare navigate action
- **Teardown support** — `TestCase.teardown_steps: List[Step]` field added; `CIRBuilder` processes teardown steps in `_build_teardown()` and includes them as the `teardown` list of `CIRTestCase`
- **Parallel build** — `setup_task`, `steps_task`, and `teardown_task` all run via `asyncio.gather()` instead of sequentially
- **Heuristic atomic split fallback** — when the LLM returns the original intent unchanged, `_heuristic_split()` splits on "and then", "then", and "after that" conjunctions to ensure compound steps are always decomposed
- **Per-step max_retries** — `Step.max_retries: Optional[int]` (0–10) field added for runtime retry control

---

### Script Parser Expansion (Phase 3)

- **Playwright semantic API patterns** — `get_by_label()`, `get_by_placeholder()`, `get_by_text()` now fully parsed by `ScriptParser.extract_locator()`
- **iOS Appium patterns** — `AppiumBy.IOS_CLASS_CHAIN`, `AppiumBy.IOS_PREDICATE_STRING`, `AppiumBy.ANDROID_UIAUTOMATOR` patterns added and mapped to the new locator strategies
- **Locator normalization** — `_normalize_strategy()` in `BaseExtractor` now handles `placeholder`, `label`, `text_content`, `uiautomator`, `androiduiautomator`, `accessibility_id`, `ios_class_chain`, `ios_predicate_string`

---

### Playwright Action Renderer — 11 New Renderers (Phase 4)

The Playwright code generator now renders all 17 action types:

| New Renderer | Generated API |
|---|---|
| `_generate_hover` | `await locator.hover()` |
| `_generate_double_click` | `await locator.dbl_click()` |
| `_generate_right_click` | `await locator.click(button='right')` |
| `_generate_scroll` | `await locator.scroll_into_view_if_needed()` / `mouse.wheel()` |
| `_generate_drag_drop` | `await page.drag_and_drop(source, target)` |
| `_generate_upload_file` | `await locator.set_input_files(path)` |
| `_generate_keyboard` | `await page.keyboard.press(combo)` |
| `_generate_switch_frame` | `frame_locator = page.frame_locator(...)` |
| `_generate_switch_window` | `page = context.pages[index]` |
| `_generate_execute_script` | `await page.evaluate(expr)` |
| `_generate_wait_for` | `await page.wait_for_url/selector/load_state(...)` |

**Additional renderer fixes:**

- **Link role fix** — XPath `//a[...]` patterns are now correctly rendered as `page.get_by_role('link', name=...)` instead of the erroneous `a:has-text()` CSS fallback
- **XPath auto-upgrade** — extended to `//button[...]` and `//a[...]` elements

---

### Framework-Aware Verifier (Phase 5)

- **`verifier_constraints` field** added to `FrameworkProfile` — each profile now carries a string of framework-specific rules that the step verifier prompt uses instead of hardcoded Playwright-only rules
- **Cypress verifier bug fixed** — the verifier previously applied Playwright async/await rules to Cypress code, causing false negatives; it now uses Cypress-specific constraints
- **Selenium and Appium constraints** — both profiles populated with appropriate synchronous/mobile-specific verifier rules
- **Repair loop** — up to `MAX_VERIFIER_REPAIR_ATTEMPTS` (default: 4) verify→modify cycles per step

---

### Intent Corrector & Role Upgrader Hardening (Phase 5)

- **False-positive locator mutation fix** — `_diff_contains_locator_mutation()` replaced with a regex-based `LOCATOR_PATTERNS` list; bare `#` comment characters and `//` path separators no longer incorrectly trigger locator-mutation detection
- **Structure preservation** — both `IntentCorrector` and `FrameworkRoleUpgrader` now also compare control-flow statement count (`if`/`for`/`while`/`try`) to detect structural changes
- **Log level cleanup** — `IntentCorrector` initialization and intent-correction events downgraded from `WARNING` to `INFO`

---

### New Endpoint: Dry-Run Validation (Phase 6)

```
POST /validate/
```

Builds the CIR without generating any code — useful for validating test case structure before incurring LLM generation cost.

**Request body:** Same `test_case` object as `/generate/`.

**Response:**

```json
{
  "valid": true,
  "cir_summary": {
    "setup_blocks": 1,
    "step_blocks": 3,
    "teardown_blocks": 1,
    "total_actions": 5
  },
  "warnings": [],
  "error": null
}
```

**Error codes:**

| Code | Meaning |
|---|---|
| `200` | CIR built and valid (even with warnings) |
| `400` | Request body invalid |
| `422` | CIR build or validation failed — `error` field contains detail |

---

### Infrastructure Bug Fixes (Phase 7)

#### Circuit Breaker — Double Failure Fix
The circuit breaker was calling `record_failure()` twice on LLM errors — once inside the `except` block and once unconditionally after the retry loop. The unconditional call was removed. Each failure is now recorded exactly once.

#### Redis Cache — Non-Blocking SCAN
`RedisCache.clear()` previously used `KEYS *` which blocks the Redis event loop for the full key scan. Replaced with an async `SCAN` cursor loop — O(1) amortized, non-blocking.

#### JSON Decoder — Brace-in-String Fix
`_extract_json_block()` now first attempts `json.JSONDecoder().raw_decode()` which correctly handles JSON objects containing `{` and `}` inside string values. The previous brace-counting heuristic had been misidentifying string contents as JSON boundaries.

#### JSON Truncation Removed
The `text.strip()[:max_chars]` truncation was applied *before* JSON extraction on the hot path, causing valid but long LLM responses to be silently cut. The truncation is removed; `MAX_JSON_CHARS` now defaults to 25,000 (raised from 5,000) with a maximum of 200,000.

---

### Security Hardening (Phase 8)

#### Path Traversal Fix
`/generate/` now uses `resolved_path.is_relative_to(_OUTPUT_DIR)` instead of `str(resolved_path).startswith(str(_OUTPUT_DIR))`. The old string-prefix check was bypassable with filenames like `../secret`.

#### Streaming Body Size Guard
`MaxBodySizeMiddleware.dispatch()` previously relied solely on the `Content-Length` header to enforce request body size limits. Requests without `Content-Length` (chunked transfer encoding) bypassed the check. The middleware now intercepts streaming bodies via a `limited_receive` closure and returns HTTP 413 regardless of whether `Content-Length` is present.

---

### Enterprise Features (Phase 9)

#### Generation Timeout (HTTP 504)
Generation is wrapped with `asyncio.wait_for(..., timeout=settings.GENERATION_TIMEOUT_SECONDS)`. When the timeout is exceeded, the service returns HTTP 504 Gateway Timeout instead of hanging indefinitely. Configurable via `GENERATION_TIMEOUT_SECONDS` (30–1200 seconds, default 300).

#### Framework-Aware File Extension
- Cypress scripts are saved with the `.js` extension
- All other frameworks use `.py`
- `BaseGenerator` exposes `get_file_extension() -> str`; `CypressGenerator` overrides it to return `.js`

#### `run_id` in Filename
When `run_id` is supplied, the output filename includes it: `test_<id>_<run_id>.py`. This prevents concurrent requests for the same test case from overwriting each other's output.

#### JSON Structured Logging
- New `JSONFormatter` class in `app/main.py` emits each log record as a single JSON line
- Activated via `LOG_FORMAT=json` — defaults to `"text"` (human-readable)
- Fields: `timestamp`, `level`, `logger`, `message`, `exc_info` (when present)

#### Playwright Generator Registry Reset
`PlaywrightPythonGenerator.generate()` now resets `_step_registry` and `_step_defs` at the start of each call, preventing step function names from leaking across consecutive calls on the same generator instance.

---

### Template Engine Fix (Phase 10)

`PromptTemplateEngine` was using a shared class-level dict (`BUILT_IN_TEMPLATES`) as its mutable template store. Calling `add_template()` on one instance would mutate the class dict and affect all other instances in the process.

Fix: `__init__` now copies `dict(self.BUILT_IN_TEMPLATES)` into `self._templates`; all internal reads and writes use the instance dict. The class-level dict is now read-only.

---

### Hardcoded Assertion Removed

`AssertActionExtractor` contained a hardcoded fallback: `if "dashboard" in text: return element_is_visible`. This caused every step mentioning "dashboard" to receive a visibility assertion regardless of intent. The block was removed entirely; the LLM extraction result is always used.

---

### Multi-Action Block Support

`BaseGenerator` previously raised `RuntimeError` when a `CIRBlock` contained more than one action. This guard was removed. All generators now iterate over `block.actions` and render each action in sequence, enabling compound steps (e.g., hover-then-click) to be expressed as a single block with multiple actions.

---

### Test Suite — 105/105 Passing

All 105 tests pass after the enhancements. Notable additions:

- `test_llm_json_regressions.py` — tests for `generate_json()` recovering from key-value (non-JSON) LLM output; tests for `AssertActionExtractor` accepting the same
- `StubExecutor.run()` signature updated to accept `config=None` matching the updated `generate_json()` interface

---

### Phase 11 — Enterprise Hardening & Audit (June 2026)

A full end-to-end codebase audit produced 55 tracked findings across 7 categories: bugs, architecture, enterprise, sophistication, auditability, modularity, and production readiness. All findings were resolved.

#### API Versioning (ENT-1)

All routes are now prefixed with `/v1/`:

| Before | After |
|---|---|
| `POST /generate/` | `POST /v1/generate/` |
| `POST /batch/` | `POST /v1/batch/` |
| `POST /stream/generate` | `POST /v1/stream/generate` |
| `POST /validate/` | `POST /v1/validate/` |
| `POST /cost/estimate` | `POST /v1/cost/estimate` |
| `POST /matrix/generate` | `POST /v1/matrix/generate` |
| `GET /health/*` | `GET /v1/health/*` |
| `GET /metrics/*` | `GET /v1/metrics/*` |

#### Admin API (ENT-5)

New admin endpoints — all require API key:

| Endpoint | Description |
|---|---|
| `GET /v1/admin/cache/stats` | LRU + Redis cache statistics |
| `POST /v1/admin/cache/clear` | Flush the LLM response cache |
| `GET /v1/admin/circuit-breaker/status` | Current circuit breaker state, failure count |
| `POST /v1/admin/circuit-breaker/reset` | Manually reset an open circuit to CLOSED |
| `GET /v1/admin/metrics` | JSON metrics snapshot (same as `/v1/metrics/`) |
| `GET /v1/admin/config` | Non-sensitive config values (no API keys or secrets) |

#### Bug Fixes

| ID | Component | Fix |
|---|---|---|
| BUG-1 | `assembler.py` | Framework name now passed to assembler so Cypress output correctly uses `.js` extension |
| BUG-2 | `batch_processor.py` | Batch items use each item's `target_framework` — batch_processor now delegates to `GenerationService` |
| BUG-3 | `generation_service.py`, `stream.py` | Teardown blocks included in CIR validation (were previously skipped) |
| BUG-4 | `stream.py` | Fixed blocking `assemble()` call → non-blocking `assemble_async()` |
| BUG-5 | `assembler.py` | Async temp file now uses the correct framework extension (was always `.py`) |
| BUG-6 | `stream.py` | Module-level `asyncio.Semaphore` replaced with lazy factory `_get_stream_semaphore()` to avoid Python 3.10+ event-loop deprecation |
| BUG-7 | `rate_limit.py` | Redis sliding-window check replaced with atomic Lua script — eliminates ZADD/ZREM race condition |
| BUG-8 | `cir_builder.py` | Intent correction log downgraded from `WARNING` to `INFO` (was flooding warning logs) |
| BUG-9 | `webhook_notifier.py` | DNS rebinding: `localhost.` (trailing dot) added to blocked hostname list |
| BUG-10 | `config.py` | `CORS_ORIGINS` now correctly parses JSON array strings (e.g. `'["https://a.com"]'`) from environment |
| BUG-11 | `main.py` | File log handler uses absolute path resolved from `__file__` — avoids broken relative path on non-CWD launches |
| BUG-12 | `batch_processor.py` | Batch cost estimate sums per-item estimates; was previously extrapolating the first item's cost across all items |

#### Architecture

| ID | Change |
|---|---|
| ARCH-1 | `batch_processor.py` delegates entirely to `GenerationService` — single unified pipeline shared with `/generate/` and `/stream/` |
| ARCH-5 | `ENABLE_INTENT_CORRECTION` moved from a module-level constant in `cir_builder.py` to `INTENT_CORRECTION_ENABLED` in `Settings` — runtime-configurable without code changes |

#### Enterprise Features

| ID | Change |
|---|---|
| ENT-8 | `STREAM_MAX_CONCURRENT` added to config (default: 10) — streaming concurrency limit is now configurable |
| ENT-9 | Rate limit `Retry-After` header returns exact seconds until the oldest request expires — was previously a fixed estimate |
| ENT-10 | All LLM raw-response debug logs truncated to 200 chars — prevents multi-megabyte log entries from large LLM outputs |
| ENT-11 | Webhook payloads include versioned schema: `event`, `schema_version`, `timestamp` fields on every notification |

#### Sophistication

| ID | Change |
|---|---|
| SOF-1 | LLM executor reads `Retry-After` header from 429 responses and sleeps the exact duration before retrying |
| SOF-2 | LLM cache keys normalize prompts (collapse whitespace, lowercase) before hashing — prevents duplicate cache misses from cosmetic whitespace differences |
| SOF-3 | Circuit breaker distinguishes permanent errors (4xx auth/billing) from transient ones — permanent errors open the circuit immediately, bypassing the failure threshold |
| SOF-4 | `Histogram.observe()` uses `bisect.insort()` — O(log n) sorted insert instead of O(n log n) sort-on-read |
| SOF-5 | CIR prerequisites now built in parallel with `asyncio.gather()` — was sequential |
| SOF-7 | `sanitization.py` emits a `WARNING` log when content is redacted — previously silent |
| SOF-8 | `BatchResult` includes `skipped_items` count |

#### Auditability

| ID | Change |
|---|---|
| AUD-1 | `X-Request-ID` / `X-Correlation-ID` header value propagated through the generation pipeline and written into the generated script file header as a comment |
| AUD-2 | `GET /v1/health/deep` now requires API key (previously open to unauthenticated callers) |
| AUD-3 | `GET /v1/metrics/` and `GET /v1/metrics/prometheus` now require API key |
| AUD-4 | Generated script file header includes `# Request ID: <id>` for traceability |

#### Modularity

| ID | Change |
|---|---|
| MOD-1 | `get_webhook_notifier()` singleton factory added — all routes share one notifier instance; `main.py` shuts it down cleanly via the factory |
| MOD-2 | `MAX_BATCH_SIZE` read inside each handler via `get_settings()` — not cached at module import time |
| MOD-3 | Module-level `settings = get_settings()` removed from `batch_processor.py` — settings fetched per-request |
| MOD-4 | Inline `import` statements inside function bodies removed from `cir_builder.py` and `stream.py` — all imports are at module level |

#### Production Readiness

| ID | Change |
|---|---|
| PROD-2 | All error responses use a structured envelope: `{"error": {"code": …, "message": …, "type": …, "request_id": …, "timestamp": …}}` |
| PROD-3 | `VERSION` changed from `"1"` to `"1.0.0"` (semver) |
| PROD-4 | `openapi_url="/openapi.json"` always enabled — OpenAPI schema accessible in all environments |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        API Layer  (all routes under /v1/)        │
│  POST /v1/generate/    POST /v1/stream/generate  POST /v1/matrix/│
│  POST /v1/batch/       POST /v1/validate/        GET  /v1/health/│
│  GET  /v1/metrics/     GET  /v1/admin/*                          │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Middleware Stack                          │
│  API Key ─► Rate Limit (atomic Lua) ─► Body Size ─► Metrics     │
│  ─► Audit                                                        │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                   GenerationService  (unified pipeline)          │
│                                                                  │
│  ┌───────────┐   ┌───────────┐   ┌────────────┐  ┌───────────┐  │
│  │CIR Builder│──▶│CIR Validtr│──▶│Code Genertr│─▶│ Assembler │  │
│  └─────┬─────┘   └───────────┘   └────────────┘  └───────────┘  │
│        │  setup + steps + teardown validated & built in parallel │
│        ▼  LLM calls gated by asyncio.Semaphore                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              LLM Executor  (lazy semaphore)              │    │
│  │  Classifier ─ Extractors ─ Intent Corrector ─ Verifier  │    │
│  │  ↳ Retry-After-aware retry  ↳ Permanent-error fast-fail │    │
│  │  ↳ generate_json(schema=…) → structured output mode     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  asyncio.wait_for → HTTP 504 on GENERATION_TIMEOUT_SECONDS       │
│  X-Request-ID propagated → script file header comment           │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Infrastructure                           │
│  Cache (Redis SCAN / In-Mem, normalised prompt keys)             │
│  Circuit Breaker (permanent vs transient errors)                 │
│  Webhooks (HMAC-signed, versioned schema, SSRF-safe)             │
│  Metrics (O(log n) histogram) ─ Structured JSON Logging          │
└──────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Google Gemini API key | Required (primary LLM) |
| OpenAI API key | Optional (fallback LLM) |
| Redis | Optional (rate limiting + caching at scale) |
| Docker | Optional (containerized deployment) |

---

## Quick Start

### 1 — Clone and install

```bash
git clone <repository-url>
cd Automation-Script-Generator-Enhanced

python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in **at minimum**:

```env
# A strong random key (≥ 32 characters)
API_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">

# Your Gemini API key
GOOGLE_API_KEY=<your-gemini-key>
```

### 3 — Start the server

```bash
# Development (auto-reload)
uvicorn app.main:app --reload --port 8001

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 4 — Verify health

```bash
curl http://localhost:8001/v1/health/
# {"status": "ok", "version": "1.0.0", ...}
```

---

## Configuration Reference

All variables are read from the environment (or `.env`). The service validates them at startup and **refuses to start** if required values are missing or insecure.

### Security

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | *(required)* | Shared secret for callers. ≥ 32 chars. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `API_KEY_ENABLED` | `true` | Set `false` only in local dev |
| `API_KEY_HEADER` | `X-API-Key` | HTTP header name callers use |
| `TRUST_FORWARDED_IP` | `false` | Trust `X-Forwarded-For` for IP resolution. Enable **only** behind a trusted reverse proxy. See [Security](#security). |
| `ENV` | `development` | `development` / `staging` / `production`. CORS wildcard is blocked when `production`. |

### LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` or `openai` |
| `GOOGLE_API_KEY` | — | Gemini API key |
| `OPENAI_API_KEY` | — | OpenAI API key (fallback) |
| `PRIMARY_MODEL` | `gemini-2.5-pro` | Also aliased as `LLM_MODEL` |
| `FALLBACK_MODEL` | `gemini-2.5-flash` | Used when primary fails |
| `MAX_CONCURRENT_LLM_CALLS` | `8` | Semaphore cap. 1–10. |
| `MAX_OUTPUT_TOKENS` | `2048` | Max tokens per LLM response |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-call timeout |
| `LLM_DEFAULT_RETRIES` | `2` | Retries on transient failures |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature. Lower = more deterministic |
| `MIN_CONFIDENCE_THRESHOLD` | `80` | Minimum extraction confidence (0–100) |
| `MAX_JSON_CHARS` | `25000` | Maximum characters parsed during JSON extraction (max 200000) |
| `GENERATION_TIMEOUT_SECONDS` | `300` | Hard timeout for the full generation pipeline. Returns HTTP 504 on breach. (30–1200) |

### Rate Limiting

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Toggle rate limiting globally |
| `RATE_LIMIT_REQUESTS` | `100` | Requests allowed per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window duration |
| `REDIS_URL` | *(blank)* | e.g. `redis://localhost:6379/0`. When set, Redis is used for rate limiting (multi-worker safe). Falls back to in-memory. |

### Caching

| Variable | Default | Description |
|---|---|---|
| `CACHE_ENABLED` | `true` | Toggle LLM response caching |
| `CACHE_TTL_SECONDS` | `3600` | Cache entry lifetime |
| `REDIS_URL` | *(blank)* | Shared with rate limiting. When set, uses Redis cache with non-blocking `SCAN` cursor operations. |

### Batch Processing

| Variable | Default | Description |
|---|---|---|
| `BATCH_MAX_ITEMS` | `50` | Maximum items per batch request |
| `BATCH_MAX_PARALLEL` | `5` | Default concurrency for batch jobs |

### Streaming

| Variable | Default | Description |
|---|---|---|
| `STREAM_MAX_CONCURRENT` | `10` | Maximum simultaneous SSE streaming connections. Extra connections receive HTTP 429. |

### CIR Builder

| Variable | Default | Description |
|---|---|---|
| `INTENT_CORRECTION_ENABLED` | `true` | Toggle the LLM-based intent correction loop inside the CIR builder. Set `false` to skip correction and use raw extraction results. |

### Webhooks

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Per-request timeout |
| `WEBHOOK_MAX_RETRIES` | `3` | Retries with exponential back-off |
| `WEBHOOK_SECRET` | *(blank)* | HMAC-SHA256 signing secret. When set, every webhook payload is signed and delivered with an `X-Webhook-Signature: sha256=<hex>` header. Leave blank to skip signing. |

### File Cleanup

| Variable | Default | Description |
|---|---|---|
| `CLEANUP_ENABLED` | `true` | Background task to delete old generated scripts |
| `CLEANUP_MAX_AGE_HOURS` | `24` | Scripts older than this are deleted |

### CORS

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | *(blank = no CORS)* | Comma-separated list of allowed origins. JSON list also accepted. Wildcard `*` is **blocked** in `production` env. |

### Logging & Observability

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `text` | `text` (human-readable) or `json` (structured JSON log lines for log aggregators) |
| `LOG_TO_FILE` | `false` | Writes logs to `service.log` / `service_error.log` when `true` |
| `METRICS_ENABLED` | `true` | Expose `/metrics/` endpoints |
| `TRACING_ENABLED` | `false` | OpenTelemetry tracing |
| `TRACING_ENDPOINT` | `http://localhost:4317` | OTLP collector endpoint |

### Auth (JWT — Optional Layer)

| Variable | Default | Description |
|---|---|---|
| `AUTH_ENABLED` | `false` | JWT token validation layer (on top of API key) |
| `JWT_SECRET_KEY` | — | Signing secret for JWT |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |

---

## API Reference

All protected endpoints require:

```
X-API-Key: <your-API_KEY>
Content-Type: application/json
```

> All routes are prefixed with `/v1/`. Example: `POST /v1/generate/`.

### Error Envelope

All error responses (4xx, 5xx) return a structured JSON envelope:

```json
{
  "error": {
    "code": 429,
    "message": "Rate limit exceeded",
    "type": "RateLimitExceeded",
    "request_id": "a1b2c3d4",
    "timestamp": "2026-06-19T10:30:00.000Z"
  }
}
```

### Generate Script

```
POST /v1/generate/
```

Generates an automation test script for a single test case. Returns the script as a downloadable file. The output filename includes a `run_id` suffix when one is provided, preventing concurrent requests from overwriting each other.

**Request body:**

```json
{
  "test_case": {
    "test_case_id": "TC001",
    "description": "Verify login with valid credentials",
    "target_framework": "playwright",
    "prerequisites": [
      {
        "prerequisite_id": "PRE001",
        "description": "Navigate to the login page",
        "matched_script": {
          "raw_code": "page.goto('https://example.com/login')",
          "language": "python",
          "framework": "playwright"
        }
      }
    ],
    "steps": [
      {
        "step_id": "STEP001",
        "description": "Enter 'testuser' in the username field",
        "expected_outcome": "Username field contains testuser",
        "max_retries": 2
      },
      {
        "step_id": "STEP002",
        "description": "Click the Login button",
        "expected_outcome": "User is redirected to the dashboard"
      }
    ],
    "teardown_steps": [
      {
        "step_id": "TEAR001",
        "description": "Log out of the application",
        "expected_outcome": "Login page is shown"
      }
    ]
  },
  "webhook_url": "https://hooks.yourapp.com/notify"
}
```

> `target_framework` accepts: `playwright`, `selenium`, `cypress`, `appium`.  
> Defaults to `AUTOMATION_FRAMEWORK` env var if omitted.  
> `teardown_steps` is optional. When provided, teardown blocks are appended to the generated script.  
> `max_retries` on individual steps (0–10) is optional. Passed through to the runtime.

For Appium requests, `appium_config` is optional. Script Generator produces one device-agnostic Appium script that reads its capabilities from environment variables at runtime.

Generated Appium scripts read:
- `APPIUM_SERVER_URL` for the Appium hub URL, defaulting to `http://127.0.0.1:4723`.
- `APPIUM_CAPABILITIES_JSON` for the exact device/app/provider capabilities.
- `APPIUM_DEVICE_CONTEXT_JSON` for labels that appear in artifacts and repair prompts.

> `webhook_url` is optional. If set, the service POSTs a completion notification to that URL after the script is saved. The URL must be publicly reachable — private/loopback IPs are blocked (SSRF protection).

**Response:** `200 OK` — script file download (`application/octet-stream`)

**Errors:**

| Code | Meaning |
|---|---|
| `400` | Invalid request body |
| `401` | Missing or invalid API key |
| `413` | Request body exceeds size limit (including streaming bodies) |
| `422` | CIR validation failed (bad test case structure) |
| `429` | Rate limit exceeded |
| `500` | LLM or internal error |
| `504` | Generation timed out (`GENERATION_TIMEOUT_SECONDS` exceeded) |

---

### Dry-Run Validation

```
POST /v1/validate/
```

Builds the CIR for a test case **without** generating any code. Use this to validate test case structure and catch errors before paying for a full generation run.

**Request body:** Same `test_case` object as `/generate/`.

**Response:**

```json
{
  "valid": true,
  "cir_summary": {
    "setup_blocks": 1,
    "step_blocks": 3,
    "teardown_blocks": 1,
    "total_actions": 5
  },
  "warnings": ["STEP_02: assertion extracted from intent only — no matched_script reference"],
  "error": null
}
```

| Field | Description |
|---|---|
| `valid` | `true` when CIR was built and passed all validation checks |
| `cir_summary` | Block and action counts per section |
| `warnings` | Non-fatal issues (empty-value fields, low-confidence extractions, etc.) |
| `error` | Error detail when `valid` is `false`; `null` otherwise |

---

### Stream Generation

```
POST /v1/stream/generate
```

Same payload as `/generate/`. Returns a **Server-Sent Events** stream with real-time progress events as each pipeline stage completes, followed by the script filename on completion.

**Event format:**

```
event: progress
data: {"stage": "cir_build", "message": "Building CIR...", "percent": 20}

event: complete
data: {"script_filename": "TC001_playwright.py", "tokens_used": 1842}

event: error
data: {"message": "LLM extraction failed", "stage": "classify"}
```

---

### Batch Processing

```
POST /v1/batch/
```

Generate scripts for multiple test cases in one request.

**Request body:**

```json
{
  "items": [
    {
      "test_case": { "test_case_id": "TC001", "..." : "..." },
      "priority": 1
    },
    {
      "test_case": { "test_case_id": "TC002", "..." : "..." },
      "priority": 2
    }
  ],
  "parallel": 3,
  "stop_on_error": false,
  "webhook_url": "https://hooks.yourapp.com/batch-done"
}
```

**Response:**

```json
{
  "batch_id": "abc123",
  "status": "completed",
  "total_items": 2,
  "completed_items": 2,
  "failed_items": 0,
  "total_tokens_used": 3800,
  "cost_estimate_usd": 0.0047,
  "duration_ms": 12400,
  "results": [
    {
      "test_case_id": "TC001",
      "status": "success",
      "script_path": "outputs/generated_scripts/TC001_playwright.py",
      "tokens_used": 1842,
      "duration_ms": 6100
    }
  ]
}
```

**Status values:** `completed` | `partial` | `failed`  
**Item status values:** `success` | `failed` | `skipped`

---

### Batch Status Stream

```
GET /v1/batch/{batch_id}/stream
```

Real-time SSE stream of progress events for a running batch job.

---

### Cost Estimate

```
POST /v1/cost/estimate
```

Estimates token usage and cost before running a generation job — no LLM call is made.

**Request body:** Same `test_case` object as `/generate/`.

**Response:**

```json
{
  "estimated_input_tokens": 4200,
  "estimated_output_tokens": 900,
  "estimated_total_tokens": 5100,
  "estimated_llm_calls": 7,
  "estimated_cost_usd": 0.0063,
  "confidence": "high",
  "warnings": []
}
```

---

### Matrix Generation (Playwright)

```
POST /v1/matrix/generate
```

Generates multiple Playwright scripts across a device/browser matrix and returns them as a single ZIP archive.

---

### Health Checks

```
GET /v1/health/         # Lightweight liveness check — no API key required
GET /v1/health/ready    # Readiness — no API key required
GET /v1/health/deep     # Deep check — LLM provider connectivity — API key required
```

---

### Metrics

Both endpoints require an API key.

```
GET /v1/metrics/           # JSON summary
GET /v1/metrics/prometheus # Prometheus text format
```

---

### Admin API

All endpoints require an API key.

```
GET  /v1/admin/cache/stats             # LRU + Redis cache hit/miss stats
POST /v1/admin/cache/clear             # Flush the LLM response cache
GET  /v1/admin/circuit-breaker/status  # Breaker state, failure count, last failure time
POST /v1/admin/circuit-breaker/reset   # Reset open circuit to CLOSED
GET  /v1/admin/metrics                 # JSON metrics snapshot
GET  /v1/admin/config                  # Non-sensitive config (no API keys)
```

**Example — circuit breaker status:**

```json
{
  "state": "open",
  "failure_count": 5,
  "last_failure_time": "2026-06-19T10:15:00Z",
  "threshold": 5
}
```

**Example — non-sensitive config:**

```json
{
  "version": "1.0.0",
  "env": "production",
  "automation_framework": "playwright",
  "llm_provider": "gemini",
  "primary_model": "gemini-2.5-pro",
  "rate_limit_enabled": true,
  "cache_enabled": true,
  "stream_max_concurrent": 10,
  "intent_correction_enabled": true
}
```

---

## Security

### API Key

Every request except the lightweight health endpoints (`/v1/health/` and `/v1/health/ready`) must include the `X-API-Key` header. `/v1/health/deep` and all `/v1/metrics/` and `/v1/admin/` endpoints also require the key.

```bash
curl -H "X-API-Key: <your-key>" http://localhost:8001/generate/ \
     -d '{ ... }' -H "Content-Type: application/json"
```

The service **refuses to start** if `API_KEY` is empty, a known placeholder, or shorter than 32 characters. Key comparison uses `hmac.compare_digest` (constant-time) to prevent timing attacks.

Generate a strong key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Trusted Proxy (`TRUST_FORWARDED_IP`)

By default, the service resolves the client IP from the direct TCP peer (`request.client.host`) and **ignores** `X-Forwarded-For` and `X-Real-IP`. This prevents IP spoofing when the service is exposed directly.

Set `TRUST_FORWARDED_IP=true` **only** when the service is sandboxed behind a reverse proxy (Nginx, HAProxy, AWS ALB) that is configured to set and sanitize forwarded headers.

### CORS

`CORS_ORIGINS` should list your exact frontend origins:

```env
CORS_ORIGINS=https://app.yourcompany.com,https://staging.yourcompany.com
```

The wildcard `*` is **blocked** when `ENV=production`.

### Path Traversal Protection

Output filenames are resolved to absolute paths and validated with `resolved_path.is_relative_to(_OUTPUT_DIR)`. This replaces the previous string-prefix check which was bypassable via `../` traversal.

### Request Body Size Limit

The body-size middleware enforces the size limit on both fixed-length and streaming (chunked) request bodies. A request without `Content-Length` is now correctly rejected with HTTP 413 when it exceeds the limit.

### Webhook SSRF Protection

All webhook URLs are validated before any network call:
- Private RFC-1918 ranges (`10.x`, `192.168.x`, `172.16-31.x`) — blocked
- Loopback (`127.0.0.1`, `::1`, `localhost`) — blocked
- AWS instance metadata (`169.254.169.254`) — blocked
- Non-HTTP schemes (`ftp://`, `file://`) — blocked

### Webhook Payload Signing

When `WEBHOOK_SECRET` is set, every outgoing webhook payload is signed:

```
X-Webhook-Signature: sha256=<hmac-sha256-hex>
```

Verify on the receiver side:

```python
import hmac, hashlib

expected = hmac.new(
    WEBHOOK_SECRET.encode(),
    request.body,
    hashlib.sha256
).hexdigest()

assert hmac.compare_digest(f"sha256={expected}", request.headers["X-Webhook-Signature"])
```

### Webhook Payload Schema

All webhook payloads follow a versioned schema (added Phase 11):

```json
{
  "event": "script.generated",
  "schema_version": "1.0",
  "timestamp": "2026-06-19T10:30:00.000Z",
  "request_id": "a1b2c3d4",
  "status": "success",
  "test_case_id": "TC001",
  "duration_ms": 6100.0,
  "tokens_used": 1842
}
```

Failure payloads use `"event": "script.failed"` and include an `"error"` field. Batch completions use `"event": "batch.completed"`.

### Atomic Rate Limiting

The Redis rate limiter uses a Lua script executed atomically on the Redis server — ZADD and ZREMRANGEBYSCORE are issued as a single unit, eliminating the race condition present in a two-command check-then-add approach. The `Retry-After` header returns the exact number of seconds until the oldest in-window request expires.

---

## Docker Deployment

### Build and run

```bash
docker build -t automation-script-generator .

docker run -d \
  --name asg \
  -p 8000:8000 \
  -e API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e GOOGLE_API_KEY="your-gemini-key" \
  -e ENV=production \
  -e CORS_ORIGINS="https://yourapp.com" \
  automation-script-generator
```

### With Redis (recommended for production)

```bash
docker run -d --name redis redis:7-alpine

docker run -d \
  --name asg \
  -p 8000:8000 \
  --link redis:redis \
  -e API_KEY="..." \
  -e GOOGLE_API_KEY="..." \
  -e REDIS_URL="redis://redis:6379/0" \
  -e ENV=production \
  automation-script-generator
```

### Health check

The Docker image includes a built-in `HEALTHCHECK` that polls `/health/` every 30 seconds.

```bash
docker inspect --format='{{.State.Health.Status}}' asg
# healthy
```

---

## Testing

### Run all tests

```bash
pip install -r requirements-dev.txt
pytest
```

### Run with coverage

```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

### Run a specific file

```bash
pytest tests/test_cache.py -v
pytest tests/test_webhook_notifier.py -v
```

### Test environment

The test suite automatically injects a valid `API_KEY` before collection via `tests/conftest.py`. No `.env` changes are needed to run tests.

### Test coverage areas

| File | What is tested |
|---|---|
| `test_config_validation.py` | API key strength, CORS wildcard guard, LLM provider whitelist |
| `test_middleware_rate_limit.py` | IP resolution, sliding window enforcement, window expiry, cleanup |
| `test_cache.py` | CRUD, TTL, LRU eviction, stats, concurrency safety |
| `test_assembler.py` | `output_dir` regression, sync/async assembly, path traversal |
| `test_webhook_notifier.py` | SSRF protection, payload size guard, HMAC signing |
| `test_cleanup.py` | File age deletion, error resilience, loop lifecycle |
| `test_batch_processor.py` | Token aggregation race condition, cost fallback, status transitions |
| `test_proxy.py` | IP header extraction with trust enabled/disabled |
| `test_core_regressions.py` | Cost estimator, script parser, token tracker, action renderer |
| `test_llm_json_regressions.py` | JSON recovery from key-value LLM output, assertion extractor fallback |

---

## Project Structure

```
Automation-Script-Generator-Enhanced/
├── app/
│   ├── main.py                  # FastAPI app + lifespan + JSON logging
│   ├── core/
│   │   ├── config.py            # Pydantic Settings (all config, incl. LOG_FORMAT, GENERATION_TIMEOUT_SECONDS)
│   │   ├── cache.py             # LRU cache (in-memory + Redis SCAN)
│   │   ├── circuit_breaker.py   # LLM failover (single failure per breach)
│   │   ├── cleanup.py           # Background file cleanup task
│   │   ├── cost_estimator.py    # Pre-flight cost estimation
│   │   ├── exceptions.py        # Domain exceptions
│   │   ├── framework_profiles.py# FrameworkProfile with verifier_constraints
│   │   ├── llm_executor.py      # Semaphore + retry + failover (circuit breaker fix)
│   │   ├── llm_json.py          # generate_json() + JSONDecoder.raw_decode() fix
│   │   ├── metrics.py           # Prometheus-compatible metrics
│   │   ├── token_tracker.py     # Per-request token aggregation (ContextVar)
│   │   └── llm/
│   │       ├── __init__.py      # Re-exports LLMConfig, LLMResponse, provider factory
│   │       ├── base.py          # BaseLLMProvider, LLMConfig (incl. response_schema)
│   │       ├── gemini_provider.py  # Gemini backend + schema adaptation
│   │       └── openai_provider.py  # OpenAI backend + json_schema response format
│   ├── middleware/
│   │   ├── api_key.py           # API key authentication (constant-time compare)
│   │   ├── audit.py             # Request/response audit logging
│   │   ├── body_size.py         # Request body size limit (streaming-body guard)
│   │   ├── metrics.py           # Request metrics middleware
│   │   └── rate_limit.py        # Sliding window rate limiter (Redis/in-memory)
│   ├── models/
│   │   ├── batch.py             # Batch request/response models
│   │   ├── cir.py               # CIR models (17 ActionTypes, 16 AssertionTypes, 15 LocatorStrategies)
│   │   ├── matched_script.py    # Matched script reference
│   │   └── test_case.py         # TestCase / Step (max_retries) / Prerequisite + teardown_steps
│   ├── prompts/
│   │   └── template_engine.py   # Instance-level template dict (class mutation fix)
│   ├── routes/
│   │   ├── admin.py             # GET|POST /v1/admin/* (API key protected)
│   │   ├── batch.py             # POST /v1/batch/
│   │   ├── cost.py              # POST /v1/cost/estimate
│   │   ├── generate.py          # POST /v1/generate/ (request ID propagation, path traversal fix)
│   │   ├── generate_matrix.py   # POST /v1/matrix/generate
│   │   ├── health.py            # GET  /v1/health/* (/deep requires API key)
│   │   ├── metrics.py           # GET  /v1/metrics/ (API key protected)
│   │   ├── stream.py            # POST /v1/stream/generate (lazy semaphore, assemble_async)
│   │   └── validate.py          # POST /v1/validate/ (dry-run CIR build)
│   └── services/
│       ├── assembler.py         # Script assembly — framework ext, run_id, request_id in header
│       ├── batch_processor.py   # Parallel batch orchestration (delegates to GenerationService)
│       ├── cir_builder.py       # TestCase → CIR (teardown, parallel prerequisites, config-driven intent correction)
│       ├── generation_service.py# Unified pipeline (shared by /generate, /batch, /stream)
│       ├── validator.py         # CIR validation — includes teardown blocks
│       ├── webhook_notifier.py  # HMAC-signed, SSRF-safe, versioned webhook dispatch (singleton)
│       ├── build_helpers/
│       │   ├── assert_extractor.py      # Assertion extraction (hardcode removed)
│       │   ├── base_extractor.py        # extract_wait() context-aware + _normalize_strategy()
│       │   ├── cir_action_builders.py   # 7 new _safe_*_action() builders
│       │   ├── click_extractor.py
│       │   ├── framework_role_upgrader.py  # Structure check (control-flow count)
│       │   ├── intent_corrector.py      # Regex-based locator mutation detection
│       │   ├── llm_classifier.py        # 11 new action type heuristics
│       │   ├── script_parser.py         # Playwright semantic API + iOS Appium patterns
│       │   ├── select_extractor.py
│       │   └── type_extractor.py
│       ├── framework_helpers/
│       │   ├── action_renderer.py       # 11 new renderers, link role fix
│       │   ├── appium_templates.py
│       │   ├── playwright_templates.py
│       │   ├── selenium_templates.py
│       │   └── step_verifier.py         # Framework-aware verifier constraints
│       └── generators/
│           ├── base_generator.py        # Multi-action support, get_file_extension()
│           ├── appium_generator.py
│           ├── cypress_generator.py     # get_file_extension() → ".js"
│           ├── playwright_generator.py  # Registry reset per call
│           └── selenium_generator.py
├── tests/
│   ├── conftest.py
│   ├── test_assembler.py
│   ├── test_batch_processor.py
│   ├── test_cache.py
│   ├── test_cleanup.py
│   ├── test_config_validation.py
│   ├── test_core_regressions.py
│   ├── test_llm_json_regressions.py     # New: JSON recovery + assertion extractor tests
│   ├── test_middleware_rate_limit.py
│   ├── test_proxy.py
│   └── test_webhook_notifier.py
├── fixtures/                    # Sample test case JSON files
├── CLAUDE.md                    # Developer reference (pipeline, adding new action types)
├── Dockerfile
├── .dockerignore
├── .env.example                 # Template — copy to .env and fill in
├── requirements.txt             # Runtime dependencies
├── requirements-dev.txt         # Test/dev dependencies
└── pytest.ini
```

---

## Cypress Note

Because Cypress executes inside a Node.js runner that controls the browser environment, **video recording is handled globally** via `cypress.config.js` — not inside individual test files. Generated Cypress scripts use the `.js` extension and will **not** inject video recording code. Ensure `video: true` is set in your Cypress configuration if you need video artifacts.

---

## Changelog

### 1.0.0 — June 2026 (Phase 11 Audit & Hardening)

**Breaking changes:**
- All routes moved to `/v1/` prefix. Update client base URLs.
- `/v1/health/deep`, `/v1/metrics/*`, and `/v1/admin/*` now require `X-API-Key`.
- Error responses now use the structured envelope format (see [Error Envelope](#error-envelope)).

**New:**
- Admin API at `/v1/admin/*` (cache, circuit breaker, metrics, config)
- `STREAM_MAX_CONCURRENT` config setting
- `INTENT_CORRECTION_ENABLED` config setting
- `skipped_items` field in batch result
- `Retry-After` header returns exact wait time on 429 responses
- Versioned webhook payload schema (`event`, `schema_version`, `timestamp`)
- Generated scripts include `# Request ID` header comment for traceability
- OpenAPI schema (`/openapi.json`) always accessible in all environments

**Fixed:**
- Cypress batch items now correctly use `.js` extension (BUG-1, BUG-2)
- Teardown blocks now validated in generation service and stream route (BUG-3)
- Stream route was blocking the event loop with synchronous assembly (BUG-4)
- Async temp file extension was always `.py` regardless of framework (BUG-5)
- Module-level `asyncio.Semaphore` in stream route caused Python 3.10+ deprecation (BUG-6)
- Redis rate limiter had ZADD/ZREMRANGEBYSCORE race — replaced with atomic Lua script (BUG-7)
- Intent correction emitted excessive `WARNING` log entries (BUG-8)
- `localhost.` (trailing dot) DNS rebinding vector now blocked (BUG-9)
- `CORS_ORIGINS=["https://a.com"]` JSON array string format now parsed correctly (BUG-10)
- Log file handler used relative path — broke when server started outside project root (BUG-11)
- Batch cost estimate was extrapolating first item's cost — now sums per-item (BUG-12)

**Improved:**
- Batch processor delegates to `GenerationService` — single unified pipeline (ARCH-1)
- LRU cache normalises prompt whitespace before hashing — eliminates cache misses from cosmetic differences (SOF-2)
- Circuit breaker fast-fails on permanent errors (4xx auth/billing) without threshold countdown (SOF-3)
- Histogram insert is O(log n) via `bisect.insort` (SOF-4)
- CIR prerequisites built in parallel (SOF-5)
- Sanitization logs a warning when content is redacted (SOF-7)
- LLM raw-response debug logs capped at 200 chars (ENT-10)
- `get_webhook_notifier()` singleton factory — clean startup/shutdown (MOD-1)
- All inline imports moved to module level (MOD-4)

---

### 0.x — January–May 2026 (Phases 1–10)

See [What's New — Enhanced Edition](#whats-new--enhanced-edition) for the full Phase 1–10 feature history.

---

## License

MIT License — see LICENSE file for details.

---

*Created by Mokshith Balidi · TW.2324 | Enhanced Edition — June 2026*
