import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_REQUIRED", "false")
os.environ.setdefault("API_KEY", "ReportsRAG")
os.environ.setdefault("ADMIN_API_KEY", "reports-admin-secret")
os.environ.setdefault("JWT_SECRET_KEY", "12345678901234567890123456789012")
os.environ.setdefault("MONGO_ENABLED", "false")

from app.main import app  # noqa: E402
from app.routes import report as report_routes  # noqa: E402


client = TestClient(app)
API_HEADERS = {"X-API-Key": os.environ["API_KEY"]}
ADMIN_HEADERS = {"X-Admin-API-Key": os.environ["ADMIN_API_KEY"]}


def test_health_ready_when_mongo_disabled():
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "db": "disabled"}


def test_upload_report_success(monkeypatch):
    created_at = datetime(2026, 6, 3, tzinfo=timezone.utc)

    async def fake_store_report(name, file):
        assert name == "Quarterly Report"
        return {
            "report_id": "507f1f77bcf86cd799439011",
            "name": name,
            "created_at": created_at,
            "size": 42,
            "content_type": "text/html",
        }

    monkeypatch.setattr(report_routes, "store_report", fake_store_report)

    response = client.post(
        "/v1/api/reports/upload",
        headers=API_HEADERS,
        data={"name": "Quarterly Report"},
        files={"file": ("report.html", "<html><body>ok</body></html>", "text/html")},
    )

    assert response.status_code == 201
    assert response.headers["x-request-id"]
    assert response.json() == {
        "status": "success",
        "message": "Report uploaded successfully",
        "report_id": "507f1f77bcf86cd799439011",
        "name": "Quarterly Report",
        "created_at": "2026-06-03T00:00:00Z",
    }


def test_upload_report_rejects_invalid_extension():
    response = client.post(
        "/v1/api/reports/upload",
        headers=API_HEADERS,
        data={"name": "Quarterly Report"},
        files={"file": ("report.txt", "<html><body>ok</body></html>", "text/plain")},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "Only .html or .htm files are allowed" in payload["error"]["message"]


def test_download_report_success(monkeypatch):
    async def fake_fetch_report(report_id):
        assert report_id == "507f1f77bcf86cd799439011"
        return {
            "id": report_id,
            "name": "Quarterly Report",
            "html_content": "<html><body>report</body></html>",
            "content_type": "text/html",
            "created_at": datetime(2026, 6, 3, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 6, 3, tzinfo=timezone.utc),
            "size": 33,
            "filename": "report.html",
        }

    monkeypatch.setattr(report_routes, "fetch_report", fake_fetch_report)

    response = client.get("/v1/api/reports/download/507f1f77bcf86cd799439011", headers=API_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"] == 'attachment; filename="Quarterly Report.html"'
    assert response.text == "<html><body>report</body></html>"


def test_admin_report_routes_reject_missing_or_normal_key():
    assert client.get("/v1/api/reports").status_code == 401
    assert client.get("/v1/api/reports", headers=API_HEADERS).status_code == 401
    assert client.get("/v1/api/reports", headers={"X-Admin-API-Key": os.environ["API_KEY"]}).status_code == 403

    assert client.delete("/v1/api/reports/507f1f77bcf86cd799439011", headers=API_HEADERS).status_code == 401
    assert client.post("/v1/api/reports/delete-all?confirm=true", headers=API_HEADERS).status_code == 401


def test_admin_list_reports_success(monkeypatch):
    created_at = datetime(2026, 6, 3, tzinfo=timezone.utc)

    async def fake_list_report_metadata(skip, limit):
        assert skip == 5
        assert limit == 10
        return [
            {
                "_id": "507f1f77bcf86cd799439011",
                "name": "Quarterly Report",
                "filename": "report.html",
                "content_type": "text/html",
                "created_at": created_at,
                "updated_at": created_at,
                "size": 42,
            }
        ]

    monkeypatch.setattr(report_routes, "list_report_metadata", fake_list_report_metadata)

    response = client.get("/v1/api/reports?skip=5&limit=10", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["skip"] == 5
    assert payload["limit"] == 10
    assert payload["reports"][0]["_id"] == "507f1f77bcf86cd799439011"


def test_admin_delete_report_success(monkeypatch):
    called = {}

    async def fake_delete_report(report_id):
        called["report_id"] = report_id

    monkeypatch.setattr(report_routes, "delete_report", fake_delete_report)

    response = client.delete("/v1/api/reports/507f1f77bcf86cd799439011", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert called["report_id"] == "507f1f77bcf86cd799439011"
    assert response.json() == {
        "success": True,
        "report_id": "507f1f77bcf86cd799439011",
        "message": "Report deleted successfully",
    }


def test_admin_delete_all_requires_confirm(monkeypatch):
    async def fake_delete_reports(confirm):
        raise AssertionError("delete_reports must not be called when confirm is false")

    monkeypatch.setattr(report_routes, "delete_reports", fake_delete_reports)

    response = client.post("/v1/api/reports/delete-all", headers=ADMIN_HEADERS)

    assert response.status_code == 400
    assert "Confirmation required" in response.json()["error"]["message"]


def test_admin_delete_all_success(monkeypatch):
    async def fake_delete_reports(confirm):
        assert confirm is True
        return 3

    monkeypatch.setattr(report_routes, "delete_reports", fake_delete_reports)

    response = client.post("/v1/api/reports/delete-all?confirm=true", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "deleted_reports": 3,
        "message": "All reports deleted successfully",
    }


def test_deleted_report_download_returns_404(monkeypatch):
    from app.core.errors import not_found_error

    async def fake_fetch_report(report_id):
        raise not_found_error(message=f"Report {report_id} not found")

    monkeypatch.setattr(report_routes, "fetch_report", fake_fetch_report)

    response = client.get("/v1/api/reports/download/507f1f77bcf86cd799439011", headers=API_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
