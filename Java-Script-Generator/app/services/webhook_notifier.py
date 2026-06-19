# app/services/webhook_notifier.py
"""
Webhook Notification Service

Production-ready implementation:
- Retry with exponential backoff + jitter
- Retry only on retryable errors
- HMAC signing
- Timeout protection
- SSRF-safe URL validation
- Persistent HTTP client
"""

import hashlib
import hmac
import json
import logging
import asyncio
import random
import ipaddress
import socket
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

logger = logging.getLogger("api.webhook")


class WebhookNotifier:
    """
    Webhook notification service with retry support.
    """

    MAX_PAYLOAD_SIZE = 2 * 1024 * 1024  # 2MB safety limit

    def __init__(self):
        self._settings = get_settings()
        self._timeout = self._settings.WEBHOOK_TIMEOUT_SECONDS
        self._max_retries = self._settings.WEBHOOK_MAX_RETRIES
        # Auto-sign payloads when WEBHOOK_SECRET is configured
        self._default_secret: Optional[str] = getattr(
            self._settings, "WEBHOOK_SECRET", None
        ) or None

        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
        )
        self._background_tasks = set()

    def add_task(self, task: asyncio.Task):
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------

    async def notify(
        self,
        url: str,
        payload: Dict[str, Any],
        secret: Optional[str] = None,
    ) -> bool:

        # Validate URL (basic SSRF protection)
        if not self._is_valid_url(url):
            logger.warning("Invalid webhook URL blocked", extra={"url": url})
            return False

        body = json.dumps(payload, default=str)

        if len(body.encode()) > self.MAX_PAYLOAD_SIZE:
            logger.warning("Webhook payload too large", extra={"size": len(body)})
            return False

        headers = {"Content-Type": "application/json"}

        # Use explicit secret > configured default > no signature
        active_secret = secret or self._default_secret
        if active_secret:
            signature = hmac.new(
                active_secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.post(
                    url,
                    content=body,
                    headers=headers,
                )

                # Success
                if 200 <= response.status_code < 300:
                    logger.info(
                        "webhook_delivered",
                        extra={
                            "url": url,
                            "status": response.status_code,
                            "attempt": attempt,
                        },
                    )
                    return True

                # Retry only on 5xx
                if 500 <= response.status_code < 600:
                    logger.warning(
                        "webhook_retry_server_error",
                        extra={
                            "url": url,
                            "status": response.status_code,
                            "attempt": attempt,
                        },
                    )
                else:
                    # 4xx = client error → do NOT retry
                    logger.warning(
                        "webhook_client_error_no_retry",
                        extra={
                            "url": url,
                            "status": response.status_code,
                        },
                    )
                    return False

            except httpx.RequestError as e:
                logger.warning(
                    "webhook_network_error",
                    extra={
                        "url": url,
                        "error": str(e),
                        "attempt": attempt,
                    },
                )

            # Backoff (exponential + jitter)
            if attempt < self._max_retries:
                backoff = (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(backoff)

        logger.error(
            "webhook_delivery_failed",
            extra={"url": url, "retries": self._max_retries},
        )

        return False

    # ------------------------------------------------------
    # URL VALIDATION
    # ------------------------------------------------------

    def _is_valid_url(self, url: str) -> bool:
        """Validate webhook URL against SSRF targets.

        NOTE — DNS rebinding: we resolve the hostname once here to block
        RFC-1918/loopback destinations.  A sophisticated attacker could
        serve a public IP on the first DNS query then switch to a private IP
        for the actual HTTP request.  Full mitigation requires pinning the
        resolved IP into the httpx request (custom transport); that adds
        complexity, so we log and block the most common cases.  Operators
        should also restrict outbound network access at the infrastructure
        level (security groups / egress firewall rules).
        """
        try:
            parsed = urlparse(url)

            if parsed.scheme not in ("http", "https"):
                return False

            if not parsed.netloc:
                return False

            hostname = parsed.hostname
            if not hostname:
                return False

            if hostname.lower() in ("localhost", "localhost."):
                return False

            try:
                addresses = [ipaddress.ip_address(hostname)]
            except ValueError:
                try:
                    infos = socket.getaddrinfo(hostname, None)
                except socket.gaierror:
                    return False
                addresses = list({
                    ipaddress.ip_address(info[4][0])
                    for info in infos
                })

            if any(self._is_blocked_ip(address) for address in addresses):
                return False

            return True

        except Exception:
            return False

    @staticmethod
    def _is_blocked_ip(address: ipaddress._BaseAddress) -> bool:
        return any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_multicast,
                address.is_reserved,
                address.is_unspecified,
            )
        )

    # ------------------------------------------------------
    # CLEANUP (optional but recommended)
    # ------------------------------------------------------

    async def close(self):
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Singleton factory — reuses one httpx connection pool across the application
# ---------------------------------------------------------------------------
_notifier_instance: Optional[WebhookNotifier] = None


def get_webhook_notifier() -> WebhookNotifier:
    """Return the shared WebhookNotifier instance."""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = WebhookNotifier()
    return _notifier_instance

