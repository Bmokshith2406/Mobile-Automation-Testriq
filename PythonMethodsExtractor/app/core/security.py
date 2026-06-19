from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

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
