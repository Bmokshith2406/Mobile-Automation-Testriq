import unittest
from fastapi import Request
from app.core.rate_limiter import get_client_identifier
from app.core.config import get_settings

class TestProxy(unittest.TestCase):
    def test_get_client_identifier(self):
        settings = get_settings()
        original_trust = settings.TRUST_FORWARDED_IP
        
        try:
            # Case 1: TRUST_FORWARDED_IP is False
            settings.TRUST_FORWARDED_IP = False
            scope = {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"203.0.113.195")],
                "client": ("127.0.0.1", 12345)
            }
            req = Request(scope=scope)
            ip = get_client_identifier(req)
            assert ip == "127.0.0.1"
            
            # Case 2: TRUST_FORWARDED_IP is True
            settings.TRUST_FORWARDED_IP = True
            req = Request(scope=scope)
            ip = get_client_identifier(req)
            assert ip == "203.0.113.195"
            
        finally:
            settings.TRUST_FORWARDED_IP = original_trust
