from fastapi import Request, status
from fastapi.responses import JSONResponse
from app.core.logger import get_logger
from app.core.errors import APIException, ErrorCode, ErrorSeverity, ErrorCategory

logger = get_logger(__name__)


# ------------------------------------------------------------------------------
# API Exception Handler
# ------------------------------------------------------------------------------

async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """Handle custom API exceptions (enterprise-grade)."""

    log_payload = {
        "error_id": exc.id,
        "error_code": exc.error_code.value,
        "error_message": exc.message,
        "category": exc.category.value,
        "severity": exc.severity.value,
        "retryable": exc.retryable,
        "path": request.url.path,
        "method": request.method,
        "details": exc.details,
    }

    # Severity-aware logging
    if exc.severity == ErrorSeverity.CRITICAL:
        logger.critical("Critical API Exception", extra=log_payload, exc_info=True)
    elif exc.severity == ErrorSeverity.ERROR:
        logger.error("API Exception", extra=log_payload, exc_info=True)
    elif exc.severity == ErrorSeverity.WARNING:
        logger.warning("API Exception", extra=log_payload)
    else:
        logger.info("API Exception", extra=log_payload)

    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
        headers=exc.headers,
    )


# ------------------------------------------------------------------------------
# General Exception Handler
# ------------------------------------------------------------------------------

async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected uncaught exceptions."""

    logger.critical(
        "Unhandled Exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error": str(exc),
            "error_type": type(exc).__name__,
        },
        exc_info=True,
    )

    api_exc = APIException(
        error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        message="Internal server error",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        category=ErrorCategory.INTERNAL,
        severity=ErrorSeverity.CRITICAL,
    )

    return JSONResponse(
        status_code=api_exc.status_code,
        content=api_exc.to_dict(),
        headers=api_exc.headers,
    )
