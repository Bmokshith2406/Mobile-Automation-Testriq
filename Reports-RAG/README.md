# Reports RAG

> **Created by:** Mokshith Balidi  
> **Created in:** January 2026  
> **Organization:** TW.2324  
> **Rights:** Mokshith Balidi holds all rights to this microservice.

---

FastAPI microservice for uploading and downloading HTML reports backed by MongoDB GridFS.

## What Changed

- Fixed startup and import-time failures across config, logging, middleware, health, auth, and data access.
- Preserved the existing public FastAPI routes:
  - `POST /v1/api/reports/upload`
  - `GET /v1/api/reports/download/{report_id}`
  - `GET /health*`
  - `GET /metrics*`
- Removed any role-based authorization behavior. Authentication is JWT-only when `AUTH_REQUIRED=true`.
- Moved report content storage to GridFS so large HTML payloads do not hit MongoDB's 16 MB document limit.
- Added structured request tracing, rate limiting, readiness checks, Prometheus metrics, and regression tests.

## Project Structure

```text
reports-rag/
├── app/
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── health.py
│   │   ├── logging.py
│   │   ├── metrics.py
│   │   ├── rate_limit.py
│   │   ├── security.py
│   │   └── validation.py
│   ├── db/
│   │   └── mongo.py
│   ├── middleware/
│   │   └── context.py
│   ├── models/
│   │   └── schemas.py
│   ├── routes/
│   │   └── report.py
│   ├── services/
│   │   └── report_service.py
│   └── main.py
├── tests/
│   ├── test_api.py
│   └── test_validation.py
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Runtime Requirements

```bash
pip install -r requirements.txt
```

For tests:

```bash
pip install -r requirements-dev.txt
```

## Configuration

Copy `.env.example` to `.env` and set at least:

- `MONGODB_URI`
- `JWT_SECRET_KEY`
- `AUTH_REQUIRED`
- `CORS_ORIGINS`

Important behavior:

- If `AUTH_REQUIRED=true`, `JWT_SECRET_KEY` must be set and must not be the placeholder.
- If `MONGO_ENABLED=false`, the service still boots for smoke tests, but report storage endpoints will not work against Mongo.
- No RBAC or role claims are enforced anywhere in the service.

### Security Context: Trusted Proxy (`TRUST_FORWARDED_IP`)

#### Why this approach is used
In production environments, services are often deployed behind load balancers, reverse proxies (like Nginx, HAProxy), or API gateways. By default, these proxies forward the original client's IP in headers such as `X-Forwarded-For` or `X-Real-IP`.

If a microservice blindly trusts these headers without verification, a malicious client can bypass the gateway and send spoofed headers directly to the service. For example, by sending a custom header like `X-Forwarded-For: 8.8.8.8` on every request, an attacker could spoof their IP, bypass rate limiters, or falsify security audit logs.

To prevent IP spoofing, we follow a defense-in-depth approach:
- By default, `TRUST_FORWARDED_IP` is set to `false`, meaning the microservice ignores forwarded headers and resolves the client IP to the direct socket IP (`request.client.host`).
- It should only be set to `true` when the service is safely sandboxed behind a trusted reverse proxy that is explicitly configured to sanitize, preserve, or overwrite client IP headers.

## Run

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### Health

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/deep`

`/health/ready` and `/health/deep` return HTTP `503` when MongoDB is enabled but unavailable.

### Upload Report

```http
POST /v1/api/reports/upload
Authorization: Bearer <jwt>
Content-Type: multipart/form-data
```

Form fields:

- `name`
- `file`

Success response:

```json
{
  "status": "success",
  "message": "Report uploaded successfully",
  "report_id": "507f1f77bcf86cd799439011",
  "name": "Quarterly Report",
  "created_at": "2026-06-03T00:00:00Z"
}
```

### Download Report

```http
GET /v1/api/reports/download/{report_id}
Authorization: Bearer <jwt>
```

Returns the HTML file body as `text/html` with `Content-Disposition: attachment`.

## Storage Model

Report HTML is stored in MongoDB GridFS:

- Bucket: `reports` by default
- Metadata is stored in the GridFS `files` collection
- Content is stored in GridFS `chunks`

Stored metadata includes:

- `name`
- `created_at`
- `updated_at`
- `content_type`
- `size`

## Observability

- Structured request logging with `X-Request-ID`, `X-Correlation-ID`, and `X-Trace-ID`
- Prometheus metrics at `/metrics`
- JSON metrics snapshot at `/metrics/json`
- In-memory rate limiting with configurable window and limit

## Tests

```bash
pytest
```