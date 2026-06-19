from fastapi import Request
from app.middleware import _get_client_ip
from app.core.security import RateLimiter
from app.core.config import get_settings

def test_audit_middleware_get_client_ip():
    settings = get_settings()
    original_trust = settings.TRUST_FORWARDED_IP
    
    try:
        # Case 1: TRUST_FORWARDED_IP is False
        settings.TRUST_FORWARDED_IP = False
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"203.0.113.195"), (b"x-real-ip", b"203.0.113.196")],
            "client": ("127.0.0.1", 12345)
        }
        req = Request(scope=scope)
        ip = _get_client_ip(req)
        assert ip == "127.0.0.1"
        
        # Case 2: TRUST_FORWARDED_IP is True
        settings.TRUST_FORWARDED_IP = True
        req = Request(scope=scope)
        ip = _get_client_ip(req)
        assert ip == "203.0.113.195"
        
    finally:
        settings.TRUST_FORWARDED_IP = original_trust


def test_rate_limiter_get_client_key():
    settings = get_settings()
    original_trust = settings.TRUST_FORWARDED_IP
    
    try:
        limiter = RateLimiter()
        
        # Case 1: TRUST_FORWARDED_IP is False
        settings.TRUST_FORWARDED_IP = False
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"203.0.113.195")],
            "client": ("127.0.0.1", 12345)
        }
        req = Request(scope=scope)
        key = limiter._get_client_key(req)
        assert key == "ip:127.0.0.1"
        
        # Case 2: TRUST_FORWARDED_IP is True
        settings.TRUST_FORWARDED_IP = True
        req = Request(scope=scope)
        key = limiter._get_client_key(req)
        assert key == "ip:203.0.113.195"
        
    finally:
        settings.TRUST_FORWARDED_IP = original_trust
