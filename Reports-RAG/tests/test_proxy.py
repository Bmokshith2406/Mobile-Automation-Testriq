import pytest
from unittest.mock import patch, MagicMock
from fastapi import Request
from fastapi.responses import Response
from app.middleware.context import RequestContextMiddleware
from app.core.config import settings

def test_reports_middleware_client_ip():
    import asyncio
    asyncio.run(_test_impl())

async def _test_impl():
    original_trust = settings.TRUST_FORWARDED_IP
    
    middleware = RequestContextMiddleware(app=None)
    
    async def mock_call_next(request: Request):
        return Response(content="ok")
        
    try:
        # Test Case 1: TRUST_FORWARDED_IP is False
        settings.TRUST_FORWARDED_IP = False
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/reports",
            "headers": [(b"x-forwarded-for", b"203.0.113.195")],
            "client": ("127.0.0.1", 12345)
        }
        req = Request(scope=scope)
        
        mock_limiter = MagicMock()
        mock_limiter.enabled = True
        mock_limiter.is_allowed.return_value = True
        mock_limiter.get_remaining.return_value = 10
        
        with patch("app.middleware.context.get_limiter", return_value=mock_limiter):
            await middleware.dispatch(req, mock_call_next)
            
        mock_limiter.is_allowed.assert_called_once_with("127.0.0.1")
        
        # Test Case 2: TRUST_FORWARDED_IP is True
        settings.TRUST_FORWARDED_IP = True
        
        mock_limiter_2 = MagicMock()
        mock_limiter_2.enabled = True
        mock_limiter_2.is_allowed.return_value = True
        mock_limiter_2.get_remaining.return_value = 10
        
        with patch("app.middleware.context.get_limiter", return_value=mock_limiter_2):
            await middleware.dispatch(req, mock_call_next)
            
        mock_limiter_2.is_allowed.assert_called_once_with("203.0.113.195")
        
    finally:
        settings.TRUST_FORWARDED_IP = original_trust
