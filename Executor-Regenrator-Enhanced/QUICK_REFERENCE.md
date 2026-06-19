# Quick Reference Guide

## Start Here 👇

### For First-Time Users

1. **What is this?**  
   → Automated Playwright test repair using AI (Google Gemini LLM)

2. **How do I run it locally?**
   ```bash
   # Activate venv first
   .\venv\Scripts\activate    # Windows
   source venv/bin/activate   # Linux / macOS

   # Run with pretty colorized developer logs (default: binds to 127.0.0.1:8000)
   python run.py --mode pretty

   # Or run using Docker (app listens on port 8080 inside container)
   docker build -t repair-engine:latest .
   docker run -p 8080:8080 -e GOOGLE_API_KEY="your-key" repair-engine:latest
   ```

3. **How do I use it?**
   ```bash
   curl -X POST http://127.0.0.1:8000/repair \
     -H "X-API-Key: client_sec_key" \
     -F 'payload={
       "step_id": "test_1",
       "step_intent": "Click login",
       "original_code": "await page.click(\"#btn\")",
       "error_classification": {"type": "LOCATOR_NOT_FOUND"},
       "error_details": {"message": "Timeout"}
     }'
   ```

---

## Essential Commands

### Development

```bash
# Start locally with pretty logs (auto-reload on app/ directory)
python run.py --mode pretty

# Start without reload (cleaner for executor runs — avoids noise from script writes)
python run.py --no-reload

# Start with JSON logs (staging simulation)
python run.py --mode json

# Expose to network (team / Docker host)
python run.py --host 0.0.0.0 --port 8000

# Run tests
python -m pytest -q

# Run tests with coverage
pytest --cov=app --cov-report=html

# View Prometheus metrics
curl http://127.0.0.1:8000/metrics
```

### Deployment

```bash
# Build image
docker build -t repair-engine:latest .

# Run container (app binds to 0.0.0.0:8080 inside container)
docker run -p 8080:8080 \
  -e GOOGLE_API_KEY="your-key" \
  -e MONGODB_URL="mongodb+srv://..." \
  repair-engine:latest

# Deploy to Kubernetes
kubectl apply -f api-deployment.yaml

# Scale API instances
kubectl scale deployment repair-engine-api --replicas=5
```

### Database (MongoDB)

```bash
# Indexes are auto-created on startup — no migration commands needed

# View active indexes
mongosh "mongodb://localhost:27017/repair_engine" --eval "db.repair_records.getIndexes()"
```

---

## API Quick Commands

### Health Checks

```bash
# Is it alive?
curl http://127.0.0.1:8000/health/live

# Can it serve traffic? (checks MongoDB, Redis, memory, disk, API keys)
curl http://127.0.0.1:8000/health/ready

# Full observability including LLM ping
curl http://127.0.0.1:8000/health/deep

# Show all Prometheus metrics
curl http://127.0.0.1:8000/metrics

# App metadata and feature flags
curl http://127.0.0.1:8000/info
```

### Repair Endpoint

```bash
# Repair a failing step (multipart/form-data with optional screenshot)
curl -X POST http://127.0.0.1:8000/repair \
  -H "X-API-Key: client_sec_key" \
  -F 'payload={
    "step_id": "step_1",
    "step_intent": "Click Login Button",
    "original_code": "await page.click('"'"'#login-btn'"'"')",
    "error_classification": {"type": "LOCATOR_NOT_FOUND"},
    "error_details": {"message": "Timeout"}
  }'
```

### Execute Script

```bash
# Run script with self-healing executor — returns a ZIP file
curl -X POST http://127.0.0.1:8000/executor/playwright/run \
  -H "X-API-Key: client_sec_key" \
  -F "script=@tests/scripts/failing_test.py" \
  --output result.zip

# Check the semantic result (ALWAYS do this — HTTP 200 does NOT mean the test passed)
unzip result.zip -d result/
cat result/artifacts/status.txt           # "passed" or "failed"
cat result/repair_report.json             # full repair history (if passed)
cat result/final_failure_explanation.json # root cause (if failed)

# Get executor statistics
curl http://127.0.0.1:8000/executor/stats \
  -H "X-API-Key: client_sec_key"
```

