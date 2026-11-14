"""Thin, opt-in adapter for existing Slack-compatible incoming webhooks.

The Hermes host owns the URL and bearer material. This module never creates a
chat system, polls messages, stores credentials, or grants execution rights.
An HTTP 2xx means upstream accepted the POST, not that a human received it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class WebhookDeliveryError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class WebhookDestination:
    url: str
    # Intended only for local loopback integration tests, never customer config.
    allow_test_loopback: bool = False

    def __post_init__(self):
        parsed = urlsplit(self.url)
        local = self.allow_test_loopback and parsed.hostname in ("127.0.0.1", "::1")
        if (parsed.scheme != ("http" if local else "https")
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.query or len(self.url) > 2048):
            raise ValueError("TRUSTED_WEBHOOK_DESTINATION_REQUIRED")


def post_chat_message(destination: WebhookDestination, text: str, *, timeout: int = 5) -> dict:
    """Send without redirects, retries, or leaking URL/token in errors."""
    if not isinstance(destination, WebhookDestination):
        raise ValueError("TRUSTED_DESTINATION_REQUIRED")
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValueError("MESSAGE_INVALID")
    if type(timeout) is not int or not 1 <= timeout <= 15:
        raise ValueError("TIMEOUT_INVALID")
    data = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":")).encode()
    request = Request(destination.url, data=data, method="POST",
                      headers={"Content-Type": "application/json"})
    try:
        # Prevent inherited corporate proxies from receiving secret-bearing URL.
        with build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as exc:
        raise WebhookDeliveryError("UPSTREAM_HTTP_REJECTED") from None
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise WebhookDeliveryError("UPSTREAM_UNAVAILABLE") from None
    if not 200 <= status < 300:
        raise WebhookDeliveryError("UPSTREAM_NOT_ACCEPTED")
    return {"accepted": True, "delivery_verified": False, "status": status,
            "notice": "Upstream HTTP accepted, downstream readback not verified"}


def send_with_trusted_host(*, tenant: str, identity: str, adapter_id: str,
                           connection_id: str, text: str, registry,
                           approve_effect, resolve_destination) -> dict:
    """JustYou and admission are checked by caller and existing tenant registry.

    Security-sensitive host callbacks are injected by the Hermes runtime, not
    caller/model-provided URLs or boolean claims.
    """
    if adapter_id not in ("ember", "slack"):
        raise ValueError("ADAPTER_NOT_SUPPORTED_FOR_WEBHOOK_DELIVERY")
    if not all(isinstance(v, str) and v for v in (tenant, identity, connection_id)):
        raise PermissionError("IDENTITY_OR_CONNECTION_REQUIRED")
    if registry is None or not callable(approve_effect) or not callable(resolve_destination):
        raise PermissionError("TRUSTED_HOST_REQUIRED")
    registry.authorize_tenant_capability(
        tenant_id=tenant, adapter_id=adapter_id,
        capability="chat.message.send", require_release_eligible=True)
    if approve_effect(tenant, identity, adapter_id, connection_id, "chat.message.send") is not True:
        raise PermissionError("EXTERNAL_EFFECT_NOT_AUTHORIZED")
    destination = resolve_destination(tenant, identity, adapter_id, connection_id)
    if not isinstance(destination, WebhookDestination) or destination.allow_test_loopback:
        raise PermissionError("PRODUCTION_HTTPS_DESTINATION_REQUIRED")
    return post_chat_message(destination, text)
