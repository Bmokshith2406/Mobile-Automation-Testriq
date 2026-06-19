# Deployment Notes

This service is designed to run behind a reverse proxy or managed platform such as Google Cloud Run, ECS, or Kubernetes.

## Production Checklist

- Set `ENVIRONMENT=prod`
- Set `DEBUG=false`
- Provide a real `API_KEY`
- Configure `LLM_PROVIDER` and the matching API key
- Decide whether rate limiting is `memory` or `redis`
- Keep `.env` out of container builds and source control
- Expose `/health/live` and `/health/ready` to the platform health checks

## Recommended `.env.cloud`

Use the committed `.env.cloud` as a starting point. Important values:

```env
ENVIRONMENT=prod
DEBUG=false
PORT=8080
WORKERS=1
AI_ENABLED=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_BACKEND=memory
MAX_ZIP_SIZE_MB=500
MAX_DECOMPRESSED_SIZE_MB=1024
API_KEY_ENABLED=true
```

If you need shared rate limiting across instances:

```env
RATE_LIMIT_BACKEND=redis
REDIS_URL=redis://...
```

## Build

```bash
docker build -t artifact-report-generator:latest .
```

## Run

```bash
docker run -d \
  -p 8000:8000 \
  --env-file .env.cloud \
  --name artifact-report-generator \
  artifact-report-generator:latest
```

## Health Checks

- Liveness: `/health/live`
- Readiness: `/health/ready`

`/health/ready` returns `503` if the container cannot write to its temp filesystem.

## Cloud Run Example

```bash
gcloud run deploy artifact-report-generator \
  --image asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/artifact-repo/artifact-report-generator:latest \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10 \
  --env-vars-file .env.cloud
```

## Notes

- The Docker image is multi-stage and only includes the runtime `app/` code.
- `.dockerignore` excludes `.env`, tests, samples, and local virtual environments from the build context.
- If AI provider initialization fails, the service falls back to a no-op AI provider and still generates reports.