---

## Executor Output — What You Actually Get Back

> ⚠️ **The executor ALWAYS returns HTTP 200 with a ZIP file.** Check `X-Semantic-Status` header or `status.txt` inside the ZIP to know if the test passed or failed. Never assume HTTP 200 = test passed.

### Response Headers (both pass and fail)

| Header | Example | Meaning |
|--------|---------|---------|
| `X-Semantic-Status` | `passed` or `failed` | **The actual test outcome** |
| `X-Run-ID` | `a3f9b21c` | Unique run identifier |
| `X-Request-ID` | `4e8d123abc01` | Correlation ID for logs |
| `X-Duration-Ms` | `12340.5` | Total time in milliseconds |
| `X-Script-Hash` | `3fa8c1d90e41` | SHA256 of the uploaded script |

### ✅ Success — ZIP Contents

```
<run_id>/
├── <script_filename>.py           ← original (possibly patched) script
├── artifacts/
│   ├── steps/<step_id>/
│   │   ├── status.txt             ← "passed"
│   │   ├── summary.json           ← per-step timings
│   │   └── screenshot.png         ← final screenshot
│   └── status.txt                 ← "passed" (top-level)
├── final_script.py                ← the healed script
└── repair_report.json             ← repair history
```

**`repair_report.json`** (no repairs needed):
```json
{
  "final_status": "passed",
  "iterations": 1,
  "repairs": [],
  "execution_id": "a3f9b21c",
  "timestamp": "2026-06-02T10:01:00Z"
}
```

**`repair_report.json`** (after self-healing):
```json
{
  "final_status": "passed",
  "iterations": 2,
  "repairs": [
    {
      "step_id": "TC_PARABANK__step_5",
      "attempt": 1,
      "outcome": "patched",
      "explanation": {"root_cause": "...", "recommendation": "..."},
      "timestamp": "2026-06-02T10:01:15Z"
    }
  ]
}
```

### ❌ Failure — ZIP Contents

```
<run_id>/
├── <script_filename>.py           ← script (possibly partially patched)
├── artifacts/
│   └── <step_id>/
│       ├── status.txt             ← "failed"
│       ├── error.txt              ← raw traceback
│       ├── dom_snapshot.html      ← DOM at failure point
│       ├── step_summary.json      ← step context for repair
│       └── screenshot.png         ← screenshot at failure
└── final_failure_explanation.json ← LLM root-cause analysis
```

**`final_failure_explanation.json`**:
```json
{
  "step_id": "TC_PARABANK__step_5",
  "step_intent": "click the Send Payment button",
  "original_code": "await page.click('#sendPayment')",
  "repaired_code": "PERMANENT_FAILURE (Self-healing attempts exhausted)",
  "root_cause": "Button ID changed from #sendPayment to #submit-payment",
  "recommendation": "Update locator to: page.get_by_role('button', name='Send Payment')"
}
```

---

## 🔒 Sandbox Security — Disallowed Imports & Calls

### 🚫 Forbidden Imports (Always Blocked)

| Module | Reason |
|--------|--------|
| `subprocess` | Shell command execution |
| `shutil` | File system manipulation |
| `ctypes` | Direct C/OS memory access |
| `multiprocessing` | Spawning new processes |
| `signal` | OS signal sending (SIGKILL etc.) |
| `socket` | Raw network socket access |
| `http.server` | Spawning HTTP servers |
| `ftplib` | FTP client |
| `smtplib` | Email sending |
| `telnetlib` | Telnet access |
| `pickle` | Arbitrary object deserialization |
| `marshal` | Bytecode deserialization |
| `shelve` | Persistent pickle-backed store |
| `code` | Interactive interpreter embedding |
| `codeop` | Incremental code compilation |
| `pty` | Pseudo-terminal control |
| `tty` | Terminal control |
| `fcntl` | UNIX file control |
| `resource` | UNIX resource limit control |
| `sysconfig` | Python build config access |
| `gc` | Garbage collector control |
| `importlib` | Dynamic module loading |

