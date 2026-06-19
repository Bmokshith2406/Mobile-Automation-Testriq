import hmac
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.config import get_settings

settings = get_settings()


# Paths fully exempt from the middleware-level API key check.
# /health/ and /health/ready are open for load-balancer probes.
# /health/deep and /metrics are protected by Depends() inside their routers.
_FULLY_EXEMPT_PATHS = frozenset({
    "/health",
    "/health/",
    "/health/ready",
})

_DEV_ONLY_EXEMPT_PREFIXES = (
    "/docs",
    "/openapi.json",
    "/redoc",
)


class APIKeyMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Fully open: liveness and readiness probes only
        if path in _FULLY_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Dev-only: interactive docs
        if settings.ENV != "production":
            if any(path.startswith(p) for p in _DEV_ONLY_EXEMPT_PREFIXES):
                await self.app(scope, receive, send)
                return

        if not settings.API_KEY_ENABLED:
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        header_name = settings.API_KEY_HEADER.lower().encode()
        client_key_bytes = headers.get(header_name)

        if not client_key_bytes:
            await self._reject(scope, receive, send, "API key missing")
            return

        try:
            client_key = client_key_bytes.decode("utf-8")
        except UnicodeDecodeError:
            await self._reject(scope, receive, send, "Invalid API key encoding")
            return

        # Constant-time comparison
        if not hmac.compare_digest(client_key, settings.API_KEY):
            await self._reject(scope, receive, send, "Invalid API key")
            return

        await self.app(scope, receive, send)

    async def _reject(self, scope, receive, send, message: str):
        response = JSONResponse(
            status_code=401,
            content={
                "error": {
                    "type": "authentication_error",
                    "message": message,
                }
            },
        )
        await response(scope, receive, send)
