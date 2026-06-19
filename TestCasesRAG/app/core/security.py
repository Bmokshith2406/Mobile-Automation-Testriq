from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", scheme_name="ApiKeyAuth", auto_error=False)
admin_api_key_header = APIKeyHeader(name="X-Admin-API-Key", scheme_name="AdminApiKeyAuth", auto_error=False)

async def verify_api_key(
    api_key: str = Security(api_key_header),
    admin_api_key: str = Security(admin_api_key_header),
) -> dict:
    """
    Verify either the standard API key or the admin API key.
    If the admin key is valid, return role='admin'.
    If the standard key is valid, return role='client'.
    """
    if admin_api_key and admin_api_key == settings.ADMIN_API_KEY:
        return {"id": "admin-client", "username": "admin-client", "role": "admin"}

    if api_key and api_key == settings.API_KEY:
        return {"id": "api-client", "username": "api-client", "role": "client"}

    if not api_key and not admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key or Admin API Key missing",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid API Key or Admin API Key",
    )

async def verify_admin_api_key(
    api_key: str = Security(api_key_header),
    admin_api_key: str = Security(admin_api_key_header),
) -> dict:
    """
    Verify the admin API key for sensitive operations.
    If a valid standard key is provided but the admin key is missing/invalid,
    return 403 Forbidden to block non-admins.
    """
    if admin_api_key and admin_api_key == settings.ADMIN_API_KEY:
        return {"id": "admin-client", "username": "admin-client", "role": "admin"}

    # If the standard client key is valid, reject with 403 Forbidden
    if api_key and api_key == settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access required",
        )

    if not admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API Key missing",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid Admin API Key",
    )