### ✅ Allowed Imports (Strict Mode — Only These)

`playwright`, `playwright.sync_api`, `playwright.async_api`, `asyncio`, `re`, `json`, `time`, `datetime`, `typing`, `dataclasses`, `enum`, `functools`, `itertools`, `collections`, `math`, `random`, `string`, `uuid`, `os` *(path ops only)*, `pathlib` *(limited)*, `logging`, `traceback`, `inspect`, `sys`, `hashlib`

### 🚫 Forbidden Function Calls

| Call | Reason |
|------|--------|
| `eval(...)` | Arbitrary code execution |
| `exec(...)` | Arbitrary code execution |
| `compile(...)` | Bytecode compilation |
| `__import__(...)` | Dynamic import |
| `memoryview(...)` | Raw memory access |
| `listdir(...)` | Directory listing |

### 🚫 Forbidden Method/Attribute Calls (On Any Object)

`system`, `popen`, `spawn*` (all variants), `Popen`, `call`, `check_call`, `check_output`, `rmtree`, `remove`, `unlink`, `rename`, `rmdir`, `scandir`, `kill`, `fork`, `forkpty`, `startfile`, `exec*` (all variants), `read_text`, `read_bytes`, `glob`, `rglob`, `iterdir`, `resolve`, `absolute`, `chmod`, `chown`, `modules`

### 🚫 Dangerous Patterns (Regex Layer)

| Pattern | Reason |
|---------|--------|
| `.mro()` | Class hierarchy traversal abuse |
| `.subclasses()` | Privilege escalation via subclass enumeration |
| `breakpoint()` | Interactive debugger injection |

### 🚫 Blocked Attribute Access (AST Layer)

Any attribute starting with `__` is blocked:  
`__dict__`, `__code__`, `__globals__`, `__class__`, `__builtins__`, `__import__`, etc.

### ➕ How to Whitelist a New Library

