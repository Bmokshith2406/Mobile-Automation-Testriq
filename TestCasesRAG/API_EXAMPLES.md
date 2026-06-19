# API Examples

All protected examples below assume you already logged in and exported:

```bash
export TOKEN="paste-your-jwt-here"
```

## Provider Configuration Examples

Gemini:

```env
LLM_USE_GEMINI=true
LLM_USE_OPENAI=false
LLM_USE_ANTHROPIC=false
LLM_USE_LOCAL=false
GOOGLE_API_KEY=your-gemini-key
```

OpenAI:

```env
LLM_USE_GEMINI=false
LLM_USE_OPENAI=true
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-4o-mini
```

Anthropic:

```env
LLM_USE_GEMINI=false
LLM_USE_ANTHROPIC=true
ANTHROPIC_API_KEY=your-anthropic-key
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

Local API:

```env
LLM_USE_GEMINI=false
LLM_USE_LOCAL=true
LOCAL_LLM_API_URL=http://localhost:11434/v1/chat/completions
LOCAL_LLM_API_FORMAT=openai
LOCAL_LLM_MODEL=llama3.1
```

Embedding presets:

```env
EMBEDDING_USE_MINILM_384=true
EMBEDDING_USE_MPNET_768=false
EMBEDDING_USE_BGE_LARGE_1024=false
```

## 1. Bootstrap And Login

### Register First Admin

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "ChangeMe123!",
    "role": "admin"
  }'
```

### Login

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=ChangeMe123!"
```

### Inspect Current User

```bash
curl http://localhost:8001/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

## 2. Synchronous Upload

```bash
curl -X POST http://localhost:8001/api/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

Example response:

```json
{
  "success": true,
  "mode": "sync",
  "testcases_inserted": 12,
  "scripts_inserted": 12,
  "duplicates_skipped": 1,
  "total_groups": 13
}
```

## 3. Background Upload

```bash
curl -X POST "http://localhost:8001/api/upload?background=true" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@Sample.xlsx"
```

Example response:

```json
{
  "success": true,
  "mode": "background",
  "job_id": "4b7786d8-9d7f-41c7-bf0e-2a6553a20c26",
  "status": "queued",
  "filename": "Sample.xlsx",
  "created_at": "2026-04-24T09:10:00+00:00",
  "status_endpoint": "/api/upload/jobs/4b7786d8-9d7f-41c7-bf0e-2a6553a20c26"
}
```

### Check Background Job Status

```bash
curl http://localhost:8001/api/upload/jobs/4b7786d8-9d7f-41c7-bf0e-2a6553a20c26 \
  -H "Authorization: Bearer $TOKEN"
```

### List Recent Upload Jobs

```bash
curl "http://localhost:8001/api/upload/jobs?limit=10&status=completed" \
  -H "Authorization: Bearer $TOKEN"
```

## 4. Search

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

Example response:

```json
{
  "query": "invalid login with wrong password",
  "feature_filter": "Authentication",
  "results_count": 2,
  "results": [
    {
      "id": "testcase-doc-id",
      "probability": 93.4,
      "test_case_id": "TC-001",
      "feature": "Authentication",
      "description": "Verify login fails with invalid credentials",
      "prerequisites": "User exists",
      "steps": "Step 1: Open login page",
      "summary": "Checks authentication failure path",
      "keywords": [
        "login",
        "invalid password"
      ],
      "tags": [],
      "priority": null,
      "platform": null,
      "playwright_script_id": "script-doc-id"
    }
  ],
  "from_cache": false,
  "ranking_variant": "A"
}
```

## 5. Fetch Scripts

### Single Script

```bash
curl http://localhost:8001/api/scripts/script-doc-id \
  -H "Authorization: Bearer $TOKEN"
```

### Batch Script Fetch

Note: the request body is a raw JSON array, not an object.

```bash
curl -X POST http://localhost:8001/api/scripts/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[
    "script-doc-id-1",
    "script-doc-id-2"
  ]'
```

## 6. Update A Test Case

```bash
curl -X PUT http://localhost:8001/api/update/testcase-doc-id \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "feature": "Authentication",
    "priority": "High",
    "platform": "Web",
    "tags": ["smoke", "regression"]
  }'
```

## 7. Read Admin Data

### List Test Cases

```bash
curl "http://localhost:8001/api/get-all?skip=0&limit=20&sort_by=Feature&order=1" \
  -H "Authorization: Bearer $TOKEN"
```

### List Test Cases With Linked Scripts

```bash
curl "http://localhost:8001/api/get-all-scripts?skip=0&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### Stats

```bash
curl http://localhost:8001/api/stats \
  -H "Authorization: Bearer $TOKEN"
```

## 8. Destructive Admin Operations

### Delete One Test Case

```bash
curl -X DELETE http://localhost:8001/api/delete/testcase-doc-id \
  -H "Authorization: Bearer $TOKEN"
```

### Delete All

```bash
curl -X POST "http://localhost:8001/api/delete-all?confirm=true" \
  -H "Authorization: Bearer $TOKEN"
```

## 9. Health And Metrics

### Public Health

```bash
curl http://localhost:8001/health
curl http://localhost:8001/health/live
curl http://localhost:8001/health/ready
curl http://localhost:8001/health/deep
```

### Admin Metrics

```bash
curl http://localhost:8001/metrics \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl http://localhost:8001/metrics/json \
  -H "Authorization: Bearer $TOKEN"
```

`/health/ready` and `/health/deep` now include the selected LLM backend and embedding model details.

## 10. Python Client Example

```python
import requests


class TestCasesRAGClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
        })

    def me(self):
        return self.session.get(f"{self.base_url}/auth/me").json()

    def search(self, query: str, feature: str | None = None):
        payload = {"query": query, "ranking_variant": "A"}
        if feature:
            payload["feature"] = feature
        response = self.session.post(
            f"{self.base_url}/api/search",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def queue_upload(self, file_path: str):
        with open(file_path, "rb") as handle:
            response = self.session.post(
                f"{self.base_url}/api/upload?background=true",
                files={"file": (file_path, handle)},
            )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str):
        response = self.session.get(
            f"{self.base_url}/api/upload/jobs/{job_id}",
        )
        response.raise_for_status()
        return response.json()


client = TestCasesRAGClient("http://localhost:8001", token="your-jwt")
print(client.me())
job = client.queue_upload("Sample.xlsx")
print(job)
print(client.get_job(job["job_id"]))
print(client.search("invalid login", feature="Authentication"))
```
