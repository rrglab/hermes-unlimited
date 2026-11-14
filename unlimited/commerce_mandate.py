"""Host-side HMAC mandate preflight for sandbox tests; never grants execution.

Single-host HMAC is NOT AP2 or a multi-party delegated-payment mandate.
The trusted host must own the key, current time and revocation provider.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from .commerce_policy import ProcurementDecision, evaluate_purchase

class MandateRejected(PermissionError):
    pass

def _canonical(mandate: dict) -> bytes:
    if not isinstance(mandate, dict):
        raise MandateRejected("MANDATE_FORMAT_INVALID")
    try:
        return json.dumps(mandate, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError) as exc:
        raise MandateRejected("MANDATE_FORMAT_INVALID") from exc

def sign_test_mandate(mandate: dict, *, secret: bytes) -> str:
    """Sandbox fixture helper only; NEVER expose signing secret to an agent."""
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise MandateRejected("SIGNING_KEY_INVALID")
    return hmac.new(secret, b"hermes-commerce-mandate-v1\x00" + _canonical(mandate), hashlib.sha256).hexdigest()

@dataclass(frozen=True)
class MandatePreflight:
    verdict: str
    reason: str
    decision: ProcurementDecision | None
    execution_authorized: bool = False

def preflight_signed_purchase(*, mandate: dict, signature: str, proposal: dict,
                              trusted_secret: bytes, trusted_now: datetime,
                              is_revoked: Callable[[str], bool]) -> MandatePreflight:
    """Fail closed for bad signature, expiry, missing trust inputs and revoked mandate.

    No replay protection, aggregate-spend checks, provider signature interoperability,
    trusted payment receipt or live payment. Output is advisory ONLY.
    """
    if not isinstance(trusted_secret, bytes) or len(trusted_secret) < 32:
        raise MandateRejected("TRUSTED_KEY_REQUIRED")
    if not isinstance(trusted_now, datetime) or trusted_now.tzinfo is None:
        raise MandateRejected("TRUSTED_CLOCK_REQUIRED")
    if not callable(is_revoked):
        raise MandateRejected("REVOCATION_PROVIDER_REQUIRED")
    if not isinstance(signature, str) or len(signature) != 64:
        return MandatePreflight("DENY", "SIGNATURE_MISSING_OR_INVALID", None)
    expected = sign_test_mandate(mandate, secret=trusted_secret)
    if not hmac.compare_digest(signature, expected):
        return MandatePreflight("DENY", "SIGNATURE_MISMATCH", None)
    identifier = mandate.get("mandate_id")
    if not isinstance(identifier, str) or not identifier:
        return MandatePreflight("DENY", "MANDATE_ID_INVALID", None)
    try:
        if is_revoked(identifier) is not False:
            return MandatePreflight("DENY", "MANDATE_REVOKED", None)
    except Exception as exc:
        raise MandateRejected("REVOCATION_UNAVAILABLE") from exc
    try:
        expiry = datetime.fromisoformat(mandate["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Timezone required")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return MandatePreflight("DENY", "MANDATE_EXPIRY_INVALID", None)
    if trusted_now.astimezone(timezone.utc) >= expiry.astimezone(timezone.utc):
        return MandatePreflight("DENY", "MANDATE_EXPIRED", None)
    decision = evaluate_purchase(mandate=mandate, proposal=proposal)
    return MandatePreflight(decision.verdict,
                            "ADVISORY_ONLY" if decision.verdict == "ELIGIBLE_FOR_HOST_REVIEW" else ";".join(decision.reasons),
                            decision)