To whitelist a new module for scripts:
1. Ensure the module is not listed in `FORBIDDEN_IMPORTS` inside [sandbox.py](file:///c:/Users/Mokshith%20Balidi/Downloads/Executor-Regenrator/app/executors/sandbox.py).
2. Add the base module name to the `ALLOWED_IMPORTS` set in `app/executors/sandbox.py`.
3. Optionally add dangerous attributes/functions in that module to `FORBIDDEN_ATTRS` or `FORBIDDEN_CALLS`.
4. Test by running: `python -m pytest tests/test_security.py -v`.
5. Restart the server/application to apply.

---

## File Structure Cheat Sheet

```
app/
├── api/v1/                      → Compatibility wrappers (re-export live routes)
├── core/
│   ├── exceptions/              → Exception package (base, api, repair, executor)
│   ├── repositories/            → DB repos (base, in_memory, mongo)
│   ├── base64_utils.py          → Base64 image validators
│   ├── config.py                → Settings manager & env variable definitions
│   ├── database.py              → Motor MongoDB connection manager
│   ├── dom_pruner.py            → Compresses HTML to AST tag tree
│   ├── health.py                → Health monitors & readiness checks
│   ├── io.py                    → Atomic file writer
│   ├── llm_executor.py          → Gemini API wrapper with retries
│   ├── llm_json.py              → Cleans & parses LLM JSON responses
│   ├── metrics.py               → Prometheus metric definitions
│   ├── prompts.py               → Central LLM prompt registry
│   ├── redis_state.py           → Distributed state & cache
│   ├── resilience.py            → CircuitBreaker & exponential backoff
│   ├── security.py              → API key auth & rate limiting
│   ├── tracing.py               → OpenTelemetry span wrappers
│   └── utils.py                 → Hashing, timers, FailureFingerprint, correlation IDs
├── executors/
│   ├── base.py                  → Abstract executor base class
│   ├── models.py                → ExecutionResult dataclass & ExecutionOutcome enum
│   ├── python.py                → AsyncPythonExecutor + SandboxedPythonExecutor
│   └── sandbox.py               → AST security auditor (two-layer: AST + regex)
├── models/
│   ├── cir.py                   → CIR schemas & ActionType enum
│   ├── context.py               → Runtime validation context models
│   ├── database.py              → RepairRecord & ExecutionRecord
│   ├── extraction.py            → Locator value models
│   └── step_repair.py           → Pydantic schemas for /repair
├── routes/
│   ├── executor.py              → POST /executor/{framework}/run, GET /executor/stats
│   ├── health.py                → GET /health/*
│   ├── metrics.py               → GET /metrics
│   └── repair.py                → POST /repair
├── services/
│   ├── extractors/              → ClickExtractor, TypeExtractor, SelectExtractor, AssertExtractor, DialogExtractor, ExtractorFactory
│   ├── atomic_normalizer.py     → Text normalizer
│   ├── auto_repair_trigger.py   → Parses failure dirs → StepRepairRequest
│   ├── cir_builder.py           → Builds CIR blocks
│   ├── diff.py                  → Unified diff utility
│   ├── execution_orchestrator.py → Self-healing loop (execute → repair → patch → retry)
│   ├── generator.py             → Generates Playwright code from locators
│   ├── llm_classifier.py        → Classifies action types via LLM
│   ├── llm_fallback_repair.py   → Secondary LLM repair with full context
│   ├── repair_explanation_service.py → Generates LLM repair summaries
│   ├── repair_pipeline.py       → CIR → gen → verify → modify → verify
│   ├── repair_service.py        → FastAPI repair handler
│   ├── rollback.py              → Script backup & rollback
│   ├── script_patcher.py        → Patches step body + _guarded_step() arg
│   ├── step_modifier.py         → Verifier-guided code variations
│   ├── step_verifier.py         → Sandboxed proposal validator
│   └── validator.py             → Pre-flight validators
├── tasks/
│   ├── celery_app.py            → Celery config
│   └── repair_tasks.py          → Async Celery task definitions
├── main.py                      → App entry: PrettyFormatter, middleware stack, lifespan
└── middleware.py                → Audit log & request timing
run.py                           → Dev startup wrapper (venv guard, --mode, --host, --port, --no-reload)
```

---

## Configuration Quick Setup

```bash
# Minimum required
GOOGLE_API_KEY=your-gemini-key
ALLOWED_API_KEYS=["client_sec_key"]
ENABLE_API_AUTH=true

# Persistent storage
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=repair_engine

# Distributed state & Celery
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Logging
LOG_LEVEL=INFO
LOG_FORMAT_MODE=PRETTY    # PRETTY | CONSOLE | JSON

# Sandbox
ENABLE_SANDBOX_EXECUTION=true
SANDBOX_USE_DOCKER=false  # set true in production

# Run locally
python run.py --mode pretty
```

> **MongoDB indexes are created automatically on startup. No migration commands required.**

---

## Monitoring Quick Access

```bash
http://127.0.0.1:8000/metrics      # Prometheus scrape endpoint
http://127.0.0.1:8000/health/ready # Readiness check
http://127.0.0.1:8000/docs         # Swagger UI (development only)
http://127.0.0.1:8000/info         # App metadata & feature flags
http://localhost:9090               # Prometheus UI (if self-hosted)
http://localhost:3000               # Grafana (admin/admin)
http://localhost:16686              # Jaeger Tracing (if ENABLE_TRACING=true)
```

---

## Common Issues & Fixes

| Issue | Quick Fix |
|-------|-----------|
| Port already in use | `tasklist /FI "IMAGENAME eq python.exe"` → `taskkill /PID <pid> /F` |
| `uvicorn` not found | Activate venv: `.\venv\Scripts\activate` |
| MongoDB connection error | Check `MONGODB_URL` in `.env` |
| Rate limit exceeded | Increase `RATE_LIMIT_REQUESTS_PER_MINUTE` |
| LLM timeout | Increase `LLM_TIMEOUT_SECONDS` |
| Tests failing | `pytest tests/ -v` |
| `403 Script rejected by sandbox` | Remove forbidden imports/calls — see Sandbox section above |
| `503 Executor sandbox disabled` | Set `ENABLE_SANDBOX_EXECUTION=true` or `SANDBOX_USE_DOCKER=true` |
| `ImportError: global_exception_handler` | Delete `app/core/exceptions.py` (conflicts with `exceptions/` folder) |
| HTTP 200 but test failed | Check `X-Semantic-Status` header and unzip the result — see Executor Output section |

---

## Environment Variables (Essentials)

```bash
# ── Required ─────────────────────────────────────────────────
GOOGLE_API_KEY=...                     # Primary Gemini API key
API_SECRET_KEY=...                     # Random secret for auth
ALLOWED_API_KEYS=["client_sec_key"]    # Accepted keys list

# ── Database ─────────────────────────────────────────────────
MONGODB_URL=mongodb://...              # MongoDB connection string
MONGODB_DB_NAME=repair_engine          # Target database

# ── Redis & Celery ───────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ── LLM ──────────────────────────────────────────────────────
LLM_MODEL_NAME=gemini-2.5-pro
LLM_TIMEOUT_SECONDS=150
LLM_MAX_RETRIES=3

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL=INFO                         # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT_MODE=PRETTY                 # PRETTY | CONSOLE | JSON
ENV=development                        # development | staging | production

# ── Feature Flags ────────────────────────────────────────────
ENABLE_API_AUTH=true
ENABLE_SELF_HEALING=true
ENABLE_SANDBOX_EXECUTION=true
ENABLE_METRICS=true
ENABLE_TRACING=false

# ── Sandbox ──────────────────────────────────────────────────
SANDBOX_USE_DOCKER=false               # true in production
ALLOW_UNSAFE_HOST_EXECUTION_IN_PRODUCTION=false

# ── Rate Limiting ────────────────────────────────────────────
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_BURST_SIZE=10

# ── Repair Limits ────────────────────────────────────────────
MAX_LLM_MODIFICATIONS=1
EXECUTOR_TIMEOUT_SECONDS=800
```

---

## API Error Codes

| Code | Status | Meaning |
|------|--------|---------|
| `INVALID_API_KEY` | 401 | Wrong or missing API key |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INVALID_REQUEST` | 400 | Bad request format |
| `LLM_TIMEOUT` | 504 | Gemini API timed out |
| `DATABASE_ERROR` | 500 | DB connection failed |
| `CIRCUIT_BREAKER_OPEN` | 503 | Service temporarily down |
| `EXECUTOR_SANDBOX_DISABLED` | 503 | Sandbox disabled or unavailable |

---

## Database Quick Queries (MongoDB)

```javascript
// How many repairs succeeded today?
db.repair_records.countDocuments({
  outcome: "success",
  created_at: { $gt: new Date(Date.now() - 24*60*60*1000) }
})

// Most common error types
db.repair_records.aggregate([
  { $group: { _id: "$error_type", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])

// Average repair duration
db.repair_records.aggregate([
  { $match: { outcome: "success" } },
  { $group: { _id: null, avg_duration: { $avg: "$duration_ms" } } }
])

// Top 10 failing steps
db.repair_records.aggregate([
  { $match: { outcome: "failure" } },
  { $group: { _id: "$step_id", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 10 }
])
```

---

## Celery Quick Commands

```bash
# Start workers
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4

# Check active workers
celery -A app.tasks.celery_app inspect active

# Check pending tasks
celery -A app.tasks.celery_app inspect reserved

# Purge all tasks
celery -A app.tasks.celery_app purge

# Monitor real-time
celery -A app.tasks.celery_app events
```

> Celery workers are **optional**. The engine runs fully synchronously without them.

---

## Redis Quick Commands

```bash
# Connect
redis-cli

# Check memory usage
redis-cli INFO memory

# View all repair-engine keys
redis-cli KEYS "repair:*"

# Monitor commands in real-time
redis-cli MONITOR
```

---

## Deployment Checklist

- [ ] MongoDB running and reachable (`MONGODB_URL` configured)
- [ ] Redis running (optional — needed for Celery & distributed state)
- [ ] `GOOGLE_API_KEY` set in `.env`
- [ ] `ALLOWED_API_KEYS` configured
- [ ] `ENABLE_API_AUTH=true` confirmed
- [ ] `ENABLE_SANDBOX_EXECUTION=true` confirmed
- [ ] Docker sandboxing enabled for production (`SANDBOX_USE_DOCKER=true`)
- [ ] MongoDB indexes auto-created on startup (verify via `/health/ready`)
- [ ] Tests passing (`pytest tests/ -v`)
- [ ] Health check passing (`curl /health/ready`)
- [ ] Metrics accessible (`curl /metrics`)
- [ ] Logging configured (`LOG_FORMAT_MODE`, `LOG_LEVEL`)
- [ ] Data retention policy confirmed (30-day TTL via MongoDB TTL index)
- [ ] `run.py` binds to `127.0.0.1` by default; use `--host 0.0.0.0` only when needed

---

## One-Liner Deployments

```bash
# Local development (default: 127.0.0.1:8000)
python run.py

# Local — exposed to network
python run.py --host 0.0.0.0

# Docker run (container binds to 8080)
docker run -p 8080:8080 \
  -e GOOGLE_API_KEY="your-key" \
  -e MONGODB_URL="mongodb+srv://..." \
  repair-engine:latest

# Kubernetes
kubectl apply -f api-deployment.yaml

# Scale
kubectl scale deployment repair-engine-api --replicas=5 -n repair-engine

# Port forward to local
kubectl port-forward svc/repair-engine-api 8000:80 -n repair-engine
```

---

## Performance Benchmarks

| Metric | Target | Observed |
|--------|--------|---------|
| API Response Time | < 5s | ~3.4s |
| LLM Processing | < 60s | ~34s avg |
| Database Query | < 100ms | ~5ms avg |
| Health Check | < 1s | ~0.2s |
| P95 Latency | < 10s | ~8.9s |
| Error Rate | < 1% | ~0.5% |

---

## Troubleshooting Flowchart

```
Service not responding?
├─ Check: zombie python.exe? → tasklist → taskkill
├─ curl http://127.0.0.1:8000/health/live
│   ├─ Fails → process crashed. Restart with python run.py
│   └─ OK → curl /health/ready
│       ├─ Not ready → check MONGODB_URL, Redis
│       └─ Ready → call an endpoint
│           ├─ 401 → check X-API-Key header value vs ALLOWED_API_KEYS
│           ├─ 403 → script blocked by sandbox — remove forbidden imports
│           ├─ 429 → reduce request rate or raise RATE_LIMIT_REQUESTS_PER_MINUTE
│           ├─ 503 → sandbox disabled or circuit breaker open
│           └─ 200 + ZIP → check X-Semantic-Status header
│               ├─ passed → ✅ Test succeeded
│               └─ failed → unzip → read final_failure_explanation.json
```

---

## Pro Tips 💡

1. **Use pretty mode**: `python run.py --mode pretty` for color-coded, emoji-enriched logs
2. **No venv?** → `run.py` will tell you exactly what command to run
3. **Debug logging**: `LOG_LEVEL=DEBUG` to see every MongoDB query and LLM call
4. **HTTP 200 ≠ Test Passed**: Always read `X-Semantic-Status` header from executor
5. **Check ZIP contents**: `status.txt`, `repair_report.json`, `final_failure_explanation.json`
6. **No PostgreSQL**: This app is **MongoDB only** — no SQL migrations
7. **Indexes auto-created**: MongoDB indexes are created on every startup
8. **Celery is optional**: The engine runs synchronously without Redis/Celery
9. **Sandbox by default**: All scripts go through the AST security validator before execution
10. **Patch is full**: `script_patcher.py` patches both the step function body AND the `_guarded_step(...)` string literal

---

## Version & Status

- **Version**: 3.0.0
- **Status**: ✅ Production Ready
- **Author**: Mokshith Balidi
- **Organization**: TW.2324
- **Created**: January 2026
- **Last Updated**: June 3, 2026
- **Python**: 3.11+
- **Rights**: All rights reserved by Mokshith Balidi

---

**Everything working? Great! You're ready to use the Playwright Step Repair Engine! 🚀**  
For full details, refer to `README.md`.
