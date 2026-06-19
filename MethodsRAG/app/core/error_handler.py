"""Global error handling and response formatting."""

from typing import Callable, Coroutine

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ProductionError, internal_error
from app.core.exceptions import ApplicationException
from app.core.logging import logger


def create_error_response(
    status_code: int,
    error_code: str,
    message: str,
    details: dict | None = None,
    request_id: str | None = None,
):
    """Create standardized error response."""
    response = {
        "error": error_code,
        "message": message,
    }
    
    if details:
        response["details"] = details
    
    if request_id:
        response["request_id"] = request_id
    
    return JSONResponse(
        status_code=status_code,
        content=response
    )


def register_exception_handlers(app: FastAPI):
    """Register all exception handlers with FastAPI app."""

    @app.exception_handler(ProductionError)
    async def production_error_handler(request: Request, exc: ProductionError):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )
    
    @app.exception_handler(ApplicationException)
    async def application_exception_handler(request: Request, exc: ApplicationException):
        """Handle ApplicationException."""
        logger.warning(
            f"Application error: {exc.error_code}",
            extra={
                "error_code": exc.error_code,
                "error_message": exc.message,
                "status_code": exc.status_code,
                "details": exc.details,
                "path": request.url.path,
            }
        )
        
        return create_error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details if exc.details else None,
            request_id=getattr(request.state, "request_id", None),
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle Pydantic validation errors."""
        errors = []
        for error in exc.errors():
            field = '.'.join(str(loc) for loc in error['loc'][1:])
            errors.append({
                "field": field,
                "message": error['msg'],
                "type": error['type']
            })
        
        logger.warning(
            "Validation error",
            extra={
                "validation_errors": errors,
                "path": request.url.path,
            }
        )
        
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": errors},
            request_id=getattr(request.state, "request_id", None),
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle uncaught exceptions."""
        # Log full stack trace
        logger.error(
            f"Unhandled exception: {type(exc).__name__}",
            exc_info=True,
            extra={
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
        )

        err = internal_error(request_id=getattr(request.state, "request_id", None))
        return JSONResponse(
            status_code=err.status_code,
            content=err.detail,
            headers=err.headers,
        )


async def safe_operation(
    operation_name: str,
    coroutine: Coroutine,
    on_error_callback: Callable | None = None,
):
    """Execute operation with error handling and logging."""
    try:
        logger.debug(f"Starting operation: {operation_name}")
        result = await coroutine
        logger.debug(f"Operation completed: {operation_name}")
        return result
    except ApplicationException as exc:
        logger.warning(
            f"Application error in {operation_name}: {exc.error_code}",
            extra={"error_code": exc.error_code, "error_message": exc.message}
        )
        if on_error_callback:
            await on_error_callback(exc)
        raise
    except Exception as exc:
        logger.error(
            f"Unexpected error in {operation_name}",
            exc_info=True,
            extra={"operation": operation_name}
        )
        if on_error_callback:
            await on_error_callback(exc)
        raise
