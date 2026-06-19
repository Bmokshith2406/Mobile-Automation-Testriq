# Playwright Python Method Extractor (AST-Only, Production-Grade)

> **Created by:** Mokshith Balidi  
> **Created in:** January 2026  
> **Organization:** TW.2324  
> **Rights:** Mokshith Balidi holds all rights to this microservice.

---

A fast, deterministic, LLM-free **Playwright Python method extraction service** built using Python AST parsing.

Optimized for:
- Playwright Python automation scripts  
- Large enterprise Python codebases  
- Byte-perfect extraction (no code modification)  
- Static analysis, test intelligence, and test-case workflows  
- High-volume API processing with MongoDB logging  

The system extracts top-level functions, class methods, and nested methods, injects required execution context (global variables and constructor-initialized attributes), and returns a **single-column CSV** where each row contains one complete method block.

---

## Features

### 1. AST-Based Extraction (No LLMs)
- Byte-perfect slicing from the original source  
- No decorators included  
- Preserves indentation, spacing, and code style  
- Supports `def` and `async def`  
- Supports nested functions  

### 2. Context Injection (Playwright-Oriented)

The extractor injects:
- **Top-level global assignments** (constants, fixtures, selectors)
- **Constructor (`__init__`) assignments** for class-based methods

Example constructor:

```python
def __init__(self, page):
    self.page = page
    self.base_url = "https://example.com"
````

Injected above each class method:

```python
self.page = page
self.base_url = "https://example.com"

def open(self):
    self.page.goto(self.base_url)
```

Rules:

* Only assignments inside `__init__` are injected
* Injection preserves original formatting
* Injection is deterministic and AST-driven
* No reference-based guessing or mutation

This design is well-suited for **Playwright Page Object Models**.

---

### 3. Chunking System

Splits extracted output into safe chunks (default: **20,000 characters per chunk**) while **never splitting a method**.

This enables:

* Safe downstream LLM usage
* Embedding pipelines
* Parallel processing

---

### 4. CSV Output

Produces a single-column CSV with header:

```
Raw Method
```

Each row contains:

* Injected context (if any)
* Full method source code
* Original formatting preserved

Excel/CSV injection is safely mitigated.

---

### 5. REST API (FastAPI)

Endpoints:

```
GET  /health
POST /extract
```

Supports:

* File upload
* Raw code paste
* Streaming CSV downloads

---

### 6. MongoDB Logging

Stores:

* API audit logs
* Raw uploaded Playwright Python scripts

Logging is **best-effort** and never blocks extraction.

---

### 7. Production-Grade Architecture

Includes:

* Middleware-based auditing
* Strict validation layer
* Structured logging
* Environment-based configuration
* Async MongoDB (Motor)
* Docker-ready deployment

---

## Architecture Overview

```
app/
│
├── core/
│   ├── config.py          # Settings loader
│   ├── logging.py         # Global logging config
│   └── utils.py           # Safe decoding, timing helpers
│
├── db/
│   └── mongo.py           # Async MongoDB client + storage functions
│
├── middleware/
│   └── audit.py           # API call logging middleware
│
├── models/
│   └── schemas.py         # Pydantic APILog and RawScript schemas
│
├── routes/
│   ├── extract.py         # Playwright method extraction API
│   └── health.py          # Health check
│
├── services/
│   ├── scanner.py         # AST-based extractor (core logic)
│   ├── chunker.py         # Chunk splitting system
│   ├── csv_writer.py      # CSV builder with injection safety
│   └── validator.py       # Validation layer
│
└── main.py                # FastAPI application entry point
```

---

## AST Extraction Rules

### Extracted

* Top-level functions
* Class methods (excluding `__init__`)
* Nested functions
* Sync and async functions

### Ordering

* Preserved exactly as in the source file

### Byte-Perfect Guarantee

* Extraction begins exactly at `def` or `async def`
* No decorators included
* No formatting changes
* No normalization or rewriting

### Not Extracted

* Constructors (`__init__`)
* Decorators
* Comments outside method bodies

---

## Injection Logic (Context Preservation)

Injected before each extracted method:

1. Global variable assignments
2. `self.<attr> = ...` assignments from `__init__`

Characteristics:

* No runtime evaluation
* No dependency inference
* No code mutation
* Exact source-line injection

This ensures extracted methods remain **standalone and analyzable**.

---

## Project File Structure

```
.
├── app/
│   ├── core/
│   ├── db/
│   ├── middleware/
│   ├── models/
│   ├── routes/
│   ├── services/
│   └── main.py
├── requirements.txt
├── .env
└── README.md
```

---

## Installation

Clone the repository:

```bash
cd playwright-python-method-extractor
```

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Environment Variables (.env Example)

```
MONGO_URI=mongodb://localhost:27017
MONGO_DB=playwright_python_method_extractor
LOG_LEVEL=INFO
MAX_CHARS_PER_CHUNK=20000
VERSION=1.0.0
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

## Running the Application

Start FastAPI with Uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open API documentation:

```
http://localhost:8000/docs
```

---

## API Documentation

### GET /health

Returns service status.

Response:

```json
{
  "status": "ok"
}
```

---

### POST /extract

#### Option 1: Upload a File

```
multipart/form-data
file: test_login.py
```

#### Option 2: Paste Code

```
script="async def test_login(page): ..."
```

#### Response

A downloadable CSV file containing extracted Playwright Python methods.

---

## MongoDB Storage

### Raw Scripts Collection (`raw_scripts`)

```json
{
  "filename": "login.py",
  "content": "...",
  "size": 3240,
  "timestamp": "2025-01-10T12:30:00Z"
}
```

### API Logs Collection (`api_logs`)

```json
{
  "timestamp": "2025-01-10T12:30:01Z",
  "ip": "127.0.0.1",
  "user_agent": "...",
  "file_name": "login.py",
  "method_count": 12,
  "chunk_count": 1,
  "status": 200,
  "duration_ms": 15.2
}
```

---

## Logging

All logs follow a structured format:

```
2025-01-10 11:00:00 | INFO | playwright_python_method_extractor | Extracted 12 methods
```

---

## Validation Rules

Validation ensures:

* Code begins with `def` or `async def`
* Decorators are excluded
* Methods are ordered by source line
* Injected context consists only of strings

On failure, a `ValidationError` is raised internally.

---

## Troubleshooting

### Method does not start with def or async def

Decorators exist in the source. Decorators are intentionally excluded from extraction.

### No methods extracted

Possible causes:

* Syntax errors in source code
* File contains only `__init__`
* Encoding issues

### CSV issues in Excel

Excel may interpret rows as formulas. The CSV writer safely escapes dangerous prefixes.

---

## FAQ

### Why AST instead of an LLM?

AST parsing is deterministic, reproducible, safe, and scalable for large Playwright codebases.

### Does it support async Playwright tests?

Yes. `async def` is fully supported.

### Does it modify source code?

No. Extraction is byte-perfect.

### Is method order preserved?

Yes. Guaranteed.
