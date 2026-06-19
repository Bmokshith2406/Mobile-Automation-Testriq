# Multi-Framework Test Executor + Self-Healing Step Repair Engine

> **Created by:** Mokshith Balidi  
> **Created in:** January 2026  
> **Organization:** TW.2324  
> **Rights:** Mokshith Balidi holds all rights to this microservice.

---

A production-grade, AI-driven self-healing automation microservice designed to intercept test failures (Playwright, Selenium, Appium, Cypress), diagnose locator and interruption issues using Google Gemini, validate proposed code changes with strict AST inspection, and automatically patch test scripts on disk through explicit framework-specific execution routes.

## Current API Surface

The live FastAPI exports are:

- `POST /repair` — Repair a single failing test automation step (Playwright, Selenium, Appium, Cypress)
- `POST /executor/playwright/run` — Execute a Playwright Python script with full self-healing loop
- `POST /executor/selenium/run` — Execute a Selenium Python script with full self-healing loop
- `POST /executor/cypress/run` — Execute a Cypress-oriented Python script with full self-healing loop
- `POST /executor/appium/run` — Execute an Appium Python script with Appium runtime parameters
- `GET /executor/stats` — Execution statistics from MongoDB
- `GET /health`, `GET /health/live`, `GET /health/ready`, `GET /health/startup`, `GET /health/deep`
- `GET /metrics` — Prometheus metrics scrape endpoint
- `GET /info`, `GET /` — App metadata and feature flags

`app/api/v1/*` still exists only as a compatibility layer that re-exports the live routers in `app/routes/*`.

## Operational Defaults

The service ships with production-safe defaults:

- API-key authentication is **enabled** by default.
- Executor sandbox validation is **enabled** by default.
- Production execution **requires Docker sandboxing** unless you set an explicit override.
- Generated Appium Python scripts are supported through `/executor/appium/run`, but an Appium server must be running separately at `APPIUM_SERVER_URL` before real mobile execution.
- Repair screenshots can be provided as PNG, JPEG, or WebP.
- MongoDB fallback to in-memory storage is **allowed in development**, but no longer happens silently in production.
- `run.py` binds to `127.0.0.1` by default to avoid Windows Firewall prompts; use `--host 0.0.0.0` to expose to a network.

---

