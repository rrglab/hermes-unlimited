"""Read-only procurement mandate evaluation. Never authorizes external effects."""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

class CommercePolicyError(ValueError):
    pass

@dataclass(frozen=True)
class ProcurementDecision:
    verdict: str
    reasons: tuple[str, ...]
    proposal_digest: str
    mandate_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "reasons": list(self.reasons), "execution_authorized": False}

def _digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def _positive_int(v: Any) -> bool:
    return type(v) is int and v > 0

def evaluate_purchase(*, mandate: Mapping[str, Any], proposal: Mapping[str, Any]) -> ProcurementDecision:
    """Evaluate proposal against a trusted-host mandate, without issuing an execution permit.

    Does not verify signatures, balances, supplier identity, revocation, replay,
    purchase history, or a trusted clock. Host must independently enforce these.
    """
    if not isinstance(mandate, Mapping) or not isinstance(proposal, Mapping):
        raise CommercePolicyError("INVALID_RECORD")
    try:
        md, pd = _digest(mandate), _digest(proposal)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CommercePolicyError("INVALID_JSON_RECORD") from exc

    def decision(verdict: str, *reasons: str) -> ProcurementDecision:
        return ProcurementDecision(verdict, tuple(reasons), pd, md)

    m_fields = ("tenant_id", "principal_id", "agent_id", "currency", "expires_at", "mandate_id")
    p_fields = ("tenant_id", "principal_id", "agent_id", "currency", "supplier_id", "category", "created_at", "order_id")
    if any(k not in mandate for k in (*m_fields, "max_amount_minor", "approved_suppliers", "allowed_categories")) or any(k not in proposal for k in (*p_fields, "amount_minor")):
        return decision("DENY", "REQUIRED_FIELD_MISSING")
    if any(not isinstance(mandate[k], str) or not mandate[k].strip() for k in m_fields):
        return decision("DENY", "INVALID_MANDATE_SCOPE")
    if any(not isinstance(proposal[k], str) or not proposal[k].strip() for k in p_fields):
        return decision("DENY", "INVALID_PROPOSAL_SCOPE")
    if not _positive_int(mandate["max_amount_minor"]) or not _positive_int(proposal["amount_minor"]):
        return decision("DENY", "INVALID_AMOUNT")
    suppliers, categories = mandate["approved_suppliers"], mandate["allowed_categories"]
    if not isinstance(suppliers, (list, tuple)) or not isinstance(categories, (list, tuple)) or not suppliers or not categories or any(not isinstance(v, str) or not v.strip() for v in (*suppliers, *categories)):
        return decision("DENY", "INVALID_ALLOWLIST")
    def utc(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone missing")
        return dt.astimezone(timezone.utc)
    try:
        created, expiry = utc(proposal["created_at"]), utc(mandate["expires_at"])
    except (ValueError, TypeError, OverflowError):
        return decision("DENY", "INVALID_TIME")
    reasons = [f"{key.upper()}_MISMATCH" for key in ("tenant_id", "principal_id", "agent_id", "currency") if mandate[key] != proposal[key]]
    if created >= expiry:
        reasons.append("MANDATE_EXPIRED")
    if proposal["supplier_id"] not in suppliers:
        reasons.append("SUPPLIER_NOT_APPROVED")
    if proposal["category"] not in categories:
        reasons.append("CATEGORY_NOT_ALLOWED")
    if proposal["amount_minor"] > mandate["max_amount_minor"]:
        reasons.append("AMOUNT_EXCEEDS_LIMIT")
    return decision("DENY" if reasons else "ELIGIBLE_FOR_HOST_REVIEW", *reasons)
