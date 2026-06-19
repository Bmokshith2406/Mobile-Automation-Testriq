import csv
import copy
import io
import json
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.core.config import settings
from app.core.logging import request_logger_adapter
from app.core.metrics import REQUEST_COUNT, REQUEST_DURATION
from app.core.resilience import record_success, retry_call
from app.db.mongo import get_execution_history_collection
from app.services.http_client import get_client, get_semaphore


MATCH_THRESHOLD = 85.0
STEP_METHOD_PATTERN = r"^_step_\d+_[a-f0-9]{12}$"


class PipelineService:
    SUPPORTED_FRAMEWORKS = {"playwright", "selenium", "cypress", "appium"}
    FRAMEWORK_LANGUAGE_MAP = {
        "playwright": "python",
        "selenium": "python",
        "appium": "python",
        "cypress": "javascript",
    }

    @staticmethod
    def _normal_headers() -> Dict[str, str]:
        return {"X-API-Key": settings.TESTCASES_RAG_API_KEY}

    @staticmethod
    def _admin_headers() -> Dict[str, str]:
        return {"X-Admin-API-Key": settings.TESTCASES_RAG_ADMIN_API_KEY}

    @staticmethod
    def _clean_optional_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _clean_optional_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: PipelineService._clean_optional_value(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, list):
            return [
                PipelineService._clean_optional_value(item)
                for item in value
                if item is not None
            ]
        return value

    @staticmethod
    def _shape_matched_script_for_generator(matched_script: Optional[dict]) -> Optional[Dict[str, Any]]:
        if not isinstance(matched_script, dict):
            return None
        return PipelineService._clean_optional_mapping(
            {
                "language": matched_script.get("language"),
                "framework": matched_script.get("framework"),
                "raw_code": matched_script.get("raw_code"),
            }
        )

    @staticmethod
    def _shape_appium_config_for_generator(appium_config: Optional[dict]) -> Optional[Dict[str, Any]]:
        if not isinstance(appium_config, dict):
            return None
        return PipelineService._clean_optional_value(copy.deepcopy(appium_config))

    @staticmethod
    def _shape_prerequisite_for_generator(prerequisite: dict) -> Dict[str, Any]:
        shaped = {
            "prerequisite_id": prerequisite.get("prerequisite_id"),
            "description": prerequisite.get("description"),
            "matched_script": PipelineService._shape_matched_script_for_generator(prerequisite.get("matched_script")),
        }
        return PipelineService._clean_optional_mapping(shaped)

    @staticmethod
    def _shape_step_for_generator(step: dict) -> Dict[str, Any]:
        shaped = {
            "step_id": step.get("step_id"),
            "description": step.get("description"),
            "expected_outcome": step.get("expected_outcome"),
            "matched_script": PipelineService._shape_matched_script_for_generator(step.get("matched_script")),
        }
        return PipelineService._clean_optional_mapping(shaped)

    @staticmethod
    def build_generator_payload(testcase_payload: dict) -> Dict[str, Any]:
        """Shape Orchestrator payload into Automation-Script-Generator's strict TestCase model."""
        shaped = {
            "test_case_id": testcase_payload.get("test_case_id"),
            "description": testcase_payload.get("description"),
            "target_framework": testcase_payload.get("target_framework"),
            "appium_config": PipelineService._shape_appium_config_for_generator(
                testcase_payload.get("appium_config")
            ),
            "prerequisites": [
                PipelineService._shape_prerequisite_for_generator(prerequisite)
                for prerequisite in testcase_payload.get("prerequisites", [])
            ],
            "steps": [
                PipelineService._shape_step_for_generator(step)
                for step in testcase_payload.get("steps", [])
            ],
        }
        return PipelineService._clean_optional_mapping(shaped)

    @staticmethod
    def build_generator_request(testcase_payload: dict, request_id: str) -> Dict[str, Any]:
        body = PipelineService._clean_optional_mapping(
            {
                "test_case": PipelineService.build_generator_payload(testcase_payload),
                "webhook_url": testcase_payload.get("webhook_url"),
            }
        )
        return {
            "url": f"{settings.GENERATOR_URL.rstrip('/')}/generate/",
            "headers": {
                "X-API-Key": settings.GENERATOR_API_KEY,
                "X-Request-ID": request_id,
                "Accept": "application/octet-stream, text/plain, text/x-python",
                "Content-Type": "application/json",
            },
            "json": body,
            "timeout": settings.DOWNSTREAM_TIMEOUT_SECONDS,
        }

    @staticmethod
    def build_testcases_search_request(testcase_payload: dict) -> Dict[str, Any]:
        return {
            "url": f"{settings.TESTCASES_RAG_URL.rstrip('/')}/api/search",
            "headers": {**PipelineService._normal_headers(), "Content-Type": "application/json"},
            "json": PipelineService._search_query_from_payload(testcase_payload),
            "timeout": 30.0,
        }

    @staticmethod
    def build_executor_request(script_file, request_id: str) -> Dict[str, Any]:
        return PipelineService.build_framework_executor_request(
            script_file,
            request_id,
            framework="playwright",
            testcase_payload=None,
        )

    @staticmethod
    def build_framework_executor_request(
        script_file,
        request_id: str,
        *,
        framework: Optional[str],
        testcase_payload: Optional[dict],
    ) -> Dict[str, Any]:
        framework_name = PipelineService._normalize_framework(framework)
        request_spec = {
            "url": f"{settings.EXECUTOR_URL.rstrip('/')}/executor/{framework_name}/run",
            "headers": {"X-API-Key": settings.EXECUTOR_API_KEY, "X-Request-ID": request_id},
            "files": {"script": ("generated_script.py", script_file, "text/x-python")},
            "timeout": settings.DOWNSTREAM_TIMEOUT_SECONDS,
        }

        if framework_name == "appium":
            data = PipelineService._appium_executor_form_data(testcase_payload or {})
            if data:
                request_spec["data"] = data

        return request_spec

    @staticmethod
    def _normalize_framework(framework: Optional[str]) -> str:
        framework_name = (framework or "playwright").strip().lower()
        if framework_name not in PipelineService.SUPPORTED_FRAMEWORKS:
            return "playwright"
        return framework_name

    @staticmethod
    def _normalize_optional_framework(framework: Optional[str]) -> Optional[str]:
        raw_value = str(framework or "").strip().lower()
        if not raw_value:
            return None
        for candidate in PipelineService.SUPPORTED_FRAMEWORKS:
            if raw_value == candidate or candidate in raw_value:
                return candidate
        return None

    @staticmethod
    def _normalize_optional_language(language: Optional[str]) -> Optional[str]:
        raw_value = str(language or "").strip().lower()
        if raw_value in {"python", "py"}:
            return "python"
        if raw_value in {"javascript", "js", "typescript", "ts"}:
            return "javascript"
        return None

    @staticmethod
    def _infer_framework_from_code(script_content: Optional[str]) -> Optional[str]:
        text = str(script_content or "").strip().lower()
        if not text:
            return None

        if any(token in text for token in ("cy.", "cypress.", "describe(", "it(", "beforeeach(", "aftereach(")):
            return "cypress"
        if any(token in text for token in ("from appium", "import appium", "appiumby", "appiumoptions", "appium:")):
            return "appium"
        if any(token in text for token in ("from selenium", "import selenium", "webdriverwait", "expected_conditions", "webdriver.")):
            return "selenium"
        if any(token in text for token in ("from playwright", "import playwright", "async_playwright", "locator(", "page.")):
            return "playwright"
        return None

    @staticmethod
    def _infer_language_from_code(script_content: Optional[str], framework: Optional[str] = None) -> Optional[str]:
        text = str(script_content or "").strip().lower()
        if text:
            if any(token in text for token in ("async def ", "def ", "from ", "import ")):
                return "python"
            if any(token in text for token in ("const ", "let ", "var ", "function ", "=>", "describe(", "it(", "cy.")):
                return "javascript"

        normalized_framework = PipelineService._normalize_optional_framework(framework)
        if normalized_framework:
            return PipelineService.FRAMEWORK_LANGUAGE_MAP.get(normalized_framework)
        return None

    @staticmethod
    def resolve_script_provenance(
        testcase_payload: Optional[dict],
        script_content: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        payload = testcase_payload if isinstance(testcase_payload, dict) else {}
        structured = payload.get("structured_test_case")
        structured_payload = structured if isinstance(structured, dict) else {}

        framework = None
        for candidate in (
            payload.get("script_framework"),
            structured_payload.get("script_framework"),
            payload.get("target_framework"),
            structured_payload.get("target_framework"),
            payload.get("Platform"),
            payload.get("platform"),
        ):
            framework = PipelineService._normalize_optional_framework(candidate)
            if framework:
                break
        if not framework:
            framework = PipelineService._infer_framework_from_code(script_content)

        language = None
        for candidate in (
            payload.get("script_language"),
            structured_payload.get("script_language"),
        ):
            language = PipelineService._normalize_optional_language(candidate)
            if language:
                break
        if not language:
            language = PipelineService._infer_language_from_code(script_content, framework)

        return framework, language

    @staticmethod
    def _appium_executor_form_data(testcase_payload: dict) -> Dict[str, str]:
        explicit_matrix = testcase_payload.get("appium_device_matrix")
        derived_matrix = None
        if explicit_matrix is None or explicit_matrix == "":
            appium_config = testcase_payload.get("appium_config")
            if isinstance(appium_config, dict):
                devices = appium_config.get("devices")
                if isinstance(devices, list) and devices:
                    derived_matrix = {"devices": copy.deepcopy(devices)}

        data: Dict[str, str] = {}
        values = {
            "appium_server_url": testcase_payload.get("appium_server_url"),
            "appium_device_filter": testcase_payload.get("appium_device_filter"),
            "appium_device_matrix": (
                explicit_matrix if explicit_matrix is not None and explicit_matrix != "" else derived_matrix
            ),
        }
        for key, value in values.items():
            if value is None or value == "":
                continue
            data[key] = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        return data

    @staticmethod
    def build_report_generator_request(zip_file, request_id: str) -> Dict[str, Any]:
        return {
            "url": f"{settings.REPORTER_URL.rstrip('/')}/api/v1/generate-report",
            "headers": {"X-API-Key": settings.REPORTER_API_KEY, "X-Request-ID": request_id, "Accept": "text/html"},
            "files": {"file": ("execution_artifacts.zip", zip_file, "application/zip")},
            "timeout": settings.DOWNSTREAM_TIMEOUT_SECONDS,
        }

    @staticmethod
    def build_reports_rag_upload_request(html_output: str, testcase_name: str, request_id: str) -> Dict[str, Any]:
        return {
            "url": f"{settings.REPORTS_RAG_URL.rstrip('/')}/v1/api/reports/upload",
            "headers": {"X-API-Key": settings.REPORTS_RAG_API_KEY, "X-Request-ID": request_id},
            "data": {"name": testcase_name or "Automation Report"},
            "files": {"file": ("report.html", html_output.encode("utf-8"), "text/html")},
        }

    @staticmethod
    def build_testcases_ingest_request(
        final_script_content: str,
        testcase_payload: dict,
        canonical_testcase_id: str,
    ) -> Dict[str, Any]:
        normalized = PipelineService.normalize_testcase_for_rag(
            testcase_payload,
            canonical_testcase_id,
            script_content=final_script_content,
        )
        return {
            "url": f"{settings.TESTCASES_RAG_URL.rstrip('/')}/api/testcases/ingest-full",
            "headers": PipelineService._normal_headers(),
            "data": {"testcase_json": json.dumps(normalized)},
            "files": {"file": ("final_script.py", final_script_content.encode("utf-8"), "text/x-python")},
        }

    @staticmethod
    def build_testcases_sync_request(
        final_script_content: str,
        canonical_testcase_id: str,
        testcase_payload: Optional[dict] = None,
    ) -> Dict[str, Any]:
        request_spec = {
            "url": f"{settings.TESTCASES_RAG_URL.rstrip('/')}/api/testcases/{canonical_testcase_id}/sync-script",
            "headers": PipelineService._normal_headers(),
            "files": {"file": ("final_script.py", final_script_content.encode("utf-8"), "text/x-python")},
        }
        if testcase_payload is not None:
            request_spec["data"] = {
                "testcase_json": json.dumps(
                    PipelineService.normalize_testcase_for_rag(
                        testcase_payload,
                        canonical_testcase_id,
                        script_content=final_script_content,
                    )
                )
            }
        return request_spec

    @staticmethod
    def build_extractor_request(final_script_content: str) -> Dict[str, Any]:
        return {
            "url": f"{settings.EXTRACTOR_URL.rstrip('/')}/extract/",
            "headers": {"X-API-Key": settings.EXTRACTOR_API_KEY},
            "data": {"include_method_name_pattern": STEP_METHOD_PATTERN},
            "files": {"file": ("final_script.py", final_script_content.encode("utf-8"), "text/x-python")},
        }

    @staticmethod
    def build_methodsrag_upload_request(
        csv_bytes: bytes,
        *,
        framework: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        request_spec = {
            "url": f"{settings.METHODS_RAG_URL.rstrip('/')}/api/upload-methods",
            "headers": {"X-API-Key": settings.METHODS_RAG_API_KEY},
            "files": {"file": ("methods.csv", csv_bytes, "text/csv")},
        }
        data = PipelineService._clean_optional_mapping(
            {
                "framework": PipelineService._normalize_optional_framework(framework),
                "language": PipelineService._normalize_optional_language(language),
            }
        )
        if data:
            request_spec["data"] = data
        return request_spec

    @staticmethod
    async def get_testcase_with_history(testcase_id: str) -> Dict[str, Any]:
        """Fetch a testcase from TestCasesRAG plus report history from Orchestrator DB."""
        client = await get_client()
        url = f"{settings.TESTCASES_RAG_URL.rstrip('/')}/api/get-by-id/{testcase_id}"

        resp = await client.get(url, headers=PipelineService._admin_headers(), timeout=10.0)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Test case not found in TestCasesRAG")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Error fetching test case")

        history = await get_execution_history_collection().find_one({"_id": testcase_id})
        return {
            "testcase": resp.json().get("test_case"),
            "execution_history": history.get("reports", []) if history else [],
        }

    @staticmethod
    async def get_report_html(report_id: str) -> str:
        """Fetch HTML content of a report from ReportsRAG."""
        client = await get_client()
        url = f"{settings.REPORTS_RAG_URL.rstrip('/')}/v1/api/reports/download/{report_id}"
        headers = {"X-API-Key": settings.REPORTS_RAG_API_KEY}

        resp = await client.get(url, headers=headers, timeout=10.0)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Report not found in ReportsRAG")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Error fetching report")
        return resp.text

    @staticmethod
    def build_structured_testcase_snapshot(testcase_payload: dict) -> dict:
        framework = testcase_payload.get("target_framework")
        script_framework, script_language = PipelineService.resolve_script_provenance(testcase_payload)
        return PipelineService._clean_optional_mapping(
            {
                "test_case_id": testcase_payload.get("test_case_id"),
                "description": testcase_payload.get("description"),
                "feature": testcase_payload.get("feature"),
                "target_framework": PipelineService._normalize_framework(framework) if framework else None,
                "script_framework": script_framework,
                "script_language": script_language,
                "appium_config": PipelineService._shape_appium_config_for_generator(
                    testcase_payload.get("appium_config")
                ),
                "appium_server_url": testcase_payload.get("appium_server_url"),
                "appium_device_filter": testcase_payload.get("appium_device_filter"),
                "appium_device_matrix": PipelineService._clean_optional_value(
                    copy.deepcopy(testcase_payload.get("appium_device_matrix"))
                )
                if testcase_payload.get("appium_device_matrix") is not None
                else None,
                "prerequisites": [
                    PipelineService._shape_prerequisite_for_generator(prerequisite)
                    for prerequisite in testcase_payload.get("prerequisites", [])
                ],
                "steps": [
                    PipelineService._shape_step_for_generator(step)
                    for step in testcase_payload.get("steps", [])
                ],
            }
        )

    @staticmethod
    def normalize_testcase_for_rag(
        testcase_payload: dict,
        canonical_id: Optional[str] = None,
        *,
        script_content: Optional[str] = None,
    ) -> dict:
        """Translate the generator testcase model to TestCasesRAG's Title Case document shape."""
        tc_id = (
            testcase_payload.get("test_case_id")
            or testcase_payload.get("Test Case ID")
            or testcase_payload.get("id")
            or canonical_id
            or ""
        )
        feature = testcase_payload.get("feature") or testcase_payload.get("Feature") or "General"
        description = (
            testcase_payload.get("description")
            or testcase_payload.get("Test Case Description")
            or testcase_payload.get("Description")
            or "No description provided."
        )
        platform = (
            testcase_payload.get("target_framework")
            or testcase_payload.get("Platform")
            or testcase_payload.get("platform")
        )
        script_framework, script_language = PipelineService.resolve_script_provenance(
            testcase_payload,
            script_content=script_content,
        )

        prereqs = testcase_payload.get("prerequisites") or testcase_payload.get("Pre-requisites") or []
        if isinstance(prereqs, list):
            prereq_lines = []
            for prereq in prereqs:
                desc = prereq.get("description", "") if isinstance(prereq, dict) else str(prereq)
                if desc:
                    prereq_lines.append(f"- {desc}")
            prereqs_str = "\n".join(prereq_lines)
        else:
            prereqs_str = str(prereqs)

        steps = testcase_payload.get("steps") or testcase_payload.get("Steps") or []
        if isinstance(steps, list):
            step_lines = []
            for idx, step in enumerate(steps):
                if isinstance(step, dict):
                    desc = step.get("description") or ""
                    expected = step.get("expected_outcome") or step.get("expectedOutcome") or ""
                else:
                    desc = str(step)
                    expected = ""

                if desc:
                    line = f"Step {idx + 1}: {desc}"
                    if expected:
                        line += f" -> Expected: {expected}"
                    step_lines.append(line)
            steps_str = "\n\n".join(step_lines)
        else:
            steps_str = str(steps)

        normalized = {
            "Test Case ID": tc_id,
            "Feature": feature,
            "Test Case Description": description,
            "Pre-requisites": prereqs_str,
            "Steps": steps_str,
            "Platform": platform,
            "script_framework": script_framework,
            "script_language": script_language,
            "structured_test_case": PipelineService.build_structured_testcase_snapshot(testcase_payload),
        }
        if canonical_id:
            normalized["_id"] = canonical_id
        return normalized

    @staticmethod
    def resolve_linked_script_id(payload: Optional[dict]) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        for key in ("script_id", "playwright_script_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _legacy_steps_from_document(doc: dict) -> list[dict]:
        import re

        steps_list = []
        raw_steps = doc.get("Steps") or doc.get("steps") or ""
        if isinstance(raw_steps, list):
            for idx, item in enumerate(raw_steps):
                if isinstance(item, dict):
                    steps_list.append(
                        {
                            "step_id": item.get("step_id") or f"step_{idx + 1}",
                            "description": item.get("description") or f"Step {idx + 1}",
                            "expected_outcome": item.get("expected_outcome") or item.get("expectedOutcome"),
                        }
                    )
                else:
                    steps_list.append(
                        {
                            "step_id": f"step_{idx + 1}",
                            "description": str(item),
                        }
                    )
        elif isinstance(raw_steps, str):
            lines = [line.strip() for line in re.split(r"\n\n+|\n", raw_steps) if line.strip()]
            for idx, line in enumerate(lines):
                cleaned = re.sub(r"^step\s*\d+\s*:\s*", "", line, flags=re.IGNORECASE).strip()
                desc = cleaned
                outcome = None
                if "-> Expected:" in cleaned:
                    desc, outcome = [part.strip() for part in cleaned.split("-> Expected:", 1)]
                elif "-> expected:" in cleaned:
                    desc, outcome = [part.strip() for part in cleaned.split("-> expected:", 1)]
                steps_list.append(
                    {
                        "step_id": f"step_{idx + 1}",
                        "description": desc or f"Execute step {idx + 1}",
                        "expected_outcome": outcome,
                    }
                )

        if steps_list:
            return steps_list

        return [
            {
                "step_id": "step_1",
                "description": doc.get("Test Case Description")
                or doc.get("description")
                or "Execute test case steps",
            }
        ]

    @staticmethod
    def _legacy_prerequisites_from_document(doc: dict) -> list[dict]:
        import re

        prereqs_list = []
        raw_prereqs = doc.get("Pre-requisites") or doc.get("prerequisites") or ""
        if isinstance(raw_prereqs, list):
            for idx, item in enumerate(raw_prereqs):
                if isinstance(item, dict):
                    prereqs_list.append(
                        {
                            "prerequisite_id": item.get("prerequisite_id") or f"prereq_{idx + 1}",
                            "description": item.get("description") or f"Prerequisite {idx + 1}",
                        }
                    )
                else:
                    prereqs_list.append(
                        {
                            "prerequisite_id": f"prereq_{idx + 1}",
                            "description": str(item),
                        }
                    )
        elif isinstance(raw_prereqs, str):
            lines = [line.strip() for line in raw_prereqs.split("\n") if line.strip()]
            for idx, line in enumerate(lines):
                cleaned = re.sub(r"^[-\*\+\s]+", "", line).strip()
                if cleaned:
                    prereqs_list.append(
                        {
                            "prerequisite_id": f"prereq_{idx + 1}",
                            "description": cleaned,
                        }
                    )

        return prereqs_list

    @staticmethod
    def rebuild_testcase_payload_from_document(doc: dict, testcase_id: str) -> dict:
        structured = doc.get("structured_test_case")
        if isinstance(structured, dict):
            payload = copy.deepcopy(structured)
            if not isinstance(payload.get("prerequisites"), list):
                payload["prerequisites"] = PipelineService._legacy_prerequisites_from_document(doc)
            if not isinstance(payload.get("steps"), list) or not payload.get("steps"):
                payload["steps"] = PipelineService._legacy_steps_from_document(doc)
        else:
            payload = {
                "prerequisites": PipelineService._legacy_prerequisites_from_document(doc),
                "steps": PipelineService._legacy_steps_from_document(doc),
            }

        payload["test_case_id"] = (
            payload.get("test_case_id")
            or doc.get("Test Case ID")
            or doc.get("test_case_id")
            or testcase_id
        )
        payload["description"] = (
            payload.get("description")
            or doc.get("Test Case Description")
            or doc.get("description")
            or "Run automated pipeline"
        )
        payload["feature"] = payload.get("feature") or doc.get("Feature") or doc.get("feature") or "General"
        payload["script_framework"] = payload.get("script_framework") or doc.get("script_framework")
        payload["script_language"] = payload.get("script_language") or doc.get("script_language")

        framework = payload.get("target_framework") or doc.get("Platform") or doc.get("platform")
        if isinstance(framework, str):
            framework = framework.strip().lower()
            if framework not in PipelineService.SUPPORTED_FRAMEWORKS:
                framework = "playwright"
        else:
            framework = "playwright"
        payload["target_framework"] = framework
        payload["_id"] = testcase_id
        return payload

    @staticmethod
    def _search_query_from_payload(testcase_payload: dict) -> Dict[str, Any]:
        description = (
            testcase_payload.get("description")
            or testcase_payload.get("Test Case Description")
            or testcase_payload.get("Description")
            or ""
        )
        return {
            "query": str(description).strip() or "New default test case query",
        }

    @staticmethod
    async def _search_existing_testcase(testcase_payload: dict, req_logger) -> Optional[Dict[str, Any]]:
        client = await get_client()
        request_spec = PipelineService.build_testcases_search_request(testcase_payload)

        req_logger.info("went to testcase rag for search")
        try:
            resp = await client.post(
                request_spec["url"],
                headers=request_spec["headers"],
                json=request_spec["json"],
                timeout=request_spec["timeout"],
            )
            req_logger.info("done with testcase rag search")
            if resp.status_code != 200:
                req_logger.warning("TestCasesRAG search returned %s: %s", resp.status_code, resp.text)
                return None

            results = resp.json().get("results", [])
            if not results:
                return None

            best = results[0]
            probability = float(best.get("probability") or 0.0)
            return best if probability > MATCH_THRESHOLD else None
        except Exception as exc:
            req_logger.warning("Semantic search failed, treating testcase as new: %s", exc)
            return None

    @staticmethod
    async def _fetch_script(script_id: str, req_logger=None) -> str:
        client = await get_client()
        base_url = settings.TESTCASES_RAG_URL.rstrip("/")
        req_logger = req_logger or request_logger_adapter("fetch-script")
        req_logger.info("went to testcase rag to fetch script %s", script_id)

        if settings.TESTCASES_RAG_ADMIN_API_KEY:
            admin_url = f"{base_url}/api/get-script/{script_id}"
            resp = await client.get(admin_url, headers=PipelineService._admin_headers(), timeout=10.0)
            if resp.status_code == 200:
                req_logger.info("done fetching script %s from admin endpoint", script_id)
                return resp.json().get("code", "")
            if resp.status_code != 404:
                resp.raise_for_status()

        public_url = f"{base_url}/api/scripts/{script_id}"
        resp = await client.get(public_url, headers=PipelineService._normal_headers(), timeout=10.0)
        if resp.status_code == 404:
            req_logger.info("done fetching script %s (not found)", script_id)
            return ""
        resp.raise_for_status()
        payload = resp.json()
        raw_script = payload.get("script") or ""
        req_logger.info("done fetching script %s from public endpoint", script_id)
        if isinstance(raw_script, str):
            code = raw_script.replace("python\\n", "").replace("python\n", "")
            if "\n" not in code and "\\n" in code:
                code = code.replace("\\n", "\n")
            elif code.count("\n") < 5 and "\\n" in code:
                code = code.replace("\\n", "\n")
            return code.strip()
        return str(raw_script)

    @staticmethod
    async def _generate_script(testcase_payload: dict, script_path: Path, request_id: str, req_logger) -> None:
        client = await get_client()
        request_spec = PipelineService.build_generator_request(testcase_payload, request_id)

        req_logger.info("Calling Automation-Script-Generator")
        req_logger.info("went to automation script generator")
        async with client.stream(
            "POST",
            request_spec["url"],
            headers=request_spec["headers"],
            json=request_spec["json"],
            timeout=request_spec["timeout"],
        ) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise HTTPException(
                    status_code=500,
                    detail=f"Generator Error {resp.status_code}: {text.decode(errors='ignore')}",
                )

            with open(script_path, "wb") as script_file:
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        script_file.write(chunk)
        req_logger.info("done with automation script generator")

    @staticmethod
    async def _execute_script(
        script_path: Path,
        zip_path: Path,
        request_id: str,
        req_logger,
        *,
        framework: Optional[str],
        testcase_payload: Optional[dict],
    ) -> Dict[str, Any]:
        client = await get_client()
        metadata = {
            "executor_status": "unknown",
            "executor_run_id": "",
            "executor_duration": "",
            "executor_artifact_kind": "single_run",
            "executor_matrix_run_count": None,
            "executor_failed_step_index": None,
        }

        async def call_executor() -> str:
            req_logger.info("Calling Executor-Regenrator")
            framework_name = PipelineService._normalize_framework(framework)
            req_logger.info("went to executor regenerator | framework=%s", framework_name)

            with open(script_path, "rb") as script_file:
                request_spec = PipelineService.build_framework_executor_request(
                    script_file,
                    request_id,
                    framework=framework_name,
                    testcase_payload=testcase_payload,
                )
                async with client.stream(
                    "POST",
                    request_spec["url"],
                    headers=request_spec["headers"],
                    data=request_spec.get("data"),
                    files=request_spec["files"],
                    timeout=request_spec["timeout"],
                ) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        raise HTTPException(
                            status_code=500,
                            detail=f"Executor Error {resp.status_code}: {text.decode(errors='ignore')}",
                        )

                    metadata["executor_status"] = resp.headers.get("X-Semantic-Status", "unknown")
                    metadata["executor_run_id"] = resp.headers.get("X-Run-ID", "")
                    metadata["executor_duration"] = resp.headers.get("X-Duration-Ms", "")
                    matrix_run_count = resp.headers.get("X-Appium-Matrix-Run-Count")
                    if matrix_run_count and matrix_run_count.strip():
                        try:
                            metadata["executor_matrix_run_count"] = int(matrix_run_count)
                            metadata["executor_artifact_kind"] = "appium_device_matrix"
                        except ValueError:
                            metadata["executor_matrix_run_count"] = None

                    with open(zip_path, "wb") as zip_file:
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                zip_file.write(chunk)

            req_logger.info("done with executor regenerator")
            record_success("executor")
            return str(zip_path)

        with REQUEST_DURATION.labels(stage="executor").time():
            await retry_call("executor", call_executor)
        return PipelineService._enrich_executor_metadata_from_zip(zip_path, metadata)

    @staticmethod
    async def _generate_report(zip_path: Path, request_id: str, req_logger) -> str:
        client = await get_client()

        async def call_reporter() -> str:
            req_logger.info("Calling Report-Generator")
            req_logger.info("went to report generator")

            with open(zip_path, "rb") as zip_file:
                request_spec = PipelineService.build_report_generator_request(zip_file, request_id)
                resp = await client.post(
                    request_spec["url"],
                    headers=request_spec["headers"],
                    files=request_spec["files"],
                    timeout=request_spec["timeout"],
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=500, detail=f"Reporter Error {resp.status_code}: {resp.text}")
                req_logger.info("done with report generator")
                record_success("reporter")
                return resp.text

        with REQUEST_DURATION.labels(stage="reporter").time():
            return await retry_call("reporter", call_reporter)

    @staticmethod
    async def _upload_report(html_output: str, testcase_name: str, request_id: str, req_logger) -> str:
        client = await get_client()
        req_logger.info("Uploading report to ReportsRAG")
        req_logger.info("went to reports rag")

        request_spec = PipelineService.build_reports_rag_upload_request(html_output, testcase_name, request_id)
        resp = await client.post(
            request_spec["url"],
            headers=request_spec["headers"],
            data=request_spec["data"],
            files=request_spec["files"],
        )
        resp.raise_for_status()
        report_id = resp.json().get("report_id")
        req_logger.info("done with reports rag upload")
        return report_id

    @staticmethod
    def _extract_final_script(zip_path: Path) -> str:
        if not zip_path.exists():
            return ""

        with zipfile.ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
            if "final_script.py" in names:
                with archive.open("final_script.py") as script_file:
                    return script_file.read().decode("utf-8", errors="ignore")
            if "generated_script.py" in names:
                with archive.open("generated_script.py") as script_file:
                    return script_file.read().decode("utf-8", errors="ignore")
        return ""

    @staticmethod
    def _read_zip_json(archive: zipfile.ZipFile, entry_name: str) -> Optional[dict]:
        try:
            with archive.open(entry_name) as payload_file:
                return json.loads(payload_file.read().decode("utf-8", errors="ignore"))
        except Exception:
            return None

    @staticmethod
    def _enrich_executor_metadata_from_zip(
        zip_path: Path,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        enriched = dict(metadata or {})
        enriched.setdefault("executor_artifact_kind", "single_run")
        enriched.setdefault("executor_matrix_run_count", None)
        enriched.setdefault("executor_failed_step_index", None)

        if not zip_path.exists():
            return enriched

        with zipfile.ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
            manifest = PipelineService._read_zip_json(archive, "execution_manifest.json")
            if isinstance(manifest, dict):
                failed_step_index = manifest.get("failed_step_index")
                if failed_step_index is not None:
                    try:
                        enriched["executor_failed_step_index"] = int(failed_step_index)
                    except (TypeError, ValueError):
                        pass

            if "matrix_summary.json" in names:
                summary = PipelineService._read_zip_json(archive, "matrix_summary.json") or {}
                enriched["executor_artifact_kind"] = str(
                    summary.get("kind") or "appium_device_matrix"
                )
                runs = summary.get("runs")
                if isinstance(runs, list):
                    enriched["executor_matrix_run_count"] = len(runs)

        return enriched

    @staticmethod
    async def _post_success(name: str, coro_factory, req_logger, success_codes: set[int] | None = None):
        success_codes = success_codes or {200, 201}
        resp = await PipelineService._call_with_retry(name, coro_factory, req_logger, success_codes=success_codes)
        return resp

    @staticmethod
    async def _call_with_retry(
        name: str,
        coro_factory,
        req_logger,
        attempts: int = 3,
        base_delay: float = 0.5,
        success_codes: set[int] | None = None,
    ):
        import asyncio
        import httpx

        success_codes = success_codes or {200}
        for attempt in range(1, attempts + 1):
            try:
                resp = await coro_factory()

                if resp.status_code in (400, 401, 403, 404):
                    req_logger.error("Non-retryable client error from %s: %s - %s", name, resp.status_code, resp.text)
                    raise ValueError(f"Non-retryable client error {resp.status_code}: {resp.text}")

                if resp.status_code not in success_codes:
                    raise httpx.HTTPStatusError(
                        f"Status error {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                return resp
            except ValueError:
                raise
            except Exception as exc:
                if attempt == attempts:
                    req_logger.error("Permanent failure for %s after %s attempts: %s", name, attempts, exc)
                    raise
                delay = base_delay * (2 ** (attempt - 1))
                req_logger.warning(
                    "Downstream %s failed (attempt %s/%s): %s. Retrying in %.2fs",
                    name,
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    @staticmethod
    async def _sync_testcaserag(
        *,
        final_script_content: str,
        testcase_payload: dict,
        canonical_testcase_id: str,
        mode: str,
        req_logger,
    ) -> Dict[str, str]:
        client = await get_client()

        if mode == "new":
            req_logger.info("went to testcase rag for ingestion")
            request_spec = PipelineService.build_testcases_ingest_request(
                final_script_content,
                testcase_payload,
                canonical_testcase_id,
            )
            resp = await PipelineService._post_success(
                "TestCasesRAG ingest-full",
                lambda: client.post(
                    request_spec["url"],
                    headers=request_spec["headers"],
                    data=request_spec["data"],
                    files=request_spec["files"],
                ),
                req_logger,
            )
            payload = resp.json()
            req_logger.info("done with testcase rag ingestion")
            return {
                "status": "ingested",
                "canonical_testcase_id": payload.get("testcase_id") or canonical_testcase_id,
                "script_id": payload.get("script_id", ""),
            }

        req_logger.info("went to testcase rag for script synchronization")
        request_spec = PipelineService.build_testcases_sync_request(
            final_script_content,
            canonical_testcase_id,
            testcase_payload=testcase_payload,
        )
        resp = await PipelineService._post_success(
            "TestCasesRAG sync-script",
            lambda: client.post(
                request_spec["url"],
                headers=request_spec["headers"],
                data=request_spec.get("data"),
                files=request_spec["files"],
            ),
            req_logger,
        )
        payload = resp.json()
        req_logger.info("done with testcase rag script synchronization")
        return {
            "status": "synced",
            "canonical_testcase_id": canonical_testcase_id,
            "script_id": payload.get("script_id", ""),
        }

    @staticmethod
    async def _extract_and_upload_methods(
        final_script_content: str,
        req_logger,
        *,
        framework: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        client = await get_client()
        request_spec = PipelineService.build_extractor_request(final_script_content)

        req_logger.info("went to python methods extractor")
        resp = await PipelineService._post_success(
            "Extractor",
            lambda: client.post(
                request_spec["url"],
                headers=request_spec["headers"],
                data=request_spec["data"],
                files=request_spec["files"],
            ),
            req_logger,
        )
        csv_bytes = await resp.aread()
        csv_text = csv_bytes.decode("utf-8", errors="ignore")
        req_logger.info("done with python methods extractor")

        rows = list(csv.reader(io.StringIO(csv_text)))
        if not rows or "Raw Method" not in rows[0]:
            raise ValueError("Extractor output missing 'Raw Method' header")

        method_rows = [row for row in rows[1:] if row and row[0].strip()]
        if not method_rows:
            req_logger.warning("No generated step methods extracted; skipping MethodsRAG upload")
            return "skipped_no_step_methods"

        req_logger.info("went to methods rag")
        methods_request = PipelineService.build_methodsrag_upload_request(
            csv_bytes,
            framework=framework,
            language=language,
        )
        await PipelineService._post_success(
            "MethodsRAG",
            lambda: client.post(
                methods_request["url"],
                headers=methods_request["headers"],
                data=methods_request.get("data"),
                files=methods_request["files"],
            ),
            req_logger,
        )
        req_logger.info("done with methods rag upload")
        return "uploaded"

    @staticmethod
    async def _persist_generated_artifacts(
        *,
        zip_path: Path,
        testcase_payload: dict,
        canonical_testcase_id: str,
        mode: str,
        generated_script_content: str,
        req_logger,
    ) -> Dict[str, str]:
        req_logger.info("Synchronizing execution artifacts downstream...")
        artifact_metadata = PipelineService._enrich_executor_metadata_from_zip(zip_path)
        if artifact_metadata.get("executor_artifact_kind") == "appium_device_matrix":
            final_script_content = (generated_script_content or "").strip()
            if not final_script_content:
                raise HTTPException(
                    status_code=500,
                    detail="Generated Appium matrix script is unavailable for canonical sync",
                )
        else:
            final_script_content = PipelineService._extract_final_script(zip_path)
            if not final_script_content.strip():
                raise HTTPException(
                    status_code=500,
                    detail="Executor artifacts do not contain a finalized script",
                )

        tc_result = await PipelineService._sync_testcaserag(
            final_script_content=final_script_content,
            testcase_payload=testcase_payload,
            canonical_testcase_id=canonical_testcase_id,
            mode=mode,
            req_logger=req_logger,
        )
        script_framework, script_language = PipelineService.resolve_script_provenance(
            testcase_payload,
            script_content=final_script_content,
        )

        methods_status = "not_required"
        try:
            methods_status = await PipelineService._extract_and_upload_methods(
                final_script_content,
                req_logger,
                framework=script_framework,
                language=script_language,
            )
        except Exception as exc:
            req_logger.error("MethodsRAG sync failed: %s", exc)
            methods_status = f"failed: {exc}"

        req_logger.info("Artifact synchronization completed.")
        return {
            "testcase_rag_status": tc_result["status"],
            "methods_rag_status": methods_status,
            "canonical_testcase_id": tc_result["canonical_testcase_id"],
        }

    @staticmethod
    async def _link_report_history(
        *,
        canonical_testcase_id: str,
        testcase_name: str,
        report_id: str,
        executor_metadata: Dict[str, Any],
        routing_path: str,
        matched_probability: Optional[float],
        rag_statuses: Dict[str, str],
    ) -> None:
        await get_execution_history_collection().update_one(
            {"_id": canonical_testcase_id},
            {
                "$setOnInsert": {"testcase_name": testcase_name or "Unknown TestCase"},
                "$push": {
                    "reports": {
                        "report_id": report_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "status": "completed",
                        "executor_status": executor_metadata.get("executor_status", "unknown"),
                        "executor_run_id": executor_metadata.get("executor_run_id", ""),
                        "executor_duration": executor_metadata.get("executor_duration", ""),
                        "executor_artifact_kind": executor_metadata.get("executor_artifact_kind", "single_run"),
                        "executor_matrix_run_count": executor_metadata.get("executor_matrix_run_count"),
                        "executor_failed_step_index": executor_metadata.get("executor_failed_step_index"),
                        "routing_path": routing_path,
                        "matched_probability": matched_probability,
                        "testcase_rag_status": rag_statuses.get("testcase_rag_status", "not_required"),
                        "methods_rag_status": rag_statuses.get("methods_rag_status", "not_required"),
                    }
                },
            },
            upsert=True,
        )

    @staticmethod
    async def execute_run(
        testcase_payload: dict,
        request_id: str,
        script_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the complete intelligent automation pipeline from a testcase JSON payload."""
        req_logger = request_logger_adapter(request_id)
        semaphore = get_semaphore()
        acquired = False
        run_dir: Optional[Path] = None

        try:
            await semaphore.acquire()
            acquired = True
            req_logger.info("Execution run lock acquired. Starting testcase pipeline...")
            REQUEST_COUNT.labels(stage="total", status="started").inc()
            start_time = time.time()
            matched: Optional[Dict[str, Any]] = None

            if script_id:
                matched_probability = 100.0
                canonical_testcase_id = str(testcase_payload.get("_id") or testcase_payload.get("test_case_id") or uuid.uuid4())
            else:
                matched = await PipelineService._search_existing_testcase(testcase_payload, req_logger)
                matched_probability = float(matched.get("probability")) if matched else None
                canonical_testcase_id = (
                    str(matched.get("id"))
                    if matched
                    else str(testcase_payload.get("_id") or uuid.uuid4())
                )
                script_id = PipelineService.resolve_linked_script_id(matched)

            run_dir = Path(tempfile.mkdtemp(prefix=f"run_{request_id}_"))
            script_path = run_dir / "generated_script.py"
            zip_path = run_dir / "execution_artifacts.zip"

            generated_path_mode: Optional[str] = None
            if script_id:
                req_logger.info("Fetching existing TestCasesRAG script %s", script_id)
                existing_code = await PipelineService._fetch_script(script_id, req_logger)
                if existing_code.strip():
                    script_path.write_text(existing_code, encoding="utf-8")
                    routing_path = "existing_script"
                else:
                    routing_path = "existing_missing_script_generated"
                    generated_path_mode = "existing"
                    await PipelineService._generate_script(testcase_payload, script_path, request_id, req_logger)
            elif matched:
                routing_path = "existing_missing_script_generated"
                generated_path_mode = "existing"
                await PipelineService._generate_script(testcase_payload, script_path, request_id, req_logger)
            else:
                routing_path = "new_generated"
                generated_path_mode = "new"
                testcase_payload["_id"] = canonical_testcase_id
                await PipelineService._generate_script(testcase_payload, script_path, request_id, req_logger)

            executor_framework = PipelineService._normalize_framework(
                testcase_payload.get("target_framework")
            )
            executor_metadata = await PipelineService._execute_script(
                script_path,
                zip_path,
                request_id,
                req_logger,
                framework=executor_framework,
                testcase_payload=testcase_payload,
            )
            html_output = await PipelineService._generate_report(zip_path, request_id, req_logger)

            testcase_name = (
                testcase_payload.get("feature")
                or testcase_payload.get("Feature")
                or testcase_payload.get("test_case_id")
                or testcase_payload.get("Test Case ID")
                or f"Report for {canonical_testcase_id}"
            )
            report_id = await PipelineService._upload_report(html_output, testcase_name, request_id, req_logger)

            rag_statuses = {
                "testcase_rag_status": "not_required",
                "methods_rag_status": "not_required",
                "canonical_testcase_id": canonical_testcase_id,
            }
            if generated_path_mode:
                rag_statuses = await PipelineService._persist_generated_artifacts(
                    zip_path=zip_path,
                    testcase_payload=testcase_payload,
                    canonical_testcase_id=canonical_testcase_id,
                    mode=generated_path_mode,
                    generated_script_content=script_path.read_text(encoding="utf-8"),
                    req_logger=req_logger,
                )
                canonical_testcase_id = rag_statuses["canonical_testcase_id"]

            await PipelineService._link_report_history(
                canonical_testcase_id=canonical_testcase_id,
                testcase_name=testcase_name,
                report_id=report_id,
                executor_metadata=executor_metadata,
                routing_path=routing_path,
                matched_probability=matched_probability,
                rag_statuses=rag_statuses,
            )

            total_duration = time.time() - start_time
            REQUEST_COUNT.labels(stage="total", status="success").inc()
            status = "partial_success" if str(rag_statuses.get("methods_rag_status", "")).startswith("failed:") else "success"

            return {
                "status": status,
                "routing_path": routing_path,
                "matched_probability": matched_probability,
                "canonical_testcase_id": canonical_testcase_id,
                "testcase_id": canonical_testcase_id,
                "report_id": report_id,
                "executor_status": executor_metadata.get("executor_status", "unknown"),
                "executor_run_id": executor_metadata.get("executor_run_id", ""),
                "executor_duration": executor_metadata.get("executor_duration", ""),
                "executor_artifact_kind": executor_metadata.get("executor_artifact_kind", "single_run"),
                "executor_matrix_run_count": executor_metadata.get("executor_matrix_run_count"),
                "executor_failed_step_index": executor_metadata.get("executor_failed_step_index"),
                "testcase_rag_status": rag_statuses.get("testcase_rag_status", "not_required"),
                "methods_rag_status": rag_statuses.get("methods_rag_status", "not_required"),
                "duration": total_duration,
            }
        except Exception:
            REQUEST_COUNT.labels(stage="total", status="failure").inc()
            raise
        finally:
            if acquired:
                semaphore.release()
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)