## 📖 Table of Contents
1. [Current API Surface](#current-api-surface)
2. [Operational Defaults](#operational-defaults)
3. [Core Philosophy (Why, What, & How)](#-core-philosophy-why-what--how)
4. [E2E Self-Healing Failure Lifecycle](#-e2e-self-healing-failure-lifecycle)
5. [Architecture and High-Level Design](#-architecture-and-high-level-design)
6. [Deep Dive: AST-Based Security Sandbox](#-deep-dive-ast-based-security-sandbox)
7. [Deep Dive: DOM Pruner & AST Tag-Tree Parsing](#-deep-dive-dom-pruner--ast-tag-tree-parsing)
8. [Executor Output Contract](#-executor-output-contract)
9. [Data Repository Models & Index Specification](#-data-repository-models--index-specification)
10. [Action Extractors & Prompt Engineering Specs](#-action-extractors--prompt-engineering-specs)
11. [Observability, Health Checks, & Prometheus Metrics](#-observability-health-checks--prometheus-metrics)
12. [Detailed File Map & Directory Index](#-detailed-file-map--directory-index)
13. [Configuration & Environment Variables](#-configuration--environment-variables)
14. [Setup, Running, and Deployment CLI Commands](#-setup-running-and-deployment-cli-commands)
15. [Developer Guide: Extending and Adding New Action Extractors](#-developer-guide-extending-and-adding-new-action-extractors)
16. [Troubleshooting & Support Matrix](#-troubleshooting--support-matrix)

---

## 🎯 Core Philosophy (Why, What, & How)

### Why it Exists
End-to-End (E2E) UI tests are notoriously high-maintenance. Minor frontend variations—such as changing a button's casing, altering a placeholder, or switching an identifier class name—can break strict locators, halting CI/CD release cycles.

Traditional recovery involves analyzing stack traces, reading raw HTML dumps, rewriting locators, and redeploying. The **Multi-Framework Self-Healing Step Repair Engine** automates this workflow directly at the test runtime level.

### What it Does
On failure, instead of immediately crashing the pipeline, the test runner routes failure context to this engine, which dynamically analyzes the DOM snapshot, classifies the failing instruction, requests an optimal repair candidate from Google Gemini, validates the repair in a restricted sandbox, patches the source script on the disk, and resumes execution.

### How it Works
```mermaid
graph TD
    A[Automation Step Fails] --> B[Capture HTML DOM + Error + screenshot]
    B --> C[Call /repair Endpoint]
    C --> D[Classify failing step style]
    D --> E[Prune raw HTML into compact AST tag-tree]
    E --> F[Consult Google Gemini LLM]
    F --> G[Run semantic normalization checks]
    G --> H[Validate code proposed in AST sandbox]
    H -- Success --> I[Backup & patch code file on disk]
    H -- Failure --> J[Attempt model-fallback / Abort]
    I --> K[Resume Execution from next instruction]
```

---

## 🔄 E2E Self-Healing Failure Lifecycle

The engine coordinates step resolution through ten structured phases:

1. **Failure Interception**: A custom test-runner hook traps standard errors (e.g. Playwright's `TimeoutError` or Selenium's `NoSuchElementException`).
2. **Context Serialization**: The runner serializes the failing file path, failing line number, natural language intent, stack trace, page screenshot (PNG, JPEG, or WebP), and HTML DOM snapshot.
3. **Trigger Ingestion**: The payload hits `/repair` directly, or can be queued asynchronously when the optional Celery worker stack is installed.
4. **Action Classification**: The engine determines the action category (e.g. `Click`, `Type`, `Select`, `Assert`, or JavaScript `Dialog` intercept).
5. **DOM Compression**: The raw DOM HTML is compressed into an indented AST tag-tree containing only interactive elements and nodes matching keywords.
6. **LLM Hint Synthesis**: The LLM analyzes the failure context to identify target elements, returning precise semantic strings (e.g. `click:text("Submit")`).
7. **Intermediate Representation**: The engine builds a Canonical Intermediate Representation (CIR) block containing locator strategies and payload structures.
8. **Sandbox Auditing & Verification**: The proposal is compiled into code, validated with strict AST and pattern checks, and then executed in the configured sandbox path.
9. **Real-time Disk Patching**: Upon validation, the script patcher updates the locator code **and** the matching `step_code` string literal inside `_guarded_step(...)` calls inside the original test script.
10. **Execution Resumption**: The test runner restarts execution, picking up from the patched instruction.

---

## 🏛️ Architecture and High-Level Design

The service is built around modular, decoupled components to limit code clutter:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Router Gateway                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Repair Service Orchestrator                     │
└───────┬───────────────────────────┬────────────────────────┬───────────┘
        │                           │                        │
        ▼                           ▼                        ▼
┌───────────────┐           ┌───────────────┐        ┌───────────────┐
│  CIR Builder  │           │  DOM Pruner   │        │   Extractor   │
│               │           │               │        │    Factory    │
└───────┬───────┘           └───────┬───────┘        └───────┬───────┘
        │                           │                        │
        └───────────────────────────┼────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   Gemini LLM Engine   │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │  Jailed AST Sandbox   │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │    Atomic Patcher     │
                        └───────────────────────┘
```

* **Gateway (FastAPI)**: Manages API-key authentication, rate limiting, structured logging, and the unchanged public route surface.
* **Orchestrator**: Coordinates execution, manages self-healing state, records repair metadata, and triggers rollbacks on failure.
* **Registry & Factory**: `app/services/extractors/ExtractorFactory.py` maps action types to specialized extractors.
* **AST Sandbox**: Rejects dangerous imports and host-operation primitives before execution and can delegate execution to Docker in production.
* **Patcher**: Automatically modifies code on disk while keeping backups for rollback. Patches both the `async def _step_X` function body **and** the string literal passed to `_guarded_step(...)`.

---

## 🔒 Deep Dive: AST-Based Security Sandbox

Running dynamically generated code poses security risks. Simple regex checks (e.g., blocking `import os`) are easily bypassed:
```python
# Bypasses regex keyword scanning
getattr(__builtins__, "__im" + "port__")("o" + "s").system("rm -rf /")
```

`app/executors/sandbox.py` provides protection through two-layer validation:
1. **Abstract Syntax Tree (AST) Visitor**: Parses the script into structured syntax nodes and walks the tree.
2. **Regex Defense-in-depth**: Secondary pattern checks applied after AST analysis.

### 🚫 Forbidden Imports (Blocklist)

These modules are **always blocked**, regardless of strict mode:

| Module | Why Blocked |
|--------|------------|
| `subprocess` | Shell command execution |
| `shutil` | File system manipulation (copy, move, rmtree) |
| `ctypes` | Direct C-level memory/OS access |
| `multiprocessing` | Spawning new processes |
| `signal` | OS signal sending (SIGKILL, etc.) |
| `socket` | Raw network socket access |
| `http.server` | Spawning HTTP servers |
| `ftplib` | FTP client access |
| `smtplib` | Email sending |
| `telnetlib` | Telnet access |
| `pickle` | Arbitrary object deserialization |
| `marshal` | Arbitrary bytecode deserialization |
| `shelve` | Persistent object stores via pickle |
| `code` | Interactive code interpreter embedding |
| `codeop` | Incremental code compilation |
| `pty` | Pseudo-terminal control |
| `tty` | Terminal control |
| `fcntl` | File control / UNIX FD operations |
| `resource` | UNIX resource limit control |
| `sysconfig` | Python build configuration access |
| `gc` | Garbage collector control (object finalization abuse) |
| `importlib` | Dynamic module loading |

### ✅ Allowed Imports (Allowlist — Strict Mode)

When `strict_mode=True` (enabled when `ENABLE_SANDBOX_EXECUTION=true`), **only these modules are allowed**:

| Module | Purpose |
|--------|---------|
| `playwright` | Core Playwright API |
| `playwright.sync_api` | Synchronous Playwright |
| `playwright.async_api` | Async Playwright |
| `selenium` | Core Selenium API |
| `appium` | Core Appium API |
| `asyncio` | Async I/O primitives |
| `re` | Regular expressions |
| `base64` | Appium screen recording decode support |
| `json` | JSON serialization |
| `time` | Time utilities |
| `datetime` | Date/time classes |
| `typing` | Type hints |
| `dataclasses` | Data class decorator |
| `enum` | Enumeration classes |
| `functools` | Higher-order functions |
| `itertools` | Iterator tools |
| `collections` | Data containers (defaultdict, etc.) |
| `math` | Math functions |
| `random` | Random number generation |
| `string` | String constants |
| `uuid` | UUID generation |
| `os` | OS path utilities (but `os.system`, `os.popen` etc. are blocked by FORBIDDEN_ATTRS) |
| `pathlib` | Path utilities (but `read_text`, `read_bytes`, `glob`, `rglob`, `iterdir` are blocked) |
| `logging` | Logging |
| `traceback` | Traceback formatting |
| `inspect` | Object introspection and stack frame reflection |
| `sys` | Interpreter variables and controls (e.g. exit, stdout) |
| `hashlib` | Secure cryptographic hashing (SHA256, MD5, etc.) |

### ➕ How to Whitelist a New Library

If your automation scripts need to import a standard or third-party library that is currently blocked in strict mode, follow these steps to whitelist it:

#### Step 1: Check the Blocklist (Forbidden Imports)
First, verify that the module is not listed in `FORBIDDEN_IMPORTS` inside [sandbox.py](file:///D:/Demo-Ready-TW.2324/Executor-Regenrator/app/executors/sandbox.py).
> [!IMPORTANT]
> If a module is on the blocklist (e.g., `subprocess`, `socket`), it is permanently blocked for security. Whitelisting it requires removing it from `FORBIDDEN_IMPORTS`, which is highly discouraged as it compromises sandbox isolation.

#### Step 2: Add to the Allowlist
Open [sandbox.py](file:///D:/Demo-Ready-TW.2324/Executor-Regenrator/app/executors/sandbox.py) and add the base module name as a string to the `ALLOWED_IMPORTS` set:
```python
ALLOWED_IMPORTS: Set[str] = {
    # ...
    "traceback",
    "inspect",
    "sys",
    "hashlib",
    "your_module_name",  # <-- Add your module here
}
```
*(Note: Only specify the base root package name. For example, to import `playwright.async_api`, allowing `playwright` is sufficient unless strict granular checks are required.)*

#### Step 3: Implement Additional Safety Controls (Optional)
If the library contains specific methods that could be abused (e.g., reading/writing files, execution functions), add those method/function names to `FORBIDDEN_ATTRS` or `FORBIDDEN_CALLS` in the same file to block them globally.

#### Step 4: Verify with Unit Tests
Add a test in [test_security.py](file:///D:/Demo-Ready-TW.2324/Executor-Regenrator/tests/test_security.py) (inside `TestSandboxExecution`) to verify your module is allowed:
```python
def test_validator_allows_my_custom_module(self):
    from app.executors.sandbox import ScriptSecurityValidator
    validator = ScriptSecurityValidator(strict_mode=True)
    is_safe, reason = validator.validate("import your_module_name")
    assert is_safe is True
```
Then run the tests:
```bash
python -m pytest tests/test_security.py -v
```

#### Step 5: Restart the Application
Since the sandbox validator is loaded on startup, restart your FastAPI/Uvicorn server for the changes to take effect.

### 🚫 Forbidden Function Calls

These built-in function names are blocked **by name**, regardless of how they are called:

| Call | Why Blocked |
|------|------------|
| `eval` | Arbitrary code execution |
| `exec` | Arbitrary code execution |
| `compile` | Bytecode compilation |
| `__import__` | Dynamic module import |
| `memoryview` | Raw memory buffer access |
| `listdir` | Directory listing |

### 🚫 Forbidden Attribute/Method Calls

These method names are blocked when called on **any object**:

| Method | Why Blocked |
|--------|------------|
| `system`, `popen` | Shell command execution |
| `spawn`, `spawnl`, `spawnle`, `spawnlp`, `spawnlpe`, `spawnv`, `spawnve`, `spawnvp`, `spawnvpe` | Process spawning variants |
| `Popen`, `call`, `check_call`, `check_output` | subprocess-style execution |
| `modules` | sys.modules module cache access (bypass sandbox) |
| `rmtree` | Recursive directory delete |
| `remove`, `unlink` | File deletion |
| `rename` | File renaming/moving |
| `rmdir` | Directory deletion |
| `scandir` | Directory traversal |
| `kill`, `fork`, `forkpty` | Process control |
| `startfile` | Windows shell file launch |
| `execl`, `execle`, `execlp`, `execlpe`, `execv`, `execve`, `execvp`, `execvpe` | Process replacement |
| `read_text`, `read_bytes` | File content reading |
| `glob`, `rglob`, `iterdir` | Directory traversal (pathlib) |
| `resolve`, `absolute` | Absolute path resolution |
| `chmod`, `chown` | File permission changes |

### 🚫 Dangerous Patterns (Regex Layer)

These patterns are caught by the secondary regex scan:

| Pattern | Why Blocked |
|---------|------------|
| `.mro()` | MRO traversal (class hierarchy abuse) |
| `.subclasses()` | Subclass enumeration (privilege escalation) |
| `breakpoint()` | Interactive debugger injection |

### AST Node Security Rules
- **Attribute Access**: Blocks all attributes starting with `__` (e.g. `__dict__`, `__code__`, `__globals__`) or matching any key in the `FORBIDDEN_ATTRS` set above.
- **Dynamic Attribute Resolution**: Blocks `getattr`, `setattr`, or `delattr` calls where the attribute argument is a **dynamic expression** (non-constant). If a string constant is passed, it must not match any blocked name.
- **Import Declarations**: Any `import X` or `from X import Y` where `X` is in `FORBIDDEN_IMPORTS` is rejected. In strict mode, only modules in `ALLOWED_IMPORTS` are accepted.

### 🐳 Docker Environment Variable Whitelist / Forwarding

To enforce isolation while executing tests inside sandboxed containers, environment variables are filtered strictly. Only environment variables matching specific whitelisted keys or prefixes are forwarded to the Docker environment:
- **Whitelisted Keys**: `RUN_ID`, `ARTIFACTS_DIR`
- **Whitelisted Prefixes**:
  - Playwright: `PW_`, `PLAYWRIGHT_`
  - Selenium: `SE_`, `SELENIUM_`
  - Cypress: `CY_`, `CYPRESS_`
  - Appium: `APPIUM_`
  - WebDriver: `WD_`, `WEBDRIVER_`

Any sensitive environment variables (such as database credentials or API keys) are automatically stripped to maintain strict sandbox integrity.

### Code Block Examples: Blocked vs. Allowed
#### Blocked (Dynamic Bypass)
```python
# AST Visitor detects getattr call with dynamic (non-constant) second argument
f_name = "sys" + "tem"
getattr(os, f_name)("ls")   # BLOCKED
```

#### Blocked (Internal Attribute Mapping)
```python
# AST Visitor detects __subclasses__ call in Attribute access
object.__subclasses__()   # BLOCKED
```

#### Blocked (Forbidden Import)
```python
import subprocess   # BLOCKED
from shutil import rmtree   # BLOCKED
```

#### Allowed (Standard Playwright)
```python
from playwright.async_api import async_playwright, expect
import asyncio
import json
import re

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://example.com")
        await expect(page.locator("h1")).to_be_visible()
```

---

## 🌲 Deep Dive: DOM Pruner & AST Tag-Tree Parsing

To prevent prompt bloat and keep token sizes compact for low-latency LLMs, `app/core/dom_pruner.py` compresses raw HTML into an AST-like hierarchical tag tree.

### Pruning Logic
1. **Garbage Collection**: Decomposes all non-visible metadata tags (`script`, `style`, `meta`, `link`, `noscript`).
2. **Interactive Node Filtering**: Scans the remaining body for interactive elements (`button`, `a`, `input`, `select`, `textarea`, `form`, `label`).
3. **Keyword Ranking**: Scans text contents and important attributes (`id`, `name`, `class`, `placeholder`) for keyword matches, ranking matched elements by relevance.
4. **AST Tree Reconstruction**: Reconstructs the hierarchy by keeping only target elements and their structural ancestors (e.g., forms containing the inputs).

### HTML Structure Compression Example
#### Raw Input DOM
```html
<!DOCTYPE html>
<html>
<head>
  <style>body { font-size: 14px; }</style>
  <script>console.log("noisy execution log");</script>
</head>
<body>
  <header>
    <div class="logo">Company Name</div>
  </header>
  <main>
    <div class="content-wrapper">
      <form id="login-form" action="/auth" method="POST">
        <div class="form-row">
          <label for="usr">Username</label>
          <input type="text" id="usr" name="username" placeholder="Enter username" />
        </div>
        <div class="form-row">
          <label for="pwd">Password</label>
          <input type="password" id="pwd" name="password" />
        </div>
        <div class="submit-block">
          <button type="submit" class="btn btn-primary">Login Now</button>
        </div>
      </form>
    </div>
  </main>
</body>
</html>
```

#### Pruned AST Output DOM
```html
<body>
  <form id="login-form">
    <label for="usr" text="Username"></label>
    <input id="usr" name="username" type="text" placeholder="Enter username"></input>
    <label for="pwd" text="Password"></label>
    <input id="pwd" name="password" type="password"></input>
    <button type="submit" class="btn btn-primary" text="Login Now"></button>
  </form>
</body>
```

---

## 📦 Executor Output Contract

The framework execution routes **always return HTTP 200** with a **ZIP file** download containing the execution records. The real outcome is communicated via response headers (check `X-Semantic-Status`).

Use the route that matches the generated script framework:

- `POST /executor/playwright/run`
- `POST /executor/selenium/run`
- `POST /executor/cypress/run`
- `POST /executor/appium/run`

### 📂 Archiving & Persistence Layout
Upon completing execution (whether successful or failed), the orchestrator archives the runtime context under `successful_runs/` or `failed_runs/` respectively:
- **Passed Runs**: Copied to `successful_runs/<run_id>/`
- **Failed Runs**: Copied to `failed_runs/<run_id>/` (contains both `repair_report.json` and `final_failure_explanation.json` diagnostic output)

### 🧹 Automatic Background Cleanup
To prevent disk pollution and host storage leaks:
1. All staging directories and intermediate files staged in the `runs/` root are automatically deleted.
2. The generated download `.zip` response file is asynchronously deleted from the host using FastAPI `BackgroundTask` execution 2 seconds after completion.

### ✅ Success Response

```
HTTP 200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="<run_id>.zip"

X-Semantic-Status: passed
X-Run-ID:          <run_id>           e.g. a3f9b21c
X-Request-ID:      <request_id>       e.g. 4e8d123abc01
X-Duration-Ms:     <total_ms>         e.g. 12340.5
X-Script-Hash:     <sha256[:12]>      e.g. 3fa8c1d90e41
```

#### Contents of the ZIP (success)
```
<run_id>/
├── <script_filename>.py              ← the uploaded (and possibly patched) script
├── artifacts/
│   ├── steps/<step_id>/
│   │   ├── status.txt                ← "passed"
│   │   ├── summary.json              ← per-step timings & metrics
│   │   └── screenshot.png            ← screenshot at end of step (if captured)
│   └── status.txt                    ← "passed"  (top-level)
├── final_script.py                   ← the final healed script on disk
└── repair_report.json                ← full repair history
```

**`repair_report.json` (success, no repairs)**
```json
{
  "final_status": "passed",
  "iterations": 1,
  "repairs": [],
  "execution_id": "a3f9b21c",
  "timestamp": "2026-06-02T10:01:00.000Z"
}
```

**`repair_report.json` (success, after self-healing)**
```json
{
  "final_status": "passed",
  "iterations": 2,
  "repairs": [
    {
      "step_id": "TC_PARABANK__step_5",
      "attempt": 1,
      "outcome": "patched",
      "explanation": { "root_cause": "...", "recommendation": "..." },
      "timestamp": "2026-06-02T10:01:15.000Z"
    }
  ],
  "execution_id": "a3f9b21c",
  "timestamp": "2026-06-02T10:01:30.000Z"
}
```

---

### ❌ Failure Response

```
HTTP 200 OK
Content-Type: application/zip

X-Semantic-Status: failed        ← KEY — check this header
X-Run-ID:          <run_id>
X-Request-ID:      <request_id>
X-Duration-Ms:     <total_ms>
X-Script-Hash:     <sha256[:12]>
```

#### Contents of the ZIP (failure)
```
<run_id>/
├── <script_filename>.py              ← the script (possibly partially patched)
├── artifacts/
│   └── <step_id>/
│       ├── status.txt                ← "failed"
│       ├── error.txt                 ← traceback & error message
│       ├── dom_snapshot.html         ← DOM at time of failure
│       ├── step_summary.json         ← step context used for repair
│       └── screenshot.png            ← screenshot at failure point
└── final_failure_explanation.json    ← LLM root-cause analysis
```

**`final_failure_explanation.json`**
```json
{
  "step_id": "TC_PARABANK__step_5",
  "step_intent": "click the Send Payment button",
  "original_code": "await page.click('#sendPayment')",
  "repaired_code": "PERMANENT_FAILURE (Self-healing attempts exhausted)",
  "explanation": "The element could not be located with any strategy...",
  "root_cause": "Button ID changed from #sendPayment to #submit-payment",
  "recommendation": "Update locator to use: page.get_by_role('button', name='Send Payment')"
}
```

### ⚠️ Hard Error Responses (non-200)

These are returned for request-level errors only — never for test step failures:

| Status | Meaning |
|--------|---------|
| `400` | Not a `.py` file, or file is not valid UTF-8 |
| `403` | Script rejected by AST sandbox security validator |
| `503` | Sandbox execution is disabled (`ENABLE_SANDBOX_EXECUTION=false` in non-dev env) |
| `500` | Internal server error (unexpected crash) |

---

## 🗄️ Data Repository Models & Index Specification

Database records are defined in `app/models/database.py` and managed by the repository layer (`app/core/repositories/`).

### RepairRecord
Stores outcomes of repair attempts:
* `id` (str): Unique UUID.
* `step_id` (str): ID of the failing step.
* `original_code` (str): The original failing code block.
* `repaired_code` (str, optional): The corrected code.
* `intent` (str): Description of the step.
* `error_type` (str) & `error_message` (str): Failure details.
* `outcome` (str): `success`, `not_repairable`, `timeout`, or `model_error`.
* `duration_ms` (int): Processing duration.
* `model_name` (str): Model name (e.g. `gemini-2.5-pro`).
* `request_id` (str, optional): Correlation ID.
* `created_at` (datetime): Timestamp.

### ExecutionRecord
Tracks script executions:
* `id` (str): Unique UUID.
* `run_id` (str): ID of the run.
* `script_path` (str) & `script_hash` (str): File metadata.
* `status` (str): `passed`, `failed`, `timeout`, or `error`.
* `exit_code` (int): Subprocess exit code.
* `duration_ms` (int): Total run duration.
* `stdout` (str): First 10,000 chars of stdout (truncated).
* `stderr` (str): First 10,000 chars of stderr (truncated).
* `repairs_attempted` (int) & `repairs_successful` (int): Auto-repair counts.
* `request_id` (str): Correlation ID.
* `metadata` (dict): Full repair history and orchestrator context.
* `created_at` (datetime): Timestamp.

### MongoDB Index Specifications
Indexes are auto-created on every startup by `app/core/repositories/mongo.py`:
1. **Search Index on request_id**:
   `db.repair_records.create_index([("request_id", 1)])`
2. **Compound Index on step_id & created_at**:
   `db.repair_records.create_index([("step_id", 1), ("created_at", -1)])`
3. **TTL Auto-Expiry Index** — purges records older than 30 days:
   `db.repair_records.create_index("created_at", expireAfterSeconds=2592000)`

---

## 🧠 Gemini Structured Output (Schema-Enforced JSON)

Two LLM calls in the repair pipeline produce JSON responses. Rather than embedding `"Return JSON only: ..."` instructions in the prompt and then fighting to extract and repair the output, both calls use **Gemini's native structured output mode** — the model is constrained at the API level to emit valid JSON that matches a declared Pydantic schema.

### How it Works

The Gemini Python SDK (`google-genai`) accepts a `GenerateContentConfig` with two fields:

```python
from google.genai.types import GenerateContentConfig

config = GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=MyPydanticModel,   # Pydantic BaseModel class, not instance
)
response = client.models.generate_content(
    model=model_name,
    contents=prompt,
    config=config,
)
# response.text is always valid JSON conforming to MyPydanticModel
```

When `response_mime_type="application/json"` is set, the Gemini API rejects any candidate that does not parse as JSON. When `response_schema` is also set, the candidate must additionally conform to the supplied schema — Gemini enforces this at sampling time, not post-hoc.

### Structured Output Models (`app/models/llm_structured.py`)

| Model | Used by | Fields |
|---|---|---|
| `VerifierResult` | `StepVerifier` | `verdict: Literal["correct", "incorrect"]`, `reason: str` |
| `RepairExplanation` | `RepairExplanationService` | `failure_reason`, `repair_action`, `why_previous_failed`, `why_repair_was_selected`, `rerun_result`, `execution_passed`, `failure_type`, `summary` |

`failure_type` is a `Literal` enum constraining the model to one of: `LOCATOR_CHANGE`, `ELEMENT_NOT_VISIBLE`, `DOM_CHANGE`, `TIMING_ISSUE`, `ASSERTION_CHANGE`, `UNKNOWN`.

### LLM Executor Methods (`app/core/llm_executor.py`)

Three new public methods parallel their unstructured counterparts:

| Method | Role | Schema |
|---|---|---|
| `run_verifier_structured(prompt, schema)` | `VERIFIER` | `VerifierResult` |
| `run_modifier_structured(prompt, schema)` | `MODIFIER` | `RepairExplanation` |
| `run_multimodal_modifier_structured(*, prompt, image_bytes, schema)` | `MODIFIER` | `RepairExplanation` |

All three pass a `GenerateContentConfig` into the internal `_run` / `_run_multimodal` pipeline, which threads it through to `_generate_text` / `_generate_multimodal`. The fallback model path and the multimodal→text image-rejection fallback both preserve the config so structured output is maintained across retries.

### Parsing

Because the API guarantees schema conformance, the consuming services simply call:

```python
result = VerifierResult.model_validate_json(raw)
# or
result = RepairExplanation.model_validate_json(raw)
```

A single `try/except` is the only safety net needed — no regex, no fence stripping, no trailing-comma repair, no multi-pass fallback extraction.

### What Was Removed

| File | Removed |
|---|---|
| `app/services/step_verifier.py` | `_coerce_result`, `_parse_truncated_json`, `_normalize_result_dict`, `_coerce_embedded_reason`, `_extract_first_json`, `_loads_json`, `_strip_fences` (~200 lines) |
| `app/services/repair_explanation_service.py` | `_safe_parse_json` (~50 lines) |
| `app/core/prompts.py` | `"Return JSON only: ..."` instruction from verifier prompt; `"Return JSON only with keys: ..."`, `"Allowed failure_type values: ..."` instructions from repair explanation prompt |

`app/core/llm_json.py` is unchanged — it serves offline/metadata tasks that are outside the repair pipeline.

---

## 🤖 Action Extractors & Prompt Engineering Specs

Extractors are defined in `app/services/extractors/`.

The canonical source for every live LLM prompt lives in `app/core/prompts.py`. The examples below describe the prompt contracts, but the registry file is the single place to edit prompt wording, truncation rules, and response formats.

```
              ┌───────────────┐
              │ BaseExtractor │
              └───────┬───────┘
                      │
     ┌───────────┬────┴────┬───────────┬───────────┐
     ▼           ▼         ▼           ▼           ▼
┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐
│  Click  ││  Type   ││ Select  ││ Assert  ││ Dialog  │
│Extractor││Extractor││Extractor││Extractor││Extractor│
└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘
```

### 1. ClickExtractor
* **Failing Signature**: `await page.click("...")` or `await page.locator("...").click()`
* **Prompt Spec**:
  ```text
  Classify the failed Playwright step.
  Identify CLICK action visible text (preserve casing/spacing exactly).
  No CSS/XPath. No hallucinated/invented values.

  Reply ONLY one of:
  - none
  - click:text("<EXACT visible text>")

  Intent: {step_intent}
  Code: {original_code}
  Error: {error_message}
  DOM: {pruned_dom}
  ```

### 2. TypeExtractor
* **Failing Signature**: `await page.fill("...")` or `await page.type("...")`
* **Prompt Spec**:
  ```text
  Analyze FAILED Playwright TYPE step.
  Identify target field and value kind. No CSS/XPath. No invented literals.

  Reply ONLY one of:
  - none
  - type:label("<label_text>") value("<kind>")
  - type:placeholder("<placeholder_text>") value("<kind>")
  - type:role(textbox, name="<name>") value("<kind>")

  Where <kind> is: email, username, password, text, or number.
  ```

### 3. SelectExtractor
* **Failing Signature**: `await page.select_option("...")`
* **Prompt Spec**:
  ```text
  Analyze FAILED Playwright SELECT step.
  Identify targeted dropdown and option text (preserve casing/spacing exactly).
  No CSS/XPath. No invented values.

  Reply ONLY one of:
  - none
  - select:text("<dropdown_text>") value("<option_text>")
  - select:label("<label_text>") value("<option_text>")
  ```

### 4. AssertExtractor
* **Failing Signature**: `expect(locator).to_be_visible()` or similar assertions.
* **Prompt Spec**:
  ```text
  Analyze FAILED Playwright assertion.
  Identify assertion details (preserve visible text casing/spacing exactly).
  No CSS/XPath. No invented values.

  Reply ONLY one of:
  - none
  - url_contains:<fragment>
  - element_visible
  - element_visible:text("<EXACT visible text>")
  ```

### 5. DialogExtractor
* **Failing Signature**: Test blocked by unexpected JavaScript `alert`, `confirm`, or `prompt`.
* **Prompt Spec**:
  ```text
  Analyze FAILED Playwright step for RUNTIME DIALOG or POPUP.
  Identify dialog action and visible text (if any).

  Reply ONLY one of:
  - none
  - dialog:accept:text("<visible text>")
  - dialog:dismiss:text("<visible text>")
  - dialog:close:text("<visible text>")
  - dialog:accept:none
  - dialog:dismiss:none
  - dialog:close:none
  ```

### The Literal Guard
To prevent hallucinations, the `BaseExtractor` uses `_literal_exists_in_sources` to verify that any extracted string **literally exists** in either the step intent, original code, or DOM snapshot before proceeding with the repair.

---

## 📊 Observability, Health Checks, & Prometheus Metrics

The engine monitors health and exports operational metrics via Prometheus.

### Registered Prometheus Metrics
* `repair_requests_total`: Total repair requests received (labeled by `outcome` and `action_type`).
* `repair_duration_seconds`: Histogram of repair processing times.
* `repair_pipeline_stage_duration_seconds`: Per-stage timing (cir_build, code_generation, verification_1, modification, verification_2).
* `llm_calls_total`: Total LLM requests (labeled by `model` and `status`).
* `script_executions_total`: Total script executions (labeled by `status`).
* `script_execution_duration_seconds`: Histogram of execution durations.
* `http_requests_total`: HTTP request counter (labeled by `method`, `path`, `status`).
* `http_request_duration_seconds`: HTTP latency histogram.
* `http_requests_in_progress`: In-flight request gauge.
* `circuit_breaker_state`: Gauge tracking circuit breaker (0 = Closed, 1 = Open, 2 = Half-Open).

### Health Checks Integration
* `/health/live`: Basic application life check — returns 200 if process is running.
* `/health/ready`: Checks startup completion, API-key configuration, MongoDB, Redis, disk space, and memory.
* `/health/startup`: Verifies startup prerequisites before the service begins receiving traffic.
* `/health/deep`: Includes a cached, low-token LLM connectivity check in addition to the readiness checks.

---

## 📂 Detailed File Map & Directory Index

```text
app/
├── api/                        # Compatibility router exports
│   └── v1/
│       ├── executor.py         # Compatibility wrapper to app/routes/executor.py
│       ├── health.py           # Compatibility wrapper to app/routes/health.py
│       ├── metrics.py          # Compatibility wrapper to app/routes/metrics.py
│       └── repair.py           # Compatibility wrapper to app/routes/repair.py
├── core/                       # Core system services
│   ├── exceptions/             # Exceptions package
│   │   ├── __init__.py         # Package entry exposing global error handler
│   │   ├── api.py              # API schema client validation errors
│   │   ├── base.py             # Root exception base class and ErrorCode values
│   │   ├── executor.py         # Sandbox security violations & execution errors
│   │   └── repair.py           # Repair pipeline timeout & retry failures
│   ├── repositories/           # Repositories database storage package
│   │   ├── __init__.py         # Package entry
│   │   ├── base.py             # Repository base abstract class
│   │   ├── in_memory.py        # Transient dictionary store for testing
│   │   └── mongo.py            # MongoDB repository with TTL & search indexing
│   ├── base64_utils.py         # Base64 image validators
│   ├── config.py               # Settings manager supporting CSV list parsing
│   ├── database.py             # Motor connection manager with timeout controls
│   ├── dom_pruner.py           # Compresses HTML to an AST-style tag tree
│   ├── health.py               # System health monitors
│   ├── io.py                   # Atomic file writer with write-fallback logic
│   ├── llm_executor.py         # Gemini API wrapper with rate-limit retries and structured output methods
│   ├── llm_json.py             # Best-effort JSON extraction for offline/metadata tasks (not used in repair pipeline)
│   ├── metrics.py              # Prometheus metrics collector definitions
│   ├── prompts.py              # Central registry for every live LLM prompt and prompt-trimming helper
│   ├── redis_state.py          # State/cache management for long-running processes
│   ├── resilience.py           # CircuitBreaker and Exponential Backoff definitions
│   ├── security.py             # API key checkers & rate limit algorithms
│   ├── tracing.py              # Traceparent context spans wrappers
│   └── utils.py                # Hashing, timers, FailureFingerprint, and correlation contextvars
├── executors/                  # Execution environments
│   ├── __init__.py             # Package entry exposing run interfaces
│   ├── base.py                 # Abstract base Executor definition
│   ├── models.py               # ExecutionResult dataclass & ExecutionOutcome enum
│   ├── python.py               # AsyncPythonExecutor + SandboxedPythonExecutor (subprocess, Docker)
│   └── sandbox.py              # AST-based script security auditor (two-layer: AST + regex)
├── models/                     # Data schemas
│   ├── cir.py                  # Canonical Intermediate Representation schemas
│   ├── context.py              # Runtime validation context models
│   ├── database.py             # DB persistence schemas (RepairRecord, ExecutionRecord)
│   ├── extraction.py           # Models for locator values returned from extractors
│   ├── llm_structured.py       # Pydantic schemas for Gemini structured output (VerifierResult, RepairExplanation)
│   └── step_repair.py          # Pydantic schemas for /repair endpoints
├── routes/                     # Live FastAPI route groups mounted by app.main
│   ├── executor.py             # POST /executor/{framework}/run, GET /executor/stats
│   ├── health.py               # GET /health, /health/live, /health/ready, /health/startup, /health/deep
│   ├── metrics.py              # GET /metrics (Prometheus scrape endpoint)
│   └── repair.py               # POST /repair
├── services/                   # Business logic engines
│   ├── extractors/             # Consolidated Extractors package
│   │   ├── __init__.py         # Package entry
│   │   ├── BaseExtractor.py    # Parent extractor class with literal-guard utility
│   │   ├── ClickExtractor.py   # Extracts CLICK locators using targeted prompts
│   │   ├── TypeExtractor.py    # Extracts TYPE targets and field inputs
│   │   ├── SelectExtractor.py  # Extracts SELECT options and dropdown locators
│   │   ├── AssertExtractor.py  # Extracts ASSERT verifications & URL contains
│   │   ├── DialogExtractor.py  # Intercepts runtime dialogs (alerts, confirms)
│   │   └── ExtractorFactory.py # Maps ActionTypes to extractor classes
│   ├── atomic_normalizer.py    # Text normalizer and spacing standardizer
│   ├── auto_repair_trigger.py  # Parses failure directories to build StepRepairRequests
│   ├── cir_builder.py          # Constructs StepRepairRequests into a CIR block schema
│   ├── diff.py                 # Unified diff utility for showing patched code changes
│   ├── execution_orchestrator.py # Self-healing loop: execute → detect → repair → patch → retry
│   ├── framework_classifier.py # Classifier detecting test framework (Playwright, Selenium, Appium, Cypress)
│   ├── generator.py            # Generates Playwright code from normalized locators
│   ├── llm_classifier.py       # Interrogates LLM to classify action types
│   ├── llm_fallback_repair.py  # Secondary repair loop using full code context
│   ├── repair_explanation_service.py # Generates LLM summaries of script modifications
│   ├── repair_pipeline.py      # Executes CIR build → gen → verifier pass 1 → modify → verifier pass 2
│   ├── repair_service.py       # Handles FastAPI-level repair actions
│   ├── rollback.py             # Registers backups and restores scripts on failure
│   ├── script_patcher.py       # Patches async def _step_X body AND _guarded_step() string arg
│   ├── step_modifier.py        # Generates verifier-guided code variations
│   ├── step_verifier.py        # Validates code proposals in sandboxed subprocesses
│   └── validator.py            # Pre-flight code and intent validators
├── tasks/                      # Asynchronous tasks
│   ├── celery_app.py           # Celery application configuration
│   └── repair_tasks.py         # Asynchronous worker task definitions
├── main.py                     # App entry point: PrettyFormatter, JSONFormatter, ConsoleFormatter, lifespan, middleware stack
└── middleware.py               # Audit log & request timing middleware
run.py                          # Developer startup wrapper: venv guard, --mode, --host, --port, --no-reload, --log-level
```

---

## ⚙️ Configuration & Environment Variables

All variables are read from `.env` at startup via `app/core/config.py`.

### App & Environment
| Variable | Type | Default | Description |
|---|---|---|---|
| `ENV` | literal | `development` | Running environment: `development`, `staging`, or `production` |
| `APP_NAME` | string | `Playwright Step Repair Engine` | App display name |
| `VERSION` | string | `3.0.0` | Semantic version |

### Google LLM / API Keys
| Variable | Type | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | string | `None` | Primary Gemini API key |
| `GOOGLE_API_KEYS` | list | `[]` | Additional API keys for round-robin rotation |

### Authentication
| Variable | Type | Default | Description |
|---|---|---|---|
| `ENABLE_API_AUTH` | boolean | `True` | Enables API-key authentication on protected routes |
| `ALLOWED_API_KEYS` | list | `[]` | Accepted API keys when auth is enabled |
| `API_SECRET_KEY` | string | `None` | Legacy shared secret option for auth |
| `API_KEY_HEADER` | string | `X-API-Key` | Header name used for API-key auth |

### LLM Configuration
| Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_MODEL_NAME` | string | `gemini-2.5-pro` | Gemini model to use |
| `LLM_TIMEOUT_SECONDS` | integer | `150` | Gemini API call timeout |
| `LLM_MAX_RETRIES` | integer | `3` | Max retries on LLM failure |
| `LLM_MAX_CONCURRENT_CALLS` | integer | `3` | Max concurrent LLM requests |
| `LLM_RATE_LIMIT_SLEEP` | float | `2.0` | Sleep between LLM calls when rate-limited |
| `LLM_VERIFIER_MAX_TOKENS` | integer | `512` | Token budget for verifier prompts |
| `LLM_CLASSIFIER_MAX_TOKENS` | integer | `512` | Token budget for classifier prompts |
| `LLM_EXTRACTOR_MAX_TOKENS` | integer | `8192` | Token budget for extractor prompts |
| `LLM_MODIFIER_MAX_TOKENS` | integer | `8192` | Token budget for modifier prompts |

### Safety & Sandbox
| Variable | Type | Default | Description |
|---|---|---|---|
| `ENABLE_SANDBOX_EXECUTION` | boolean | `True` | Enables strict AST validation for uploaded scripts |
| `SANDBOX_ENABLED` | boolean | `True` | Keeps low-level sandbox execution paths enabled |
| `SANDBOX_USE_DOCKER` | boolean | `False` | Executes uploaded scripts inside Docker instead of host Python |
| `SANDBOX_ALLOW_NETWORK` | boolean | `False` | Allows outbound network when Docker sandboxing is enabled |
| `SANDBOX_DOCKER_IMAGE` | string | `python:3.11-slim` | Docker image used for sandbox execution |
| `ALLOW_UNSAFE_HOST_EXECUTION_IN_PRODUCTION` | boolean | `False` | Explicit override for host execution in production — keep `False` |
| `MAX_REQUEST_SIZE_BYTES` | integer | `5000000` | Maximum multipart or JSON payload size |
| `MAX_SCREENSHOT_SIZE_BYTES` | integer | `10000000` | Maximum screenshot upload size |
| `ALLOWED_SCREENSHOT_MIME_TYPES` | list | `image/png,image/jpeg,image/webp` | Supported repair screenshot content types |

### Appium Runtime
| Variable | Type | Default | Description |
|---|---|---|---|
| `ENABLE_APPIUM_EXECUTION` | boolean | `True` | Enables generated Appium Python script execution support |
| `APPIUM_SERVER_URL` | string | `http://YOUR_APPIUM_VM_IP:4723/wd/hub` | Remote Appium server URL expected by generated Appium scripts |
| `APPIUM_DEVICE_FILTER` | string | empty | Optional comma-separated runtime Appium device labels/slugs/device names to run |
| `APPIUM_DEVICE_MATRIX_JSON` | JSON string | empty | Optional default runtime Appium device matrix/capability JSON |
| `APPIUM_DEVICE_MATRIX_PATH` | string | `appium_device_matrix.json` | Optional path to a default runtime Appium device matrix file, read on each Appium request |

### Repair Pipeline Limits
| Variable | Type | Default | Description |
|---|---|---|---|
| `MAX_LLM_MODIFICATIONS` | integer | `1` | Max LLM repair iterations per step |
| `MAX_VERIFICATION_PASSES` | integer | `2` | Max verifier passes per repair cycle |
| `MAX_STEP_CODE_LENGTH` | integer | `2000` | Max characters in a step code block |
| `MAX_STEP_LINES` | integer | `50` | Max lines in a step code block |

### Feature Flags
| Variable | Type | Default | Description |
|---|---|---|---|
| `ENABLE_SELF_HEALING` | boolean | `True` | Enables the repair loop during executor runs |
| `ENABLE_MULTIMODAL` | boolean | `True` | Enables multimodal (screenshot) LLM analysis |
| `DRY_RUN_MODE` | boolean | `False` | Dry-run mode — no actual disk patches |
| `ENABLE_RATE_LIMITING` | boolean | `True` | Enables request throttling |
| `ENABLE_METRICS` | boolean | `True` | Enables metrics middleware and `/metrics` |
| `ENABLE_TRACING` | boolean | `False` | Enables OpenTelemetry tracing middleware |

### Rate Limiting
| Variable | Type | Default | Description |
|---|---|---|---|
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | integer | `60` | Request throttle per minute |
| `RATE_LIMIT_REQUESTS_PER_HOUR` | integer | `1000` | Request throttle per hour |
| `RATE_LIMIT_BURST_SIZE` | integer | `10` | Burst allowance above the rate limit |
| `TRUST_FORWARDED_IP` | boolean | `False` | Whether to trust proxy headers like `X-Forwarded-For` for rate-limiting client IP resolution |

### Security Context: Trusted Proxy (`TRUST_FORWARDED_IP`)

#### Why this approach is used
In production environments, services are often deployed behind load balancers, reverse proxies (like Nginx, HAProxy), or API gateways. By default, these proxies forward the original client's IP in headers such as `X-Forwarded-For` or `X-Real-IP`.

If a microservice blindly trusts these headers without verification, a malicious client can bypass the gateway and send spoofed headers directly to the service. For example, by sending a custom header like `X-Forwarded-For: 8.8.8.8` on every request, an attacker could spoof their IP, bypass rate limiters, or falsify security audit logs.

To prevent IP spoofing, we follow a defense-in-depth approach:
- By default, `TRUST_FORWARDED_IP` is set to `false`, meaning the microservice ignores forwarded headers and resolves the client IP to the direct socket IP (`request.client.host`).
- It should only be set to `true` when the service is safely sandboxed behind a trusted reverse proxy that is explicitly configured to sanitize, preserve, or overwrite client IP headers.

### MongoDB
| Variable | Type | Default | Description |
|---|---|---|---|
| `MONGODB_URL` | string | `None` | MongoDB connection string |
| `MONGODB_DB_NAME` | string | `repair_engine` | MongoDB database name |
| `ALLOW_INMEMORY_DATABASE_FALLBACK` | boolean | `False` | Allows MongoDB failures to fall back to in-memory storage outside development |

### Redis
| Variable | Type | Default | Description |
|---|---|---|---|
| `REDIS_URL` | string | `None` | Redis connection string |
| `REDIS_MAX_CONNECTIONS` | integer | `10` | Maximum Redis pool size |

### Celery (Optional)
| Variable | Type | Default | Description |
|---|---|---|---|
| `CELERY_BROKER_URL` | string | `None` | Optional Celery broker URL |
| `CELERY_RESULT_BACKEND` | string | `None` | Optional Celery result backend |
| `CELERY_TASK_TIMEOUT` | integer | `300` | Hard execution timeout for Celery tasks |
| `CELERY_TASK_SOFT_TIMEOUT` | integer | `270` | Soft timeout for Celery tasks |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | integer | `1` | Worker prefetch multiplier |
| `CELERY_WORKER_CONCURRENCY` | integer | `4` | Default Celery worker concurrency |

### Executor
| Variable | Type | Default | Description |
|---|---|---|---|
| `EXECUTOR_TIMEOUT_SECONDS` | integer | `800` | Maximum executor runtime per script |
| `EXECUTOR_BASE_WORK_DIR` | string | `None` | Base directory for run folders (defaults to `cwd`) |

### Circuit Breaker
| Variable | Type | Default | Description |
|---|---|---|---|
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | integer | `5` | Failures before circuit opens |
| `CIRCUIT_BREAKER_RESET_TIMEOUT` | integer | `60` | Seconds before attempting half-open |

### Observability
| Variable | Type | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | string | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT_MODE` | string | `CONSOLE` | `JSON` (structured), `CONSOLE` (human-readable), or `PRETTY` (emoji+color) |
| `OTEL_EXPORTER_ENDPOINT` | string | `None` | OpenTelemetry exporter endpoint |
| `OTEL_SERVICE_NAME` | string | `playwright-repair-engine` | Service name in traces |
| `SENTRY_DSN` | string | `None` | Sentry DSN for error tracking |

### CORS
| Variable | Type | Default | Description |
|---|---|---|---|
| `CORS_ORIGINS` | list | `["http://localhost:3000"]` | Allowed CORS origins |
| `CORS_ALLOW_CREDENTIALS` | boolean | `False` | Allow credentials in CORS requests |
| `CORS_ALLOW_METHODS` | list | `["POST","GET","OPTIONS"]` | Allowed HTTP methods |
| `CORS_ALLOW_HEADERS` | list | `["Authorization","Content-Type","X-API-Key","X-Request-ID"]` | Allowed headers |

---

## 💻 Setup, Running, and Deployment CLI Commands

### 1. Project Initialization
Install python dependencies:
```bash
pip install -r requirements.txt
```

Create a local `.env` with at least:

```bash
GOOGLE_API_KEY=your-gemini-key
ALLOWED_API_KEYS=["client_sec_key"]
ENABLE_API_AUTH=true
ENABLE_SANDBOX_EXECUTION=true
```

If you want durable persistence and distributed state, also configure:

```bash
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=repair_engine
REDIS_URL=redis://localhost:6379/0
```

For production executor isolation, enable Docker sandboxing:

```bash
SANDBOX_USE_DOCKER=true
SANDBOX_DOCKER_IMAGE=python:3.11-slim
```

### 2. Appium Runtime Setup for Generated Mobile Scripts
Executor-Regenerator can execute generated Appium Python scripts. The generated script does not create the mobile device by itself; it creates an Appium WebDriver session against the URL in `APPIUM_SERVER_URL`.

The supported model is now remote Appium:

- Your GCP VM, BrowserStack, Sauce Labs, or another device farm hosts Appium and the mobile device.
- Executor-Regenerator runs only the Python script and talks to Appium over HTTP.
- Do not install Android Studio, create a laptop AVD, start local Appium, or rely on laptop `adb devices` for this flow.
- Device/app selection belongs in `appium_device_matrix` or `APPIUM_DEVICE_MATRIX_JSON`.

The generated Appium script stays device agnostic; Executor-Regenerator supplies Appium capabilities at runtime through `appium_device_matrix` or `APPIUM_DEVICE_MATRIX_JSON`.

#### Private GCP Appium VM

```env
ENABLE_APPIUM_EXECUTION=true
APPIUM_SERVER_URL=http://34.46.45.187:4723/wd/hub
```

Set the default device matrix in `.env` or pass it in Swagger/curl as `appium_device_matrix`:

```json
{
  "devices": [
    {
      "label": "Pixel 7 Local GCP",
      "slug": "pixel_7_local_gcp",
      "device_name": "Pixel_7_API_36",
      "platform_name": "Android",
      "udid": "emulator-5554",
      "app_package": "com.google.android.deskclock",
      "app_activity": "com.android.deskclock.DeskClock",
      "app_wait_activity": "*",
      "no_reset": true,
      "relaunch_before_test": true,
      "relaunch_before_step_retry": true
    }
  ]
}
```

For the full VM setup, firewall, Appium listener, and troubleshooting flow, see [Local-Mobile-Execution.md](Local-Mobile-Execution.md).

#### BrowserStack App Automate

Use BrowserStack when the device and Appium server are hosted by BrowserStack. In this mode:

- Do not run local Appium.
- Do not depend on local `adb devices`.
- Upload your `.apk`, `.aab`, `.xapk`, or `.ipa` to BrowserStack first, or use a public app URL/custom ID supported by BrowserStack.
- BrowserStack returns an app identifier like `bs://<APP_ID>` after upload. Use that as the app capability.

BrowserStack upload example:

```powershell
$env:BROWSERSTACK_USERNAME="YOUR_USERNAME"
$env:BROWSERSTACK_ACCESS_KEY="YOUR_ACCESS_KEY"

curl.exe -u "$env:BROWSERSTACK_USERNAME`:$env:BROWSERSTACK_ACCESS_KEY" `
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" `
  -F "file=@D:\path\to\your-app.apk"
```

The response contains:

```json
{
  "app_url": "bs://<APP_ID>"
}
```

Set Executor-Regenerator `.env` to the BrowserStack Appium hub. Prefer environment-level credentials so the generated script does not need to contain secrets:

```env
ENABLE_APPIUM_EXECUTION=true
APPIUM_SERVER_URL=https://YOUR_USERNAME:YOUR_ACCESS_KEY@hub-cloud.browserstack.com/wd/hub
```

If your username or access key contains reserved URL characters, URL-encode those characters before putting them in `APPIUM_SERVER_URL`.

Then provide BrowserStack capabilities to Executor-Regenerator at runtime. Do not put BrowserStack credentials or device matrix branches into the generated script.

```json
{
  "devices": [
    {
      "label": "Pixel 7",
      "device_name": "Google Pixel 7",
      "platform_name": "Android",
      "platform_version": "14.0",
      "app": "bs://ANDROID_APP_ID",
      "app_package": "your.android.package",
      "app_activity": ".MainActivity",
      "no_reset": true,
      "extra_capabilities": {
        "bstack:options": {
          "projectName": "Executor-Regenerator",
          "buildName": "Generated Appium Build",
          "sessionName": "Pixel 7 runtime run",
          "debug": true,
          "networkLogs": true,
          "deviceLogs": true,
          "appiumLogs": true
        }
      }
    }
  ]
}
```

Notes:

- BrowserStack supports Appium capabilities and BrowserStack-specific options such as project/build/session metadata and logs.
- If your app talks to an internal dev/staging backend, configure BrowserStack Local or expose that backend in a provider-approved way.
- Provider-side video/logs are visible in BrowserStack. Executor-Regenerator still creates its own local ZIP artifacts from the script execution.

Useful BrowserStack docs:

- BrowserStack App Automate capabilities: `https://www.browserstack.com/docs/app-automate/capabilities`
- BrowserStack App Automate upload API: `https://www.browserstack.com/docs/app-automate/api-reference/appium/apps`

#### BrowserStack End-to-End Matrix Runbook

Use this flow when you want Executor-Regenerator to run a generated Appium matrix script on BrowserStack real devices, such as Pixel 7, OnePlus, and iPhone.

##### 1. Open BrowserStack and get credentials

1. Open `https://www.browserstack.com`.
2. Click **Sign In**.
3. Go to the **App Automate** dashboard.
4. Find your BrowserStack **Username** and **Access Key**.
   - BrowserStack exposes these in the App Automate dashboard and Account Settings.
   - Treat the access key like a password.
   - Do not commit it into the repo.

For PowerShell, keep them in the current terminal session:

```powershell
$env:BROWSERSTACK_USERNAME="YOUR_USERNAME"
$env:BROWSERSTACK_ACCESS_KEY="YOUR_ACCESS_KEY"
```

##### 2. Upload the app under test

BrowserStack must have access to the mobile app before it can install it on hosted devices.

Upload from the BrowserStack website:

1. In the BrowserStack **App Automate** dashboard, open **App Management**.
2. Click **Upload App**.
3. Select your Android `.apk`/`.aab` or iOS `.ipa`.
4. Choose the App Automate/Appium framework when prompted.
5. After upload, copy the returned app identifier.

Upload from PowerShell instead:

```powershell
curl.exe -u "$env:BROWSERSTACK_USERNAME`:$env:BROWSERSTACK_ACCESS_KEY" `
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" `
  -F "file=@D:\path\to\your-android-app.apk"
```

The response contains an `app_url`:

```json
{
  "app_url": "bs://ANDROID_APP_ID"
}
```

For iOS, upload the `.ipa` separately:

```powershell
curl.exe -u "$env:BROWSERSTACK_USERNAME`:$env:BROWSERSTACK_ACCESS_KEY" `
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" `
  -F "file=@D:\path\to\your-ios-app.ipa"
```

Copy the second `app_url` as `bs://IOS_APP_ID`.

##### 3. Choose BrowserStack devices

Open the BrowserStack App Automate device/capability selection UI and pick the exact devices and OS versions available to your account.

Example selections:

```text
Pixel 7          -> Google Pixel 7, Android 13/14
OnePlus         -> OnePlus 11 or the latest OnePlus device available
iPhone Latest   -> newest iPhone model and iOS version shown in BrowserStack
```

Use the exact BrowserStack names in your matrix. Do not assume that `latest iPhone` is a magic value unless BrowserStack shows/supports that exact name in your capability generator.

##### 4. Generate or reuse the Appium script

Generate one Appium Python script from Script Generator. Do not put Pixel 7, OnePlus, or iPhone branches into that generated script. The script should contain only the test steps; Executor-Regenerator chooses devices when `/executor/appium/run` is called.

The script reads these runtime values:

- `APPIUM_SERVER_URL`: BrowserStack hub URL.
- `APPIUM_CAPABILITIES_JSON`: one selected device capability object.
- `APPIUM_DEVICE_CONTEXT_JSON`: label/slug/platform metadata used in artifacts and repair prompts.

##### 5. Start Executor-Regenerator

Start the Executor-Regenerator API:

```powershell
cd D:\Demo-Ready-TW.2324\Executor-Regenrator
.\venv\Scripts\Activate.ps1
python run.py --mode console
```

You do not need a local Appium server for BrowserStack. BrowserStack hosts the Appium server and devices.

##### 6. Define the BrowserStack runtime matrix

Create the matrix in PowerShell. Use the exact device and OS names shown in BrowserStack's capability generator:

```powershell
$browserstackHub = "https://$env:BROWSERSTACK_USERNAME`:$env:BROWSERSTACK_ACCESS_KEY@hub-cloud.browserstack.com/wd/hub"

$matrix = @'
{
  "devices": [
    {
      "label": "Pixel 7",
      "device_name": "Google Pixel 7",
      "platform_name": "Android",
      "platform_version": "14.0",
      "app": "bs://ANDROID_APP_ID",
      "app_package": "com.example.android",
      "app_activity": ".MainActivity",
      "no_reset": true,
      "extra_capabilities": {
        "bstack:options": {
          "projectName": "Executor-Regenerator",
          "buildName": "Runtime Appium Matrix",
          "sessionName": "Pixel 7",
          "debug": true,
          "networkLogs": true,
          "deviceLogs": true,
          "appiumLogs": true
        }
      }
    },
    {
      "label": "OnePlus Latest",
      "device_name": "OnePlus 11",
      "platform_name": "Android",
      "platform_version": "13.0",
      "app": "bs://ANDROID_APP_ID",
      "app_package": "com.example.android",
      "app_activity": ".MainActivity",
      "no_reset": true,
      "extra_capabilities": {
        "bstack:options": {
          "projectName": "Executor-Regenerator",
          "buildName": "Runtime Appium Matrix",
          "sessionName": "OnePlus Latest",
          "debug": true,
          "networkLogs": true,
          "deviceLogs": true,
          "appiumLogs": true
        }
      }
    },
    {
      "label": "iPhone Latest",
      "device_name": "iPhone 15 Pro Max",
      "platform_name": "iOS",
      "platform_version": "17",
      "bundle_id": "com.example.ios",
      "app": "bs://IOS_APP_ID",
      "extra_capabilities": {
        "bstack:options": {
          "projectName": "Executor-Regenerator",
          "buildName": "Runtime Appium Matrix",
          "sessionName": "iPhone Latest",
          "debug": true,
          "networkLogs": true,
          "deviceLogs": true,
          "appiumLogs": true
        }
      }
    }
  ]
}
'@
```

You can keep this in `.env` as `APPIUM_DEVICE_MATRIX_JSON=...` for a default matrix, or point `APPIUM_DEVICE_MATRIX_PATH` at a JSON file such as `appium_device_matrix.json`. The file is read on every Appium request, which is useful when the active VM/emulator device changes.

##### 7. Run the full BrowserStack matrix through Executor-Regenerator

This runs the same generated script once for each selected device. Each device gets a fresh Appium session, its own self-healing loop, and its own normal run directory.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/executor/appium/run" `
  -H "X-API-Key: client_sec_key" `
  -F "script=@D:\path\to\generated_appium.py" `
  -F "appium_server_url=$browserstackHub" `
  -F "appium_device_matrix=$matrix" `
  --output browserstack-matrix-result.zip
```

If you provide only the script and no matrix, Executor-Regenerator first looks for a request matrix, then `APPIUM_DEVICE_MATRIX_JSON`, then the JSON file at `APPIUM_DEVICE_MATRIX_PATH` (default: `appium_device_matrix.json`). If any of those defaults exist, every device in that matrix runs one after another.

##### 8. Run only selected BrowserStack devices

Run only Pixel 7:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/executor/appium/run" `
  -H "X-API-Key: client_sec_key" `
  -F "script=@D:\path\to\generated_appium.py" `
  -F "appium_server_url=$browserstackHub" `
  -F "appium_device_matrix=$matrix" `
  -F "appium_device_filter=Pixel 7" `
  --output browserstack-pixel7-result.zip
```

Run Pixel 7 and iPhone:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/executor/appium/run" `
  -H "X-API-Key: client_sec_key" `
  -F "script=@D:\path\to\generated_appium.py" `
  -F "appium_server_url=$browserstackHub" `
  -F "appium_device_matrix=$matrix" `
  -F "appium_device_filter=Pixel 7,iPhone Latest" `
  --output browserstack-pixel7-iphone-result.zip
```

##### 9. Read the output

Executor-Regenerator returns a ZIP file.

The ZIP contains one folder per selected device. Each folder is a normal Executor-Regenerator run directory in the same shape as Playwright/Selenium output:

```text
matrix_summary.json
pixel_7/
  status.txt
  exit_code.txt
  started_at.txt
  finished_at.txt
  final_script.py
  repair_report.json
  success/
    summary.json
    0__step_.../
      step_summary.json
      screenshot.png
oneplus_latest/
  status.txt
  final_script.py
  success/
    summary.json
iphone_latest/
  status.txt
  final_script.py
  failures/
    summary.json
    2__step_.../
      attempt_1/
        device_context.json
        screenshot.png
        dom.xml
        error.txt
        traceback.txt
        step_code.py
```

`matrix_summary.json` is the outer index. The folders (`pixel_7`, `oneplus_latest`, `iphone_latest`) are intentionally separate, so your report flow can treat every device run like a normal run while still uploading one ZIP. Report-Generator also understands this outer matrix bundle and prefixes report steps with the device label.

BrowserStack results:

1. Open the BrowserStack **App Automate** dashboard.
2. Open the project/build name used in `bstack:options`.
3. Review each device session.
4. Use BrowserStack's video, device logs, network logs, Appium logs, and session status for provider-side debugging.

Executor-Regenerator artifacts and BrowserStack dashboard artifacts are complementary:

- Executor-Regenerator ZIP shows repair attempts, patched script, local summaries, screenshots, DOM XML, and final status.
- BrowserStack dashboard shows remote device sessions, infrastructure status, provider logs, video, and network/device logs when enabled.

##### 10. Common BrowserStack failures

| Symptom | Likely Cause | Fix |
|---|---|---|
| Session fails before step 1 | Bad username/access key or malformed hub URL | Recheck `appium_server_url` and URL-encode special characters |
| `appium:app` rejected | Wrong or expired `bs://...` app ID | Re-upload app and update matrix |
| Device unavailable | Device name/OS not available in your plan | Copy exact name/version from BrowserStack capability UI |
| iOS session starts but app does not open | Wrong `bundle_id` or wrong `.ipa` uploaded | Use the iOS app's real bundle identifier and matching `bs://IOS_APP_ID` |
| Android app does not open | Wrong `app_package`/`app_activity` | Use app package/activity from the APK or set a valid `appium:app` |
| Repair does not happen | Failure occurred during session startup | Fix credentials, app upload, device name, or capabilities first |

#### Sauce Labs Real Device Cloud or Virtual Devices

Use Sauce Labs when the Appium server and mobile device are hosted by Sauce. In this mode:

- Do not run local Appium.
- Do not depend on local `adb devices`.
- Upload your app to Sauce App Storage or provide an app URL that Sauce can access.
- Choose the Sauce data center endpoint that matches your account/region.

Common Sauce Appium endpoints:

```text
https://YOUR_USERNAME:YOUR_ACCESS_KEY@ondemand.us-west-1.saucelabs.com:443/wd/hub
https://YOUR_USERNAME:YOUR_ACCESS_KEY@ondemand.us-east-4.saucelabs.com:443/wd/hub
https://YOUR_USERNAME:YOUR_ACCESS_KEY@ondemand.eu-central-1.saucelabs.com:443/wd/hub
```

Set Executor-Regenerator `.env`:

```env
ENABLE_APPIUM_EXECUTION=true
APPIUM_SERVER_URL=https://YOUR_USERNAME:YOUR_ACCESS_KEY@ondemand.us-west-1.saucelabs.com:443/wd/hub
```

Then generate the Appium script with Sauce capabilities:

```json
{
  "appium_config": {
    "device_name": "Samsung Galaxy S23",
    "platform_name": "Android",
    "platform_version": "13",
    "automation_name": "UiAutomator2",
    "app_package": "your.android.package",
    "app_activity": ".MainActivity",
    "no_reset": true,
    "relaunch_before_test": true,
    "relaunch_before_step_retry": true,
    "extra_capabilities": {
      "appium:app": "storage:filename=your-app.apk",
      "sauce:options": {
        "build": "Executor-Regenerator",
        "name": "Generated Appium Test",
        "appiumVersion": "2.0.0"
      }
    }
  }
}
```

Sauce app capability options:

- `storage:<file-id>`: pin to a specific uploaded file ID.
- `storage:filename=your-app.apk`: use the latest Sauce Storage file with that exact filename.
- `https://.../your-app.apk`: use a public URL that Sauce can download.

Useful Sauce Labs docs:

- Sauce Appium real device testing: `https://docs.saucelabs.com/mobile-apps/automated-testing/appium/real-devices/`
- Sauce test configuration options: `https://docs.saucelabs.com/dev/test-configuration-options/`
- Sauce App Storage: `https://docs.saucelabs.com/mobile-apps/app-storage/`

#### Private Hosted Devices or Custom Device Farms

For any other hosted mobile provider, the pattern is the same:

```env
ENABLE_APPIUM_EXECUTION=true
APPIUM_SERVER_URL=https://YOUR_PROVIDER_APPIUM_ENDPOINT/wd/hub
```

Then provide the exact capabilities your provider expects through `appium_config` and `extra_capabilities`.

Example:

```json
{
  "appium_config": {
    "device_name": "provider-device-name-or-id",
    "platform_name": "Android",
    "platform_version": "14",
    "automation_name": "UiAutomator2",
    "app_package": "your.android.package",
    "app_activity": ".MainActivity",
    "extra_capabilities": {
      "appium:app": "provider-specific-app-reference",
      "provider:options": {
        "project": "Executor-Regenerator",
        "build": "Cloud Device Build"
      }
    }
  }
}
```

Ask the provider for:

- Appium hub URL.
- Required authentication method: URL basic auth, custom capabilities, headers, or token.
- Device naming format.
- App upload/storage reference format.
- Whether `driver.save_screenshot`, `driver.page_source`, device logs, and screen recording are supported.

#### Cloud Execution Artifacts and Regeneration Behavior

Executor-Regenerator still creates its normal ZIP artifacts for cloud Appium runs because the generated script runs locally in the executor process and talks to the remote Appium server over HTTP.

Expected local artifacts:

- `status.txt`
- `exit_code.txt`
- `started_at.txt`
- `finished_at.txt`
- `final_script.py`
- `repair_report.json`
- `success/summary.json` or `failures/summary.json`
- per-step screenshots captured with `driver.save_screenshot(...)`
- failure DOM snapshots captured with `driver.page_source`
- logs when the provider exposes them through WebDriver/Appium log APIs

Regeneration/self-healing can run when the session starts and a step fails normally:

- locator not found
- text changed
- element not visible
- timing/slow-loading UI
- assertion mismatch

Regeneration cannot repair provider/session setup problems:

- wrong BrowserStack/Sauce username or access key
- expired token
- invalid app upload reference
- app not available to the cloud provider
- unsupported device name or OS version
- provider concurrency/quota failure
- remote Appium hub unreachable
- requested capability rejected before the first step runs

In those cases, the run may still return a ZIP with startup failure details, but no useful locator regeneration can happen because there is no active page source or screenshot from the app under test.

#### Runtime Appium Device Matrix Flow

Script Generator produces one Appium script. Executor-Regenerator decides which devices to run at `/executor/appium/run` time.

For a three-device cloud run:

1. Generate `generated_appium.py` from Script Generator.
2. Build `appium_device_matrix` in Executor-Regenerator with Pixel, OnePlus, and iPhone capabilities.
3. Submit the script plus matrix to `/executor/appium/run`.
4. Executor-Regenerator runs the script separately for each selected device.
5. If one device fails, repair uses that device's `device_context.json` and reruns that same device with the patched script.
6. The final ZIP contains separate run directories under device slugs such as `pixel_7/`, `oneplus_latest/`, and `iphone_latest/`.

Field behavior:

- `appium_server_url` overrides `APPIUM_SERVER_URL` only for this execution and its repair reruns.
- `appium_device_matrix` supplies the actual Appium capabilities to use. It can be a JSON object with `devices`, a JSON object with `matrix`, a single device object, or a JSON array.
- `appium_device_filter` selects runtime devices by `label`, `slug`, or `device_name`.
- If no matrix is passed, Executor-Regenerator falls back to `APPIUM_DEVICE_MATRIX_JSON`, then `APPIUM_DEVICE_MATRIX_PATH`. Only when none of those are present does it run once using its own/environment default capabilities.

Use provider-specific device names. Do not rely on the words `latest iPhone` as a magic value unless your provider explicitly supports that. In most providers, open the device catalog, copy the newest available iPhone name and OS version, and put those exact values in `appium_device_matrix`.

#### Switching Between Remote Appium Providers

For a persistent environment switch, change `APPIUM_SERVER_URL` in Executor-Regenerator:

```env
# Private GCP Appium VM
APPIUM_SERVER_URL=http://34.46.45.187:4723/wd/hub

# BrowserStack
APPIUM_SERVER_URL=https://YOUR_USERNAME:YOUR_ACCESS_KEY@hub-cloud.browserstack.com/wd/hub

# Sauce Labs
APPIUM_SERVER_URL=https://YOUR_USERNAME:YOUR_ACCESS_KEY@ondemand.us-west-1.saucelabs.com:443/wd/hub
```

Then restart Executor-Regenerator so `.env` is reloaded. For one-off runs, prefer the `/executor/appium/run` form field `appium_server_url`; that overrides the hub URL only for that execution and its repair reruns.

The generated script still needs compatible runtime capabilities. Pass them through `appium_device_matrix` at `/executor/appium/run` time, set `APPIUM_DEVICE_MATRIX_JSON` in `.env`, or maintain them in the file referenced by `APPIUM_DEVICE_MATRIX_PATH`. A script that uses Android-only locators will still need regenerated or repaired locators for iOS if the app UI differs, but the device selection itself no longer requires regenerating the script.

### 3. Start the API Server
You can start the web server in any of the three logging format modes.

**Recommended: Pretty log format mode (colorized, emoji-enriched, aligned columns)**
```bash
python run.py --mode pretty
```

**Standard console logging mode:**
```bash
python run.py --mode console
# Or start uvicorn directly:
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**JSON structured logging mode (for production log drains like Datadog/Splunk):**
```bash
python run.py --mode json
```

**Expose to network (e.g. Docker host or team environment):**
```bash
python run.py --host 0.0.0.0 --port 8000
```

**Disable auto-reload for executor runs (avoids reload noise from script writes):**
```bash
python run.py --no-reload
```

### 4. Start Background Celery Workers
Start Celery only if you are using the optional async worker path:
```bash
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
```

### 5. Running the Complete Test Suite
Execute pytest validations:
```bash
python -m pytest -q
```

### 6. Client Invocation Examples
#### Repair Step Request (curl)
```bash
curl -X POST "http://127.0.0.1:8000/repair" \
  -H "accept: application/json" \
  -H "X-API-Key: client_sec_key" \
  -F "error_image=@tests/artifacts/screenshot.webp;type=image/webp" \
  -F "payload={
    \"step_id\": \"checkout__step_4\",
    \"step_intent\": \"click on Submit Checkout button\",
    \"original_code\": \"await page.locator('#submit').click()\",
    \"error_classification\": {
      \"type\": \"ASSERTION_TIMEOUT\"
    },
    \"error_details\": {
      \"message\": \"Timeout waiting for selector '#submit'\",
      \"failed_api\": \"page.click\",
      \"timestamp\": \"2026-06-02T13:25:41Z\"
    },
    \"artifacts\": {
      \"dom_snapshot\": \"<body><form><button id='checkout-btn'>Submit Checkout</button></form></body>\"
    }
  }"
```

#### Run Script with Auto-Healing (curl)
```bash
curl -X POST "http://127.0.0.1:8000/executor/playwright/run" \
  -H "X-API-Key: client_sec_key" \
  -F "script=@tests/scripts/failing_test.py" \
  --output result.zip
```

Then check outcome:
```bash
# Unzip the result
unzip result.zip -d result/

# Check semantic status from response headers or read status.txt
cat result/artifacts/status.txt
```

#### Run Generated Appium Script on Remote Appium Device
Before this request, make sure:
- `APPIUM_SERVER_URL` points to your GCP VM, BrowserStack, Sauce, or custom provider hub URL.
- The Appium server is reachable from the Executor-Regenerator machine.
- The request includes `appium_device_matrix`, or `.env` has `APPIUM_DEVICE_MATRIX_JSON`.
- The runtime capabilities can launch the target Android/iOS app.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/executor/appium/run" `
  -H "X-API-Key: client_sec_key" `
  -F "script=@D:\path\to\generated_appium_script.py" `
  -F "appium_server_url=http://34.46.45.187:4723/wd/hub" `
  --output appium-result.zip
```

---

## 🛠️ Developer Guide: Extending and Adding New Action Extractors

To add a new action type or extractor (e.g. `HoverActionExtractor`):

### Step 1: Define the Extracted Value or Strategy (if needed)
Update `app/models/cir.py` to support the new action type:
```python
class ActionType(str, Enum):
    click = "CLICK"
    type = "TYPE"
    hover = "HOVER"  # Add the new action type
```

### Step 2: Create the Extractor File
Create `app/services/extractors/HoverExtractor.py` extending `BaseExtractor`:
```python
from typing import Optional
import logging
from app.models.extraction import ExtractedLocator
from app.models.cir import LocatorStrategy
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("hover_extractor")

class HoverActionExtractor(BaseExtractor):
    async def extract(self, *, step_intent: str, original_code: str, error_message: str, dom_snapshot: Optional[str], **kwargs) -> Optional[ExtractedLocator]:
        self._last_step_intent = step_intent
        self._last_original_code = original_code
        self._last_dom_snapshot = dom_snapshot
        
        # Implement prompt logic and query the LLM
        prompt = f"Identify the element to HOVER over in: {step_intent}"
        # ... execute LLM and get hint ...
        
        # Verify using the Literal Guard
        if not self._literal_exists_in_sources(extracted_value):
            return None
            
        return ExtractedLocator(strategy=LocatorStrategy.text, value=extracted_value)
```

### Step 3: Register in the Factory
Update `app/services/extractors/ExtractorFactory.py` to register the new extractor:
```python
from app.services.extractors.HoverExtractor import HoverActionExtractor

class ExtractorFactory:
    _registry = {
        ActionType.click: ClickActionExtractor,
        ActionType.type: TypeActionExtractor,
        ActionType.hover: HoverActionExtractor, # Register the extractor
    }
```

---

## 🩺 Troubleshooting & Support Matrix

### Issue 1: `ImportError: cannot import name 'global_exception_handler'`
* **Cause**: Python shadowing issue where `app/core/exceptions.py` conflicted with the `app/core/exceptions/` directory.
* **Resolution**: Delete `app/core/exceptions.py` and ensure the handler is imported in `app/core/exceptions/__init__.py`.

### Issue 2: Readiness Fails Because MongoDB Is Configured but Unavailable
* **Cause**: `MONGODB_URL` is set, but the database cannot be reached. In development the repository can fall back to memory, but readiness still reports the dependency failure.
* **Resolution**: Restore MongoDB connectivity, remove `MONGODB_URL` if you intentionally want in-memory mode, or explicitly set `ALLOW_INMEMORY_DATABASE_FALLBACK=true` for non-development environments where that tradeoff is acceptable.

### Issue 3: Executor Returns `503 Executor sandbox is disabled`
* **Cause**: Framework execution routes under `/executor/{framework}/run` are protected against unsandboxed execution outside development.
* **Resolution**: Re-enable `ENABLE_SANDBOX_EXECUTION`, or in production configure `SANDBOX_USE_DOCKER=true`. Host execution in production requires `ALLOW_UNSAFE_HOST_EXECUTION_IN_PRODUCTION=true`.

### Issue 4: Pydantic Validation Error for Environment Variables
* **Cause**: Environment variables for lists (e.g. `CORS_ORIGINS`) are configured as comma-separated lists instead of JSON arrays.
* **Resolution**: Standardize configuration list fields using the custom `@field_validator` with CSV parsing fallback.

### Issue 5: `python run.py` Hangs or Fails to Start
* **Cause**: The default host `0.0.0.0` can trigger Windows Defender Firewall prompts or fail to bind depending on shell permissions. Alternatively, a zombie `python.exe` process from a previous run may still hold port 8000.
* **Resolution**:
  - Run `python run.py` — it now binds to `127.0.0.1` by default, which avoids Windows Firewall issues.
  - If port is taken: `tasklist /FI "IMAGENAME eq python.exe"` and `taskkill /PID <pid> /F`.
  - If dependencies are missing: activate the virtual environment first with `.\venv\Scripts\activate`.
  - To expose the server on the network explicitly: `python run.py --host 0.0.0.0`.

### Issue 6: Script Rejected with `403 Script rejected by sandbox`
* **Cause**: The uploaded script uses a forbidden import, function call, or attribute access.
* **Resolution**: Remove any usage of the forbidden modules, calls, or attributes listed in the [AST-Based Security Sandbox](#-deep-dive-ast-based-security-sandbox) section. Use only the allowed imports listed there.

### Issue 7: `X-Semantic-Status: failed` Even Though HTTP 200 Was Returned
* **Cause**: The executor always returns HTTP 200 with a ZIP. The test script itself failed and self-healing could not recover it.
* **Resolution**: Unzip the returned archive and inspect `final_failure_explanation.json` for the root-cause analysis, and `artifacts/<step_id>/error.txt` for the raw traceback.

---

## ✨ What's New — Enhanced Edition

This section documents all changes introduced in the `Executor-Regenrator-Enhanced` copy to achieve full compatibility with `Automation-Script-Generator-Enhanced`. The enhanced edition adds support for 11 new action types, 12 new assertion types, 3 new mobile locator strategies, and Cypress `.js` script execution.

---

### 1. Expanded CIR Models (`app/models/cir.py`)

#### ActionType — 6 → 17 values

| New Value | Description |
|---|---|
| `hover` | Mouse hover / mouseover |
| `scroll` | Page or element scroll / mobile swipe |
| `drag_drop` | Drag-and-drop from source to target |
| `upload_file` | File input / file picker |
| `keyboard` | Keyboard shortcut or key combination |
| `switch_frame` | Switch into an iframe or frame locator |
| `switch_window` | Switch to a different browser window or tab |
| `execute_script` | Execute arbitrary JavaScript |
| `double_click` | Double-click on an element |
| `right_click` | Right-click / context menu |
| `wait_for` | Explicit wait for a condition or state |

#### AssertionType — 4 → 16 values

| New Value | Description |
|---|---|
| `title_equals` | Page title exact match |
| `title_contains` | Page title partial match |
| `attribute_equals` | Element attribute exact value |
| `attribute_contains` | Element attribute partial value |
| `element_count` | Number of matching elements |
| `element_enabled` | Element is enabled (not disabled) |
| `element_disabled` | Element is disabled |
| `element_checked` | Checkbox/radio is checked |
| `element_unchecked` | Checkbox/radio is unchecked |
| `element_value` | Input field value |
| `list_contains` | List/select contains an item |
| `page_source_contains` | Raw page source text match |

#### WaitCondition — 5 → 12 values

Added: `clickable`, `presence`, `text_present`, `count_equals`, `staleness`, `network_idle`, `load_state`

#### LocatorStrategy — 12 → 15 values

Added: `ios_class_chain`, `ios_predicate_string`, `android_data_matcher`

#### New CIRAction fields (13 added)

`drag_target`, `key_combination`, `frame_locator`, `window_index`, `script_expression`, `scroll_direction`, `scroll_amount`, `file_path_to_upload`, `wait_for_condition`, `wait_for_timeout`, `attribute_name`, `expected_count`

---

### 2. Expanded Code Generator (`app/services/generator.py`)

Added 11 new action renderers — each supports all four frameworks (Playwright, Selenium, Appium, Cypress):

| Action | Playwright | Selenium | Appium | Cypress |
|---|---|---|---|---|
| `hover` | `target.hover()` | `ActionChains.move_to_element` | `mobile: swipe` | `.trigger('mouseover')` |
| `double_click` | `target.dbl_click()` | `ActionChains.double_click` | double `element.click()` | `.dblclick()` |
| `right_click` | `.click(button='right')` | `ActionChains.context_click` | `mobile: longClick` | `.rightclick()` |
| `scroll` | `mouse.wheel` / `scroll_into_view_if_needed` | `execute_script('scrollBy')` | `mobile: scroll` | `cy.scrollTo()` |
| `drag_drop` | `source.drag_to(target)` | `ActionChains.drag_and_drop` | `mobile: dragFromToForDuration` | `.drag()` |
| `upload_file` | `set_input_files(path)` | `send_keys(path)` | `send_keys(path)` | `.selectFile(path)` |
| `keyboard` | `page.keyboard.press(combo)` | `Keys.CONTROL + Keys.A` | `press_keycode(code)` | `cy.focused().type('{combo}')` |
| `switch_frame` | `page.frame_locator(sel)` | `switch_to.frame(el)` | `switch_to.frame(el)` | `cy.frameLoaded(); cy.iframe()` |
| `switch_window` | `context.pages[idx]` | `switch_to.window(handles[idx])` | `switch_to.window(handles[idx])` | comment (not natively supported) |
| `execute_script` | `page.evaluate(expr)` | `driver.execute_script(expr)` | `driver.execute_script(expr)` | `cy.window().then(w => w.eval(expr))` |
| `wait_for` | `wait_for_url/load_state/wait_for` | `WebDriverWait` | `WebDriverWait` | `.should('be.visible', {timeout})` |

Added 12 new assertion renderers in `_assert()` (Playwright), `_assert_driver()` (Selenium/Appium), and `_assert_cypress()` (Cypress) covering all 16 `AssertionType` values.

Added 3 new Appium locator strategies in `_locator_appium()`:
- `ios_class_chain` → `AppiumBy.IOS_CLASS_CHAIN`
- `ios_predicate_string` → `AppiumBy.IOS_PREDICATE_STRING`
- `android_data_matcher` → `AppiumBy.ANDROID_DATA_MATCHER`

---

### 3. CIR Validator (`app/services/validator.py`)

**Before:** The `else` clause in `_validate_action()` raised `CIRValidationError("Unsupported action_type")` for any of the 11 new types, crashing the repair pipeline. The assertion validator similarly raised for any assertion type beyond the original 4.

**After:**
- `hover`, `double_click`, `right_click`, `drag_drop` — validated: `target required`
- `keyboard` — validated: `key_combination required`
- `execute_script` — validated: `script_expression required`
- `scroll`, `upload_file`, `switch_frame`, `switch_window`, `wait_for` — pass-through (all fields optional; generator handles defaults)
- `title_equals`, `title_contains`, `page_source_contains` — validated: `expected_value required`, no target
- `attribute_equals`, `attribute_contains`, `element_value`, `list_contains` — pass-through (modifier fills missing fields)
- `element_count` — pass-through (expected_value holds count string)
- `element_enabled`, `element_disabled`, `element_checked`, `element_unchecked` — validated: `expected_value must be None`

---

### 4. CIR Builder (`app/services/cir_builder.py`)

**Before:** 6 `if/elif` branches; any new action type hit the `FINAL SAFETY GATE` and raised `StepNotRepairableError`.

**After:** 15 branches added for the 11 new action types:

| Action | Strategy |
|---|---|
| `hover`, `double_click`, `right_click` | Delegates to `ClickActionExtractor` (same locator logic as click) |
| `drag_drop` | `ClickActionExtractor` for source; `drag_target` left `None` for modifier |
| `keyboard` | Regex extracts `ctrl+`, `cmd+`, `alt+`, `shift+` combos from intent/code |
| `scroll` | Regex extracts `up/down/left/right` from intent; defaults to `down` with 300px |
| `upload_file` | `ClickActionExtractor` for target; regex extracts file path from quoted strings |
| `switch_frame` | Regex extracts frame selector from original code |
| `switch_window` | Regex extracts digit from intent; defaults to index 1 |
| `execute_script` | Regex extracts expression from `execute_script(...)` or `evaluate(...)` call |
| `wait_for` | Regex infers condition from intent keywords; defaults to `visible` / 5000ms |

---

### 5. LLM Action Classifier (`app/services/llm_classifier.py`)

**Before:** 7 entries in `ALLOWED_LABELS`; any new LLM label fell through to `ActionType.click` (the safe default).

**After:**
- `ALLOWED_LABELS` expanded to 30 entries (handles all variants: `double_click`, `doubleclick`, `dblclick`, `drag`, `dragdrop`, etc.)
- 11 new pattern lists added: `DOUBLE_CLICK_PATTERNS`, `RIGHT_CLICK_PATTERNS`, `HOVER_PATTERNS`, `DRAG_DROP_PATTERNS`, `KEYBOARD_PATTERNS`, `UPLOAD_PATTERNS`, `SCROLL_PATTERNS`, `SWITCH_FRAME_PATTERNS`, `SWITCH_WINDOW_PATTERNS`, `EXECUTE_SCRIPT_PATTERNS`, `WAIT_FOR_PATTERNS`
- New patterns are checked **before** existing `CLICK_PATTERNS`/`TYPE_PATTERNS` to prevent false-positive matches (e.g., "double click" → `double_click` not `click`)
- `SCROLL_PATTERNS` is checked after `TYPE_PATTERNS` to avoid false positives

---

### 6. Assert Extractor (`app/services/extractors/AssertExtractor.py`)

**Before:** `_normalize_llm_hint()` only handled `url_contains:` and `element_visible` / `element_visible:<locator>`.

**After:** Handles all 16 `AssertionType` values with typed prefix parsing:

| LLM hint format | Produces |
|---|---|
| `title_equals:<value>` | `AssertionType.title_equals`, no locator |
| `title_contains:<value>` | `AssertionType.title_contains`, no locator |
| `page_source_contains:<value>` | `AssertionType.page_source_contains`, no locator |
| `text_equals:<expected>[:<locator>]` | `AssertionType.text_equals` |
| `text_contains:<expected>[:<locator>]` | `AssertionType.text_contains` |
| `element_enabled:<locator>` | `AssertionType.element_enabled`, no expected |
| `element_disabled:<locator>` | `AssertionType.element_disabled`, no expected |
| `element_checked:<locator>` | `AssertionType.element_checked`, no expected |
| `element_unchecked:<locator>` | `AssertionType.element_unchecked`, no expected |
| `element_value:<expected>:<locator>` | `AssertionType.element_value` |
| `list_contains:<expected>:<locator>` | `AssertionType.list_contains` |
| `attribute_equals:<expected>:<locator>` | `AssertionType.attribute_equals` |
| `attribute_contains:<expected>:<locator>` | `AssertionType.attribute_contains` |
| `element_count:<count>:<locator>` | `AssertionType.element_count` |

---

### 7. Base Extractor — Mobile Locators (`app/services/extractors/BaseExtractor.py`)

**Before:** `_appium_locator_from_hint()` had 5 patterns — `id`, `accessibility_id`, `uiautomator`, `xpath`, `text`.

**After:** 3 new patterns added at the end of the `patterns` tuple:
- `ios_class_chain(...)` → `LocatorStrategy.ios_class_chain`
- `ios_predicate_string(...)` → `LocatorStrategy.ios_predicate_string`
- `android_data_matcher(...)` → `LocatorStrategy.android_data_matcher`

These use `must_exist=False` (not validated against intent/DOM since they are structural iOS/Android selectors, not visible text).

---

### 8. Cypress `.js` Script Support (`app/routes/executor_routes/common.py`)

**Before:** Line 163 rejected any file not ending with `.py` with HTTP 400.

**After:** Both `.py` and `.js` extensions are accepted. This unblocks Cypress scripts generated by `Automation-Script-Generator-Enhanced`, which now emits `.js` for Cypress.

`_ensure_final_script()` updated: the `final_script.py` hardcode is replaced with `final_script{script_path.suffix}`, making it emit `final_script.py` for Python frameworks and `final_script.js` for Cypress.

---

### 9. Framework-Aware Repair Response (`app/routes/repair.py`)

**Before:** `Content-Disposition` always returned `{step_id}_repaired.py` and `text/x-python` media type.

**After:** `_success_response()` accepts a `framework` parameter:
- Cypress → `{step_id}_repaired.js`, `text/javascript`
- All others → `{step_id}_repaired.py`, `text/x-python`

Both call sites (`DRY_RUN_MODE` and normal success path) now pass `framework=request.framework`.

---

### 10. Expanded LLM Prompts (`app/core/prompts.py`)

#### `build_action_classifier_prompt`

**Before:** `"Return exactly one word: navigate, click, type, select, assert, or dialog."`

**After:** Lists all 17 action types with specific disambiguation rules for the 11 new ones (hover vs click, keyboard vs click, wait_for vs assert, etc.).

#### `build_assert_extractor_prompt`

**Before:** `"Return one line only: none, url_contains:<fragment>, element_visible, or element_visible:<locator>."`

**After:** Full 18-line format menu covering all 16 assertion types with format examples for each.

#### `build_click_extractor_prompt` (Appium path)

**Before:** Blocked `ios_class_chain`, `ios_predicate_string`, `android_data_matcher` with the rule `"Do not return role, label, placeholder, css, or test_id for Appium."`

**After:** Adds `ios_class_chain`, `ios_predicate_string`, `android_data_matcher` to the supported Appium strategies list with a guidance note on when to prefer them.

---

### 11. Atomic Normalizer — Keyboard Focus (`app/services/atomic_normalizer.py`)

**Before:** `FOCUS_REQUIRED_ACTIONS = {ActionType.type}` only.

**After:** `FOCUS_REQUIRED_ACTIONS = {ActionType.type, ActionType.keyboard}`.

This means a `keyboard` action with an explicit target is automatically rewritten into:
1. `click(target)` — establishes focus
2. `keyboard(:focus)` — sends keys to the active element

This mirrors how the normalizer handles `type` actions and ensures keyboard shortcuts reach the correct element.

---

### Summary Table

| File | Change |
|---|---|
| `app/models/cir.py` | ActionType 6→17, AssertionType 4→16, WaitCondition 5→12, LocatorStrategy 12→15, 13 new CIRAction fields |
| `app/services/generator.py` | 11 new action renderers (×4 frameworks), 12 new assertion renderers, 3 new Appium locator strategies |
| `app/services/validator.py` | Validates all 17 action types and 16 assertion types; no longer raises on new types |
| `app/services/cir_builder.py` | 15 new build paths for 11 new action types |
| `app/services/llm_classifier.py` | ALLOWED_LABELS 7→30, 11 new heuristic pattern lists |
| `app/services/extractors/AssertExtractor.py` | Handles all 16 assertion types with typed prefix parsing |
| `app/services/extractors/BaseExtractor.py` | 3 new mobile locator patterns (ios_class_chain, ios_predicate_string, android_data_matcher) |
| `app/routes/executor_routes/common.py` | Accepts `.py` and `.js`; `final_script.py` → `final_script{ext}` |
| `app/routes/repair.py` | Framework-aware filename and media type in repair response |
| `app/core/prompts.py` | Classifier prompt covers 17 action types; assert prompt covers 16 assertion types; Appium click prompt allows mobile locators |
| `app/services/atomic_normalizer.py` | `keyboard` added to `FOCUS_REQUIRED_ACTIONS` |

