"""Fail-closed adapter admission; no imports or execution before authorization.

The host, not adapter metadata or a customer request, supplies an immutable
approval manifest. This module never grants authority to execute side effects.
Also provides `TenantAdapterRegistry` with `CORE`, `VERIFIED`, and `EXPERIMENTAL`
maturity tiers, keeping `JustYou` mandatory and other Jackets optional under
strict per-tenant capability scopes.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping


class AdapterDenied(PermissionError):
    pass


_ID = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
_VERSION = re.compile(r'^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def authorize_adapter(adapter_id, *, catalog_path, approvals_path, host_scope, capability, status_provider=None):
    """Return pinned approved metadata; reject all incomplete or untrusted inputs."""
    if not isinstance(adapter_id, str) or not _ID.fullmatch(adapter_id):
        raise AdapterDenied('INVALID_ADAPTER_ID')
    if not isinstance(host_scope, str) or not host_scope.strip():
        raise AdapterDenied('HOST_SCOPE_REQUIRED')
    if not isinstance(capability, str) or not capability.strip():
        raise AdapterDenied('CAPABILITY_REQUIRED')
    try:
        catalog = _read(catalog_path)
        approvals = _read(approvals_path)
    except (OSError, ValueError, TypeError) as exc:
        raise AdapterDenied('APPROVAL_DATA_UNAVAILABLE') from exc
    if catalog.get('schema_version') != 1 or approvals.get('schema_version') != 1:
        raise AdapterDenied('INVALID_POLICY_SCHEMA')
    entries = catalog.get('adapters', [])
    records = approvals.get('approvals', [])
    if not isinstance(entries, list) or not isinstance(records, list):
        raise AdapterDenied('INVALID_POLICY_FORMAT')
    matching = [x for x in entries if isinstance(x, dict) and x.get('id') == adapter_id]
    approved = [x for x in records if isinstance(x, dict) and x.get('id') == adapter_id]
    if len(matching) != 1 or len(approved) != 1:
        raise AdapterDenied('NOT_UNIQUELY_APPROVED')
    entry, record = matching[0], approved[0]
    if entry.get('status') != 'approved' or record.get('status') != 'approved':
        raise AdapterDenied('ADAPTER_NOT_APPROVED')
    version, digest = record.get('version'), record.get('sha256')
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise AdapterDenied('VERSION_NOT_PINNED')
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise AdapterDenied('DIGEST_NOT_PINNED')
    if entry.get('approved_version') != version:
        raise AdapterDenied('VERSION_MISMATCH')
    if record.get('module') != entry.get('module'):
        raise AdapterDenied('MODULE_MISMATCH')
    if record.get('host_scope') != host_scope:
        raise AdapterDenied('SCOPE_MISMATCH')
    if capability not in record.get('capabilities', []):
        raise AdapterDenied('CAPABILITY_DENIED')
    if not record.get('reviewer') or not record.get('evidence'):
        raise AdapterDenied('REVIEW_EVIDENCE_REQUIRED')
    # Approval is valid only while the exact pinned build has passing
    # mandatory tests and security checks. Missing/failed/stale = denied.
    checks = record.get('checks')
    if not isinstance(checks, dict) or not checks:
        raise AdapterDenied('TEST_EVIDENCE_MISSING')
    mandatory = ('unit', 'contract', 'security', 'integration')
    if any(checks.get(name) != 'passed' for name in mandatory):
        raise AdapterDenied('REQUIRED_CHECK_NOT_GREEN')
    if record.get('tested_sha256') != digest:
        raise AdapterDenied('TESTED_DIGEST_MISMATCH')
    if record.get('tested_version') != version:
        raise AdapterDenied('TESTED_VERSION_MISMATCH')
    module_path = record.get('source_path')
    if not isinstance(module_path, str):
        raise AdapterDenied('SOURCE_NOT_PINNED')
    root = Path(catalog_path).resolve().parent.parent
    source = (root / module_path).resolve()
    if not source.is_relative_to(root) or not source.is_file() or source.suffix != '.py':
        raise AdapterDenied('SOURCE_OUTSIDE_REPOSITORY')
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise AdapterDenied('SOURCE_DIGEST_MISMATCH')
    # A host-controlled live status provider must confirm this exact artifact
    # at admission time. A stale approval file is never sufficient.
    if not callable(status_provider):
        raise AdapterDenied('LIVE_STATUS_PROVIDER_REQUIRED')
    try:
        live = status_provider(adapter_id, version, digest)
    except Exception as exc:
        raise AdapterDenied('LIVE_STATUS_UNAVAILABLE') from exc
    if not isinstance(live, dict) or live.get('version') != version or live.get('sha256') != digest:
        raise AdapterDenied('LIVE_STATUS_MISMATCH')
    if live.get('revoked') is not False or any(live.get('checks', {}).get(k) != 'passed' for k in mandatory):
        raise AdapterDenied('LIVE_STATUS_NOT_GREEN')
    return dict(record)


def load_approved_adapter(adapter_id, *, catalog_path, approvals_path, host_scope, capability, status_provider=None):
    """Import only after all admission checks; host still owns effect authorization."""
    record = authorize_adapter(adapter_id, catalog_path=catalog_path,
        approvals_path=approvals_path, host_scope=host_scope, capability=capability,
        status_provider=status_provider)
    return importlib.import_module(record['module'])


AdapterMaturityTier = Literal["CORE", "VERIFIED", "EXPERIMENTAL"]
MANDATORY_CHECK_NAMES = ("unit", "contract", "security", "integration")


@dataclass(frozen=True)
class AdapterRegistration:
    """Maturity-tiered Jacket / adapter descriptor in the Hermes Unlimited registry."""

    adapter_id: str
    tier: AdapterMaturityTier
    capabilities: tuple[str, ...]
    mandatory_for_all_tenants: bool = False
    independently_tested: bool = False
    checks: Mapping[str, str] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not _ID.fullmatch(self.adapter_id):
            raise AdapterDenied("INVALID_ADAPTER_ID")
        if self.tier not in ("CORE", "VERIFIED", "EXPERIMENTAL"):
            raise AdapterDenied("INVALID_MATURITY_TIER")
        if not self.capabilities:
            raise AdapterDenied("CAPABILITY_REQUIRED")
        if self.mandatory_for_all_tenants and self.tier != "CORE":
            raise AdapterDenied("MANDATORY_ADAPTER_MUST_BE_CORE")

    @property
    def all_mandatory_checks_passed(self) -> bool:
        return all(self.checks.get(k) == "passed" for k in MANDATORY_CHECK_NAMES)

    @property
    def release_eligible(self) -> bool:
        """Only CORE or VERIFIED adapters with passing independent tests are release-eligible."""
        return (
            self.tier in ("CORE", "VERIFIED")
            and self.independently_tested is True
            and self.all_mandatory_checks_passed
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["all_mandatory_checks_passed"] = self.all_mandatory_checks_passed
        data["release_eligible"] = self.release_eligible
        return data


_PASSED_CHECKS: Mapping[str, str] = {
    "unit": "passed",
    "contract": "passed",
    "security": "passed",
    "integration": "passed",
}

_PENDING_CHECKS: Mapping[str, str] = {
    "unit": "pending",
    "contract": "pending",
    "security": "pending",
    "integration": "pending",
}

DEFAULT_JACKET_REGISTRY: tuple[AdapterRegistration, ...] = (
    AdapterRegistration(
        adapter_id="justyou",
        tier="CORE",
        mandatory_for_all_tenants=True,
        capabilities=("identity.verify", "scope.enforce", "audit.seal"),
        independently_tested=True,
        checks=_PASSED_CHECKS,
        description="Mandatory JustYou identity, tenant isolation, and operational boundary gate.",
    ),
    AdapterRegistration(
        adapter_id="company-memory",
        tier="CORE",
        mandatory_for_all_tenants=False,
        capabilities=("memory.read", "memory.write", "memory.recall"),
        independently_tested=True,
        checks=_PASSED_CHECKS,
        description="Tenant-scoped durable organizational memory and verified outcome recall.",
    ),
    AdapterRegistration(
        adapter_id="service-factory",
        tier="CORE",
        mandatory_for_all_tenants=False,
        capabilities=("blueprint.register", "service.deliver", "sla.verify"),
        independently_tested=True,
        checks=_PASSED_CHECKS,
        description="Autonomous Service Factory blueprint packaging and verified delivery.",
    ),
    AdapterRegistration(
        adapter_id="customer-delivery-outbox",
        tier="VERIFIED",
        mandatory_for_all_tenants=False,
        capabilities=("customer.communicate", "delivery.receipt.issue"),
        independently_tested=True,
        checks=_PASSED_CHECKS,
        description="Authorized transactional customer communication and signed delivery receipt channel.",
    ),
    AdapterRegistration(
        adapter_id="a2ui-captains-bridge",
        tier="VERIFIED",
        mandatory_for_all_tenants=False,
        capabilities=("bridge.read", "bridge.action.propose"),
        independently_tested=True,
        checks=_PASSED_CHECKS,
        description="Captain's Bridge owner cockpit and 15-area readiness surface.",
    ),
    AdapterRegistration(
        adapter_id="live-email-connector",
        tier="EXPERIMENTAL",
        mandatory_for_all_tenants=False,
        capabilities=("email.send.external",),
        independently_tested=False,
        checks=_PENDING_CHECKS,
        description="External SMTP/API email connector (not release-eligible; blocked in production).",
    ),
    AdapterRegistration(
        adapter_id="live-payment-settlement",
        tier="EXPERIMENTAL",
        mandatory_for_all_tenants=False,
        capabilities=("payment.charge", "invoice.settle"),
        independently_tested=False,
        checks=_PENDING_CHECKS,
        description="External payment/invoice settlement rail (not release-eligible; blocked in production).",
    ),
    AdapterRegistration(
        adapter_id="live-crm-sync",
        tier="EXPERIMENTAL",
        mandatory_for_all_tenants=False,
        capabilities=("crm.write.external",),
        independently_tested=False,
        checks=_PENDING_CHECKS,
        description="External CRM bidirectional sync adapter (not release-eligible; blocked in production).",
    ),
)


class TenantAdapterRegistry:
    """Enforces maturity-tiered adapter eligibility and per-tenant Jacket capability scopes.

    Guarantees:
    1. `justyou` is mandatory (`CORE`) for every tenant and cannot be removed or bypassed.
    2. All other Jackets are optional and must be explicitly enabled per tenant with
       explicitly granted capability scopes.
    3. Only `CORE` and `VERIFIED` adapters with passing independent tests (`release_eligible=True`)
       can be authorized when `require_release_eligible=True`.
    """

    def __init__(
        self,
        registrations: tuple[AdapterRegistration, ...] = DEFAULT_JACKET_REGISTRY,
    ) -> None:
        self._adapters: dict[str, AdapterRegistration] = {}
        for reg in registrations:
            self.register_adapter(reg)
        if "justyou" not in self._adapters or not self._adapters["justyou"].mandatory_for_all_tenants:
            raise AdapterDenied("MANDATORY_JUSTYOU_ADAPTER_MISSING")
        # tenant_id -> {adapter_id -> set of granted capabilities}
        self._tenant_grants: dict[str, dict[str, set[str]]] = {}

    def register_adapter(self, registration: AdapterRegistration) -> None:
        if not isinstance(registration, AdapterRegistration):
            raise AdapterDenied("INVALID_ADAPTER_REGISTRATION")
        self._adapters[registration.adapter_id] = registration

    def get_adapter(self, adapter_id: str) -> AdapterRegistration:
        if adapter_id not in self._adapters:
            raise AdapterDenied(f"UNKNOWN_ADAPTER:{adapter_id}")
        return self._adapters[adapter_id]

    def configure_tenant_jackets(
        self,
        tenant_id: str,
        *,
        optional_grants: Mapping[str, tuple[str, ...] | list[str] | set[str]] | None = None,
        allow_experimental: bool = False,
    ) -> dict[str, tuple[str, ...]]:
        """Configure optional Jackets and capability scopes for a tenant while keeping JustYou mandatory."""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise AdapterDenied("TENANT_ID_REQUIRED")
        grants: dict[str, set[str]] = {}
        # Mandatory CORE adapters are always bound with their full core capabilities
        for reg in self._adapters.values():
            if reg.mandatory_for_all_tenants:
                if not reg.release_eligible:
                    raise AdapterDenied(f"MANDATORY_ADAPTER_NOT_RELEASE_ELIGIBLE:{reg.adapter_id}")
                grants[reg.adapter_id] = set(reg.capabilities)

        for adapter_id, requested_caps in (optional_grants or {}).items():
            if adapter_id not in self._adapters:
                raise AdapterDenied(f"UNKNOWN_ADAPTER:{adapter_id}")
            reg = self._adapters[adapter_id]
            if not allow_experimental and not reg.release_eligible:
                raise AdapterDenied(f"ADAPTER_NOT_RELEASE_ELIGIBLE:{adapter_id}:{reg.tier}")
            req_set = {str(c) for c in requested_caps}
            if not req_set:
                raise AdapterDenied(f"EMPTY_CAPABILITY_GRANT:{adapter_id}")
            unknown_caps = req_set - set(reg.capabilities)
            if unknown_caps:
                raise AdapterDenied(
                    f"CAPABILITY_NOT_SUPPORTED_BY_ADAPTER:{adapter_id}:{sorted(unknown_caps)[0]}"
                )
            grants[adapter_id] = req_set

        self._tenant_grants[tenant_id] = grants
        return {k: tuple(sorted(v)) for k, v in grants.items()}

    def authorize_tenant_capability(
        self,
        *,
        tenant_id: str,
        adapter_id: str,
        capability: str,
        require_release_eligible: bool = True,
    ) -> dict[str, Any]:
        """Verify that `tenant_id` is authorized to invoke `capability` on `adapter_id`."""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise AdapterDenied("TENANT_ID_REQUIRED")
        if not isinstance(capability, str) or not capability.strip():
            raise AdapterDenied("CAPABILITY_REQUIRED")
        reg = self.get_adapter(adapter_id)
        if require_release_eligible and not reg.release_eligible:
            raise AdapterDenied(f"ADAPTER_NOT_RELEASE_ELIGIBLE:{adapter_id}:{reg.tier}")

        # Ensure mandatory JustYou is always active even if configure_tenant_jackets wasn't called yet
        if tenant_id not in self._tenant_grants:
            self.configure_tenant_jackets(tenant_id, optional_grants={})

        tenant_map = self._tenant_grants[tenant_id]
        if adapter_id not in tenant_map:
            raise AdapterDenied(f"JACKET_NOT_ENABLED_FOR_TENANT:{tenant_id}:{adapter_id}")
        if capability not in tenant_map[adapter_id]:
            raise AdapterDenied(f"TENANT_CAPABILITY_SCOPE_DENIED:{tenant_id}:{adapter_id}:{capability}")

        return {
            "tenant_id": tenant_id,
            "adapter_id": reg.adapter_id,
            "tier": reg.tier,
            "capability": capability,
            "mandatory_for_all_tenants": reg.mandatory_for_all_tenants,
            "release_eligible": reg.release_eligible,
        }

    def list_release_eligible_adapters(self) -> list[dict[str, Any]]:
        return [reg.as_dict() for reg in self._adapters.values() if reg.release_eligible]

    def summary(self) -> dict[str, Any]:
        by_tier: dict[str, list[str]] = {"CORE": [], "VERIFIED": [], "EXPERIMENTAL": []}
        for reg in self._adapters.values():
            by_tier[reg.tier].append(reg.adapter_id)
        return {
            "total_adapters": len(self._adapters),
            "release_eligible_count": sum(1 for r in self._adapters.values() if r.release_eligible),
            "mandatory_adapters": [
                r.adapter_id for r in self._adapters.values() if r.mandatory_for_all_tenants
            ],
            "by_tier": by_tier,
            "adapters": [r.as_dict() for r in self._adapters.values()],
        }
