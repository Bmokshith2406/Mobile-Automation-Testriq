from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_handler import register_exception_handlers
from app.core.exceptions import ApplicationException


def test_application_exception_handler_does_not_crash_on_logging():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/application-error")
    async def application_error():
        raise ApplicationException(
            message="Bad input",
            status_code=400,
            error_code="BAD_INPUT",
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/application-error")

    assert response.status_code == 400
    assert response.json()["error"] == "BAD_INPUT"
    assert response.json()["message"] == "Bad input"


def test_general_exception_handler_returns_internal_error_without_logging_keyerror():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/unexpected-error")
    async def unexpected_error():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/unexpected-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "An unexpected error occurred"
