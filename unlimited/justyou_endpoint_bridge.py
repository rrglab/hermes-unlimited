"""Host-controlled JustYou -> AI Bridge -> optional Tailcat endpoint adapter.

Not a routing registry, identity issuer, execution permit, or background agent.
Caller injects trusted profile verification, scoped endpoint selection and
authorization callbacks. Never accept endpoint or tenant from model requests.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .tailcat_transport import TailcatTransport


class EndpointDenied(PermissionError):
    """No endpoint transport without independent trusted host approval."""


@dataclass(frozen=True)
class EndpointBinding:
    principal: str
    provider: str
    tenant: str
    service: str
    address: str
    port: int
    expires_at: datetime

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in (
                self.principal, self.provider, self.tenant, self.service)):
            raise ValueError("binding scope is required")
        TailcatTransport._address(self.address)
        TailcatTransport._port(self.port)
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise ValueError("timezone-aware expiry required")


class JustYouEndpointBridge:
    """Connect a trusted Hermes profile to an authorized ephemeral endpoint.

    verify_profile: existing JustYouVerifier.verify (signed profile evidence).
    resolve_endpoint: trusted host callback taking (identity, provider, tenant,
      service), returning EndpointBinding. Never expose as a model tool.
    authorize_endpoint: host callback taking the resolved EndpointBinding.
      Must independently check service entitlement, tenant, endpoint key,
      freshness/revocation and current policy before each network call.
    """

    def __init__(self, verify_profile: Callable, resolve_endpoint: Callable,
                 authorize_endpoint: Callable, transport: TailcatTransport):
        if not all(callable(x) for x in (
                verify_profile, resolve_endpoint, authorize_endpoint)):
            raise ValueError("trusted host callbacks required")
        if not isinstance(transport, TailcatTransport):
            raise ValueError("TailcatTransport required")
        self._verify = verify_profile
        self._resolve = resolve_endpoint
        self._authorize = authorize_endpoint
        self._transport = transport

    def exchange(self, *, provider: str, tenant: str, service: str,
                 payload: bytes, max_bytes: int = 1024 * 1024) -> bytes:
        if not all(isinstance(x, str) and x.strip() for x in (
                provider, tenant, service)):
            raise EndpointDenied("SCOPE_REQUIRED")
        try:
            evidence = self._verify()
            if not isinstance(evidence, dict) or evidence.get("verified") is not True:
                raise EndpointDenied("JUSTYOU_UNVERIFIED")
            if evidence.get("authority_granted") is not False:
                raise EndpointDenied("INVALID_IDENTITY_EVIDENCE")
            identity = evidence.get("identity")
            if not isinstance(identity, str) or not identity.startswith("@"):
                raise EndpointDenied("INVALID_PRINCIPAL")
            if not isinstance(evidence.get("binding_digest"), str) or not evidence["binding_digest"]:
                raise EndpointDenied("PROFILE_BINDING_REQUIRED")
            binding = self._resolve(identity, provider, tenant, service)
            if not isinstance(binding, EndpointBinding):
                raise EndpointDenied("ENDPOINT_UNAVAILABLE")
            if (binding.principal != identity or binding.provider != provider
                    or binding.tenant != tenant or binding.service != service):
                raise EndpointDenied("SCOPE_MISMATCH")
            if binding.expires_at <= datetime.now(timezone.utc):
                raise EndpointDenied("ENDPOINT_EXPIRED")
            if self._authorize(binding) is not True:
                raise EndpointDenied("ENDPOINT_NOT_AUTHORIZED")
        except EndpointDenied:
            raise
        except Exception:
            raise EndpointDenied("TRUSTED_HOST_UNAVAILABLE") from None
        # No address, tenant, provider or service is accepted from request payload.
        return self._transport.exchange(
            binding.address, binding.port, payload, max_bytes=max_bytes)
