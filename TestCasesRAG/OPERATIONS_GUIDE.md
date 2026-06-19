# Operations Guide

This document covers the parts of TestCasesRAG that matter once the app is deployed: startup validation, health, metrics, cache behavior, tracing, and background ingestion.

## Startup Model

The app now validates critical configuration before it serves traffic.

### Validated At Startup

- Mongo connection string exists
- CORS origins are configured and do not use `*`
- numeric runtime settings are positive
- tracing sample rate is between `0` and `1`
- Redis settings are complete when `CACHE_BACKEND=redis`
- non-development environments do not use the default JWT secret
- exactly one LLM provider flag is enabled when LLM startup is required
- exactly one embedding preset flag is enabled
- the selected provider has the required credentials or API URL

### Fail-Fast Control

```env
FAIL_FAST_STARTUP=true
```

Recommended:

- `true` in production
- `true` in staging
- optionally `false` only for local troubleshooting

## Health Endpoints

### `/health`

Use for a lightweight “process is running” check.

### `/health/live`

Use for liveness probes. This should answer whether the process should be restarted.

### `/health/ready`

Use for readiness probes. This now checks:

- MongoDB
- embedding model
- LLM backend
- cache backend
- runtime configuration
- ingestion worker manager

### `/health/deep`

Use for deep diagnostics and debugging. This includes request/error counters and component-level details.

## Metrics

### Endpoints

- `/metrics`: Prometheus text format
- `/metrics/json`: structured snapshot

Both are admin-protected.

### Current Metric Coverage

- request counts by method, path, and status code
- average request duration by method and path
- error counters
- search operation counts
- upload document counts
- cache hits and misses
- sampled trace counts
- background ingestion job counts by status

### Example Prometheus Scrape

If your Prometheus deployment supports bearer auth, scrape `/metrics` with an admin service token.

## Request Tracing

Each request carries:

- `X-Request-ID`
- `X-Correlation-ID`
- `X-Trace-ID`

The middleware now:

- generates IDs when the client does not provide them
- returns them on the response
- records request duration and status
- injects request context into structured logs

Trace sampling is controlled by:

```env
ENABLE_TRACING=true
TRACE_SAMPLE_RATE=0.1
```

## Cache Architecture

### Backends

- `memory`
- `redis`
- `auto`

`auto` is the safest default. It uses Redis when available and falls back to memory.

### Search Cache Invalidation

Search cache entries are versioned by namespace instead of being flushed wholesale.

That means:

- uploads invalidate search results immediately
- updates invalidate search results immediately
- deletes invalidate search results immediately
- unrelated cache keys do not need to be cleared

### Recommended Production Settings

```env
CACHE_ENABLED=true
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
CACHE_TTL_SECONDS=300
CACHE_MAX_SIZE=1000
```

## Background Ingestion

### What It Does

`POST /api/upload?background=true` stores an ingestion job in MongoDB and returns `202 Accepted`.

Workers then:

1. atomically claim queued jobs
2. parse the uploaded file
3. run dedupe, enrichment, embedding, and transactional inserts
4. update job status and result
5. invalidate search cache after successful writes

### Why This Matters

- uploads no longer need to hold the client connection open
- job state survives process restarts because it is stored in MongoDB
- scaled instances do not process the same queued job twice because claim is atomic

### Runtime Settings

```env
INGESTION_WORKER_COUNT=1
INGESTION_QUEUE_MAX_SIZE=100
INGESTION_JOB_RETENTION_HOURS=24
```

### Operational Checks

- `GET /api/upload/jobs`
- `GET /api/upload/jobs/{job_id}`
- `/health/ready`
- `/health/deep`
- `/metrics` or `/metrics/json`

## Suggested Production Environment

```env
ENVIRONMENT=production
FAIL_FAST_STARTUP=true
LOG_LEVEL=INFO
LOG_FORMAT=json

MONGO_CONNECTION_STRING=...
JWT_SECRET_KEY=replace-this
CORS_ALLOWED_ORIGINS=https://your-frontend.example.com

CACHE_ENABLED=true
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0

ENABLE_METRICS=true
ENABLE_TRACING=true
TRACE_SAMPLE_RATE=0.1

LLM_USE_OPENAI=true
LLM_USE_GEMINI=false
OPENAI_API_KEY=replace-this
OPENAI_MODEL=gpt-4o-mini

EMBEDDING_USE_MINILM_384=false
EMBEDDING_USE_MPNET_768=true
EMBEDDING_USE_BGE_LARGE_1024=false

INGESTION_WORKER_COUNT=2
INGESTION_QUEUE_MAX_SIZE=250
INGESTION_JOB_RETENTION_HOURS=48
```

## Recommended Alerts

- readiness probe failing for more than a few minutes
- repeated startup validation failures
- cache backend degraded when `CACHE_BACKEND=redis`
- background job failures increasing quickly
- request error rate rising above your normal baseline
- upload queue staying non-empty for too long

## Runbook Hints

### App refuses to boot

Check:

- startup log output
- missing or invalid `.env` values
- Mongo connectivity
- default JWT secret in non-development environments
- conflicting provider flags
- conflicting embedding preset flags

### Jobs remain queued

Check:

- worker count
- `/health/deep`
- `/metrics/json`
- ingestion job collection contents

### Search looks stale after writes

Check:

- mutation endpoint succeeded
- `/metrics/json` cache counters
- Redis availability when using distributed cache

### Ready check is `not_ready`

Inspect:

- database health
- embedding model state
- LLM backend state
- cache health
- configuration health
- ingestion manager state
