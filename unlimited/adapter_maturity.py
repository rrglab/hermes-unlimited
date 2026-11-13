"""AGY-derived adapter maturity evidence policy, advisory only: never an execution permit."""
from dataclasses import dataclass
from typing import Mapping
import re

CHECKS = ("unit", "contract", "security", "integration")
TIERS = ("CORE", "VERIFIED", "EXPERIMENTAL")


class AdapterPolicyDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    tier: str
    capabilities: tuple[str, ...]
    mandatory: bool = False

    def __post_init__(self):
        if not isinstance(self.adapter_id, str) or not self.adapter_id.strip():
            raise ValueError("ADAPTER_ID_REQUIRED")
        if self.tier not in TIERS:
            raise ValueError("INVALID_ADAPTER_TIER")
        if not self.capabilities or any(not isinstance(c, str) or not c.strip() for c in self.capabilities):
            raise ValueError("CAPABILITIES_REQUIRED")
        if self.mandatory and (self.adapter_id != "justyou" or self.tier != "CORE"):
            raise ValueError("ONLY_JUSTYOU_MANDATORY")


@dataclass(frozen=True)
class AdapterEvidence:
    """Evidence supplied by trusted host; never inferred from adapter metadata."""
    version: str
    sha256: str
    tested_sha256: str
    checks: Mapping[str, str]
    independently_tested: bool

    def valid_for(self, tier: str) -> bool:
        return (
            tier in ("CORE", "VERIFIED")
            and self.independently_tested is True
            and isinstance(self.version, str)
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.[0-9]+)?", self.version) is not None
            and isinstance(self.sha256, str)
            and re.fullmatch(r"[a-f0-9]{64}", self.sha256) is not None
            and self.tested_sha256 == self.sha256
            and isinstance(self.checks, Mapping)
            and all(self.checks.get(check) == "passed" for check in CHECKS)
        )


class TenantAdapterPolicy:
    """Pure per-tenant eligibility check; no adapter imports or runtime effects."""

    def __init__(self, descriptors: tuple[AdapterDescriptor, ...]):
        self._descriptors = {}
        for descriptor in descriptors:
            if descriptor.adapter_id in self._descriptors:
                raise ValueError("DUPLICATE_ADAPTER_ID")
            self._descriptors[descriptor.adapter_id] = descriptor
        justyou = self._descriptors.get("justyou")
        if justyou is None or not justyou.mandatory:
            raise ValueError("JUSTYOU_REQUIRED")
        self._grants: dict[str, dict[str, frozenset[str]]] = {}

    def configure(self, tenant: str, optional_grants: Mapping[str, tuple[str, ...]],
                  evidence: Mapping[str, AdapterEvidence]) -> None:
        if not isinstance(tenant, str) or not tenant.strip():
            raise AdapterPolicyDenied("TENANT_REQUIRED")
        if "justyou" in optional_grants:
            raise AdapterPolicyDenied("MANDATORY_JUSTYOU_NOT_OPTIONAL")
        grants = {}
        for adapter_id, caps in {"justyou": ("identity.verify",), **optional_grants}.items():
            descriptor = self._descriptors.get(adapter_id)
            if descriptor is None:
                raise AdapterPolicyDenied("UNKNOWN_ADAPTER")
            if adapter_id == "justyou" and "identity.verify" not in descriptor.capabilities:
                raise AdapterPolicyDenied("JUSTYOU_CAPABILITY_MISSING")
            ev = evidence.get(adapter_id)
            if not isinstance(ev, AdapterEvidence) or not ev.valid_for(descriptor.tier):
                raise AdapterPolicyDenied("VERIFIED_BUILD_EVIDENCE_REQUIRED")
            requested = frozenset(caps)
            if not requested or not requested.issubset(descriptor.capabilities):
                raise AdapterPolicyDenied("CAPABILITY_SCOPE_INVALID")
            grants[adapter_id] = requested
        self._grants[tenant] = grants

    def check(self, tenant: str, adapter_id: str, capability: str) -> bool:
        if capability not in self._grants.get(tenant, {}).get(adapter_id, ()):
            raise AdapterPolicyDenied("TENANT_CAPABILITY_DENIED")
        return True
