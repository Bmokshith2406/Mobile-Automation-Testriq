from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
admin_api_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)

async def verify_api_key(
    api_key: str = Security(api_key_header),
) -> dict:
    """
    Verify the standard API key.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key missing",
        )
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )
    return {"id": "api-client", "username": "api-client", "role": "client"}

async def verify_admin_api_key(
    admin_api_key: str = Security(admin_api_key_header),
) -> dict:
    """
    Verify the admin API key for sensitive operations.
    """
    if not admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API Key missing",
        )
    if admin_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Admin API Key",
        )
    return {"id": "admin-client", "username": "admin-client", "role": "admin"}
