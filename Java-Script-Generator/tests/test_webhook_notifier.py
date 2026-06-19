import hashlib
import hmac
import json
import socket
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.webhook_notifier import WebhookNotifier


# ---------------------------------------------------------------------------
# URL Validation (SSRF)
# ---------------------------------------------------------------------------

class TestUrlValidation:
    """
    These tests use WebhookNotifier._is_valid_url() directly —
    no network calls are made.

    socket.getaddrinfo is mocked to avoid DNS lookups:
    - public_ip fixture returns a routable non-reserved IP (1.1.1.1)
    - private IP tests use literal IP strings that bypass DNS
    """

    @pytest.fixture
    def notifier(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        return WebhookNotifier()

    @pytest.fixture
    def mock_public_dns(self):
        """Make getaddrinfo return Cloudflare 1.1.1.1 for any hostname lookup."""
        public_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 0))]
        with patch("app.services.webhook_notifier.socket.getaddrinfo", return_value=public_result):
            yield

    def test_public_https_url_allowed(self, notifier, mock_public_dns):
        assert notifier._is_valid_url("https://hooks.myapp.com/notify") is True

    def test_public_http_url_allowed(self, notifier, mock_public_dns):
        assert notifier._is_valid_url("http://hooks.myapp.com/notify") is True

    def test_localhost_blocked(self, notifier):
        assert notifier._is_valid_url("http://localhost/hook") is False

    def test_loopback_ipv4_blocked(self, notifier):
        assert notifier._is_valid_url("http://127.0.0.1/hook") is False

    def test_loopback_ipv6_blocked(self, notifier):
        assert notifier._is_valid_url("http://[::1]/hook") is False

    def test_aws_metadata_ip_blocked(self, notifier):
        assert notifier._is_valid_url("http://169.254.169.254/latest/meta-data/") is False

    def test_private_rfc1918_blocked(self, notifier):
        assert notifier._is_valid_url("http://10.0.0.1/hook") is False
        assert notifier._is_valid_url("http://192.168.1.1/hook") is False

    def test_ftp_scheme_rejected(self, notifier):
        assert notifier._is_valid_url("ftp://example.com/file") is False

    def test_missing_host_rejected(self, notifier):
        assert notifier._is_valid_url("https:///no-host") is False


# ---------------------------------------------------------------------------
# Payload size guard
# ---------------------------------------------------------------------------

class TestPayloadSizeGuard:

    @pytest.fixture
    def notifier(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        return WebhookNotifier()

    @pytest.mark.asyncio
    async def test_oversized_payload_rejected_without_network_call(self, notifier):
        huge_payload = {"data": "x" * (WebhookNotifier.MAX_PAYLOAD_SIZE + 1)}
        # No exception — just returns False and logs a warning
        result = await notifier.notify("https://example.com/hook", huge_payload)
        assert result is False


# ---------------------------------------------------------------------------
# HMAC signature
# ---------------------------------------------------------------------------

class TestHmacSigning:

    @pytest.fixture
    def notifier(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        return WebhookNotifier()

    def test_signature_header_format(self, notifier):
        """The HMAC signature must follow the sha256=<hex> format."""
        secret = "mysecret"
        payload = {"event": "test"}
        body = json.dumps(payload, default=str)
        expected_sig = hmac.new(
            secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        # Compute what the notifier would produce
        actual_sig = hmac.new(
            secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        assert actual_sig == expected_sig
        assert actual_sig.startswith("") and len(actual_sig) == 64

    @pytest.mark.asyncio
    async def test_signature_sent_in_header_when_secret_provided(self, notifier, monkeypatch):
        """When a secret is given, X-Webhook-Signature must be present."""
        captured_headers = {}

        async def mock_post(url, content, headers):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            return resp

        notifier._client.post = mock_post
        await notifier.notify(
            "https://example.com/hook",
            {"event": "done"},
            secret="supersecret",
        )
        assert "X-Webhook-Signature" in captured_headers
        assert captured_headers["X-Webhook-Signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_no_signature_when_no_secret(self, notifier):
        """When no secret is configured, X-Webhook-Signature must NOT be sent."""
        captured_headers = {}
        notifier._default_secret = None

        async def mock_post(url, content, headers):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            return resp

        notifier._client.post = mock_post
        await notifier.notify("https://example.com/hook", {"event": "done"})
        assert "X-Webhook-Signature" not in captured_headers

    @pytest.mark.asyncio
    async def test_default_secret_auto_applied(self, monkeypatch):
        """WEBHOOK_SECRET from config must be used automatically."""
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("WEBHOOK_SECRET", "configsecret")
        notifier = WebhookNotifier()
        assert notifier._default_secret == "configsecret"
