# Quick Reference

## Base URL

`http://localhost:8001`

## Public Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | `GET` | Basic service metadata |
| `/health` | `GET` | Basic health |
| `/health/live` | `GET` | Liveness probe |
| `/health/ready` | `GET` | Readiness probe |
| `/health/deep` | `GET` | Deep diagnostics |
| `/auth/register` | `POST` | Create first admin or register user |
| `/auth/login` | `POST` | Get bearer token |

## Protected Endpoints

| Endpoint | Method | Role/Scope |
|---|---|---|
| `/auth/me` | `GET` | Any authenticated user |
| `/api/upload` | `POST` | `cases:write`, `uploads:write` |
| `/api/upload/jobs` | `GET` | `uploads:write` |
| `/api/upload/jobs/{job_id}` | `GET` | `uploads:write` |
| `/api/search` | `POST` | `search:read` |
| `/api/scripts/{script_id}` | `GET` | `scripts:read` |
| `/api/scripts/batch` | `POST` | `scripts:read` |
| `/api/update/{doc_id}` | `PUT` | `cases:write` |
| `/api/get-all` | `GET` | `cases:read` |
| `/api/get-all-scripts` | `GET` | `scripts:read` |
| `/api/stats` | `GET` | `stats:read` |
| `/api/get-by-id/{doc_id}` | `GET` | `cases:read` |
| `/api/get-script/{script_id}` | `GET` | `scripts:read` |
| `/api/delete/{doc_id}` | `DELETE` | `admin` |
| `/api/delete-all?confirm=true` | `POST` | `admin` |
| `/metrics` | `GET` | `admin` |
| `/metrics/json` | `GET` | `admin` |

## Roles

| Role | Grants |
|---|---|
| `viewer` | search, testcase read, script read, stats read |
| `editor` | viewer + testcase write + upload |
| `admin` | editor + destructive admin + user management |

## Auth Commands

Register first admin:

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ChangeMe123!","role":"admin"}'
```

Login:

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=ChangeMe123!"
```

Use token:

```bash
curl http://localhost:8001/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

## Upload

Synchronous:

```bash
curl -X POST "http://localhost:8001/api/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

Background:

```bash
curl -X POST "http://localhost:8001/api/upload?background=true" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

Job status:

```bash
curl http://localhost:8001/api/upload/jobs/<job_id> \
  -H "Authorization: Bearer $TOKEN"
```

## Search

```bash
curl -X POST http://localhost:8001/api/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"checkout payment failure","feature":"Payments","ranking_variant":"A"}'
```

## Script Fetch

Single script:

```bash
curl http://localhost:8001/api/scripts/<script_id> \
  -H "Authorization: Bearer $TOKEN"
```

Batch script fetch body is a raw JSON array:

```bash
curl -X POST http://localhost:8001/api/scripts/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '["script-id-1","script-id-2"]'
```

## Update

```bash
curl -X PUT http://localhost:8001/api/update/<doc_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority":"High","platform":"Web"}'
```

## Admin Operations

Stats:

```bash
curl http://localhost:8001/api/stats \
  -H "Authorization: Bearer $TOKEN"
```

Delete one:

```bash
curl -X DELETE http://localhost:8001/api/delete/<doc_id> \
  -H "Authorization: Bearer $TOKEN"
```

Delete all:

```bash
curl -X POST "http://localhost:8001/api/delete-all?confirm=true" \
  -H "Authorization: Bearer $TOKEN"
```

## Operational Checks

Metrics:

```bash
curl http://localhost:8001/metrics \
  -H "Authorization: Bearer $TOKEN"
```

Deep health:

```bash
curl http://localhost:8001/health/deep
```

## Most Important Environment Variables

```env
MONGO_CONNECTION_STRING=...
JWT_SECRET_KEY=...
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
LLM_USE_GEMINI=true
LLM_USE_OPENAI=false
LLM_USE_ANTHROPIC=false
LLM_USE_LOCAL=false
GOOGLE_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
LOCAL_LLM_API_URL=http://localhost:11434/v1/chat/completions
LOCAL_LLM_API_FORMAT=openai
EMBEDDING_USE_MINILM_384=true
EMBEDDING_USE_MPNET_768=false
EMBEDDING_USE_BGE_LARGE_1024=false
CACHE_BACKEND=auto
REDIS_URL=
INGESTION_WORKER_COUNT=1
FAIL_FAST_STARTUP=true
```

Exactly one `LLM_USE_*` flag and one `EMBEDDING_USE_*` flag should be enabled.
