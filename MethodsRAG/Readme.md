# Intelligent Playwright Python Methods Search Platform – Modular Edition

> **Created by:** Mokshith Balidi  
> **Created in:** January 2026  
> **Organization:** TW.2324  
> **Rights:** Mokshith Balidi holds all rights to this microservice.

---

## Overview

This project is a production-grade backend platform for uploading, enriching, indexing, and semantically searching **Python Playwright automation methods** using:

- FastAPI for APIs  
- MongoDB Atlas for persistence and vector search  
- SentenceTransformers (`all-MiniLM-L6-v2`) for embeddings  
- Google Gemini for MADL enrichment, query expansion, and reranking  
- JWT or API-key authentication (stateless, no RBAC)  
- Advanced ranking heuristics with A/B experimentation  
- Search caching  
- Audit logging and metrics  

This refactor modularizes the original monolithic application into clean service layers for easier debugging, scaling, and experimentation.

---

## Project Structure

```

app/
├── main.py                # App startup and lifespan orchestration
│
├── core/                  # Global configuration and security
│   ├── config.py          # Environment config and constants
│   ├── logging.py         # Structured logging
│   ├── cache.py           # In-memory query caching
│   ├── security.py        # JWT verification
│   └── analytics.py      # Audit logging
│
├── db/
│   └── mongo.py           # MongoDB connection + helpers
│
├── models/
│   ├── schemas.py         # Pydantic DTO schemas
│   └── users.py           # Mongo user CRUD helpers
│
├── services/
│   ├── embeddings.py     # SentenceTransformer lifecycle + vector utilities
│   ├── keywords.py       # Keyword extraction & fallback summaries
│   ├── expansion.py      # Gemini query normalization & expansion
│   ├── rerank.py         # Gemini reranking
│   ├── ranking.py        # Multi-signal candidate scoring + A/B logic
│   ├── method_madl.py    # Playwright method-to-MADL enrichment
│   ├── dedupe_summary.py # Gemini dedupe-summary generator
│   └── dedupe_verifier.py# Duplicate detection logic
│
├── routes/
│
│   ├── upload.py          # CSV/XLSX ingestion + MADL + embeddings
│   ├── search.py          # Hybrid vector + heuristic ranking APIs
│   ├── update.py          # Method updates + reprocessing
│   └── admin.py           # Admin maintenance + metrics APIs
│
└── middleware/            # Optional global middleware (future use)

````

---

## Setup & Installation

### 1. Python Version

Python 3.10+

---

### 2. Clone & Setup Virtual Environment

```bash
git clone <your-repository>
cd <your-repository>

python -m venv .venv
source .venv/bin/activate    # macOS/Linux
.venv\Scripts\activate       # Windows
````

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Required Packages

Your `requirements.txt` should include:

```
fastapi
uvicorn
motor
pymongo
sentence-transformers
numpy
pandas
python-dotenv
python-jose
passlib[bcrypt]==1.7.4
bcrypt==3.2.2
openpyxl
google-generativeai
python-multipart
```

---

## Environment Variables

Create a `.env` file:

```
GOOGLE_API_KEY=your-google-api-key
MONGO_CONNECTION_STRING=your-mongodb-uri
JWT_SECRET_KEY=your-secret-jwt-key
TRUST_FORWARDED_IP=false
```

### Security Context: Trusted Proxy (`TRUST_FORWARDED_IP`)

#### Why this approach is used
In production environments, services are often deployed behind load balancers, reverse proxies (like Nginx, HAProxy), or API gateways. By default, these proxies forward the original client's IP in headers such as `X-Forwarded-For` or `X-Real-IP`.

If a microservice blindly trusts these headers without verification, a malicious client can bypass the gateway and send spoofed headers directly to the service. For example, by sending a custom header like `X-Forwarded-For: 8.8.8.8` on every request, an attacker could spoof their IP, bypass rate limiters, or falsify security audit logs.

To prevent IP spoofing, we follow a defense-in-depth approach:
- By default, `TRUST_FORWARDED_IP` is set to `false`, meaning the microservice ignores forwarded headers and resolves the client IP to the direct socket IP (`request.client.host`).
- It should only be set to `true` when the service is safely sandboxed behind a trusted reverse proxy that is explicitly configured to sanitize, preserve, or overwrite client IP headers.

---

## MongoDB Requirements

Create a **Vector Search Index** on the `main_vector` field:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "main_vector",
      "numDimensions": 384,
      "similarity": "cosine",
      "quantization": "none"
    }
  ]
}
```

Index name must be:

```
vector_index
```

---

## Running the App

Start the backend:

```bash
uvicorn app.main:app --reload
```

API Endpoint:

```
http://localhost:8000
```

Swagger Docs:

```
http://localhost:8000/docs
```

---

## Authentication

The service uses simple authenticated access only. Every protected route accepts either:

```
Authorization: Bearer YOUR_TOKEN
```

or

```
X-API-Key: YOUR_API_KEY
```

## Uploading Playwright Python Methods

```
POST /api/upload-methods
```

Authentication required: Valid JWT Token

Accepted file formats:

* `.csv`
* `.xlsx`

Required column:

```
Raw Method
```

Each row must contain a valid **Python Playwright method** source block.

### Processing Flow

1. Duplicate detection via Gemini (summary + vector similarity)
2. MADL generation using Gemini
3. SentenceTransformer embedding
4. Multi-vector creation and indexing
5. MongoDB insertion

---

## Searching Methods

```
POST /api/search
```

```json
{
  "query": "click login button",
  "ranking_variant": "B"
}
```

---

## Search Pipeline

```
User Query
   ↓
Sentence Embedding
   ↓
MongoDB $vectorSearch
   ↓
Local multi-signal ranker
   ↓
(Gemini reranking optional)
   ↓
Final TOP-K results
```

---

## Ranking Signals

### Variant A – Baseline

```
0.60 * Vector similarity
0.25 * Semantic cosine similarity
+ Token match boosts
```

---

### Variant B – Enhanced

```
0.45 * Vector similarity
0.20 * Semantic similarity
0.12 * Keyword overlap
0.05 * Token density
0.05 * Popularity weighting
```

Set via:

```
"ranking_variant": "A" | "B"
```

---

## Updating Methods

```
PUT /api/update/{doc_id}
```

Partial MADL updates supported:

```json
{
  "summary": "New description of method",
  "keywords": ["click", "login", "wait"]
}
```

Automatically triggers:

* Vector regeneration
* MADL re-indexing
* Main-vector recomputation

---

## Admin APIs

### Fetch All Methods

```
GET /api/get-all-methods
```

---

### Delete All Methods

```
POST /api/delete-all?confirm=true
```

Authenticated access required.

---

### Delete Single Method

```
DELETE /api/method/{id}
```

---

### Metrics

```
GET /api/metrics
```

Response:

```json
{
  "queries_today": 281,
  "top_methods": ["login_user()", "click_submit()"]
}
```

---

## Audit Logging

Every search request logs:

* Timestamp
* Endpoint
* User
* Request payload
* Ranking variant
* Result count

Stored in:

```
api_audit_logs
```

### Why Audit Logging Matters

* Query trend analysis
* Ranking quality evaluation
* Popular automation workflow discovery
* Search relevance tuning

---

## Development Workflow

### Ranking Logic

```
app/services/ranking.py
```

---

### LLM Strategies

```
app/services/expansion.py
app/services/rerank.py
```

---

### Schema & DTO Updates

```
app/models/schemas.py
```

---

### Route Wiring Only

```
app/routes/
```

