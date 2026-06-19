from pathlib import Path

from fastapi.testclient import TestClient


def test_health_check(app_client: TestClient):
    response = app_client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


def test_readiness_check(app_client: TestClient):
    response = app_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["dependencies"]["fs_writable"] == "ok"


def test_generate_report_success(app_client: TestClient, valid_zip_bytes: bytes):
    response = app_client.post(
        "/api/v1/generate-report",
        headers={"X-API-Key": "test-key"},
        files={"file": ("test_artifact.zip", valid_zip_bytes, "application/zip")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Mocked overall summary for 3 steps." in response.text
    assert "data:video/webm;base64" in response.text
    assert "TC_PARABANK_END_TO_END_001" in response.text


def test_generate_report_invalid_extension(app_client: TestClient):
    response = app_client.post(
        "/api/v1/generate-report",
        headers={"X-API-Key": "test-key"},
        files={"file": ("test.txt", b"not a zip", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "File must be a ZIP archive"


def test_generate_report_missing_required_artifacts_returns_400(
    app_client: TestClient,
    missing_artifacts_zip_bytes: bytes,
):
    response = app_client.post(
        "/api/v1/generate-report",
        headers={"X-API-Key": "test-key"},
        files={"file": ("missing_artifacts.zip", missing_artifacts_zip_bytes, "application/zip")},
    )

    assert response.status_code == 400
    assert "Missing required artifact" in response.json()["message"]


def test_generate_report_without_video_still_succeeds(
    app_client: TestClient,
    no_video_zip_bytes: bytes,
):
    response = app_client.post(
        "/api/v1/generate-report",
        headers={"X-API-Key": "test-key"},
        files={"file": ("failed_artifact.zip", no_video_zip_bytes, "application/zip")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "TC_PARABANK_END_TO_END_001" in response.text


def test_generate_report_real_sample_zip(app_client: TestClient, sample_zip_path: Path):
    with sample_zip_path.open("rb") as handle:
        response = app_client.post(
            "/api/v1/generate-report",
            headers={"X-API-Key": "test-key"},
            files={"file": (sample_zip_path.name, handle, "application/zip")},
        )

    assert response.status_code == 200
    assert "Mocked overall summary for 17 steps." in response.text
    assert "data:video/webm;base64" in response.text


def test_rate_limiter_spoofing_prevention(app_client: TestClient):
    from app.middleware.rate_limit import rate_limiter
    rate_limiter._requests.clear()
    
    # Send 30 requests. Because TRUST_FORWARDED_IP is False by default,
    # the x-forwarded-for header is ignored and all requests count against 'testclient'.
    for i in range(30):
        res = app_client.get("/health/live", headers={"x-forwarded-for": f"10.0.0.{i}"})
        assert res.status_code == 200
        
    # The 31st request should be blocked
    response = app_client.get("/health/live", headers={"x-forwarded-for": "10.0.0.99"})
    assert response.status_code == 429
    assert response.json()["message"] == "Rate limit exceeded"
    
    # Clean up so we don't break other tests
    rate_limiter._requests.clear()
