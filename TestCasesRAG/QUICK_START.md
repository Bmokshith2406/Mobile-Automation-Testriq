# Quick Start

This is the shortest path to a working local instance of TestCasesRAG with the upgraded auth and upload flows.

## 1. Install Dependencies

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Create Configuration

Copy `.env.example` to `.env` and set these values:

```env
MONGO_CONNECTION_STRING=your-mongodb-connection-string
JWT_SECRET_KEY=replace-this-with-a-long-random-secret
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
LLM_USE_GEMINI=true
LLM_USE_OPENAI=false
LLM_USE_ANTHROPIC=false
LLM_USE_LOCAL=false
GOOGLE_API_KEY=your-gemini-key
EMBEDDING_USE_MINILM_384=true
EMBEDDING_USE_MPNET_768=false
EMBEDDING_USE_BGE_LARGE_1024=false
```

Only one `LLM_USE_*` flag and one `EMBEDDING_USE_*` flag should be `true`.

Alternative LLM setups:

```env
LLM_USE_GEMINI=false
LLM_USE_OPENAI=true
OPENAI_API_KEY=your-openai-key
```

```env
LLM_USE_GEMINI=false
LLM_USE_ANTHROPIC=true
ANTHROPIC_API_KEY=your-anthropic-key
```

```env
LLM_USE_GEMINI=false
LLM_USE_LOCAL=true
LOCAL_LLM_API_URL=http://localhost:11434/v1/chat/completions
LOCAL_LLM_API_FORMAT=openai
LOCAL_LLM_MODEL=llama3.1
```

Useful optional settings:

```env
CACHE_BACKEND=auto
REDIS_URL=redis://localhost:6379/0
INGESTION_WORKER_COUNT=1
FAIL_FAST_STARTUP=true
```

## 3. Run The API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Open the docs at [http://localhost:8001/docs](http://localhost:8001/docs).

## 4. Run The Frontend In Development

```bash
cd frontend
npm install --ignore-scripts
node node_modules/esbuild/install.js
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## 5. Build The Frontend For FastAPI Hosting

```bash
cd frontend
npm run build
```

Once built, FastAPI serves the SPA from [http://localhost:8001/app](http://localhost:8001/app).

## 6. Create The First Admin

The very first registration becomes `admin` automatically.

```bash
$body = @{
    username = "admin"
    password = "Hello@7931"
    role     = "admin"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8001/auth/register" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

## 7. Login And Save The Token

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=ChangeMe123!"
```

Export the returned `access_token`:

```bash
export TOKEN="paste-token-here"
```

PowerShell:

```powershell
$env:TOKEN="paste-token-here"
```

## 8. Verify The Service

Public health:

```bash
curl http://localhost:8001/health
curl http://localhost:8001/health/ready
```

Authenticated identity check:

```bash
curl http://localhost:8001/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

## 9. Upload Test Cases

### Synchronous

```bash
curl -X POST "http://localhost:8001/api/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

### Background

```bash
curl -X POST "http://localhost:8001/api/upload?background=true" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

Check the job:

```bash
curl http://localhost:8001/api/upload/jobs/<job_id> \
  -H "Authorization: Bearer $TOKEN"
```

## 10. Search

```bash
curl -X POST http://localhost:8001/api/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "invalid login with wrong password",
    "feature": "Authentication",
    "ranking_variant": "A"
  }'
```

## 11. Fetch A Script

```bash
curl http://localhost:8001/api/scripts/<script_id> \
  -H "Authorization: Bearer $TOKEN"
```

## 12. Inspect Operations

Admin metrics:

```bash
curl http://localhost:8001/metrics/json \
  -H "Authorization: Bearer $TOKEN"
```

Admin stats:

```bash
curl http://localhost:8001/api/stats \
  -H "Authorization: Bearer $TOKEN"
```

## Common Startup Issues

### Invalid startup configuration

If the app exits immediately, check:

- `MONGO_CONNECTION_STRING`
- `JWT_SECRET_KEY`
- `CORS_ALLOWED_ORIGINS`
- one and only one `LLM_USE_*` flag
- one and only one `EMBEDDING_USE_*` flag
- `REDIS_URL` when `CACHE_BACKEND=redis`

### Ready check fails

Look at:

- `/health/ready`
- `/health/deep`
- server logs for cache, database, or embedding startup failures

## Next Documents

- [README.md](README.md)
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- [API_EXAMPLES.md](API_EXAMPLES.md)
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md)
