"""Live Tailcat E2E release gate. Never substitutes stubs for a live peer.

Run only on isolated hosts with a real Tailcat peer and trusted Hermes runtime.
The operator's fixture module must provide build() -> fixture with:
  fixture.exchange(payload: bytes, *, tenant: str | None = None,
                   authorized: bool = True, timeout: bool = False,
                   oversized: bool = False) -> bytes
  fixture.tenant: str
  fixture.proof() -> dict
  fixture.close() -> None (optional)
exchange MUST enter the actual Hermes runtime -> JustYou -> AI Bridge ->
Tailcat CLI -> external authenticated service path. Flags must configure real
host-side denial/fault scenarios; they MUST NOT synthesize local exceptions.
proof() must return observed, nonsecret runtime evidence:
  runtime_commit, client_host, peer_host, verified_justyou,
  endpoint_authorized, server_peer_authenticated,
  server_tenant_authorized, transport_kind, network_peer,
  server_request_id, no_effect_on_denial, no_secret_in_logs
All values must be real measurements, not placeholders. No addresses/tokens.
"""
import importlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone

KEYS = (
    "runtime_commit", "client_host", "peer_host", "verified_justyou",
    "endpoint_authorized", "server_peer_authenticated",
    "server_tenant_authorized", "transport_kind", "network_peer",
    "server_request_id", "no_effect_on_denial", "no_secret_in_logs",
)
TRUE_KEYS = (
    "verified_justyou", "endpoint_authorized", "server_peer_authenticated",
    "server_tenant_authorized", "network_peer", "no_effect_on_denial",
    "no_secret_in_logs",
)
SCENARIOS = (
    "live_roundtrip", "justyou_endpoint_binding", "tenant_authorization",
    "timeout_and_response_bounds", "traceable_evidence",
)


def run():
    fixture_path = os.environ.get("TAILCAT_LIVE_FIXTURE")
    output = os.environ.get("TAILCAT_E2E_EVIDENCE", "tailcat-e2e-evidence.json")
    record = {
        "gate": "tailcat-live-e2e-v1",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCKED", "checks": {name: "NOT_RUN" for name in SCENARIOS},
        "reason": "live fixture not configured", "proof": {},
    }
    fixture = None
    try:
        if not fixture_path or not os.environ.get("TAILCAT_LIVE_OPT_IN") == "YES":
            raise RuntimeError("explicit TAILCAT_LIVE_FIXTURE and TAILCAT_LIVE_OPT_IN=YES required")
        if not fixture_path.replace("_", "").replace(".", "").isalnum():
            raise RuntimeError("invalid fixture module name")
        fixture = importlib.import_module(fixture_path).build()
        if not callable(getattr(fixture, "exchange", None)) or not callable(getattr(fixture, "proof", None)):
            raise RuntimeError("fixture must implement exchange() and proof()")
        if not isinstance(getattr(fixture, "tenant", None), str) or not fixture.tenant:
            raise RuntimeError("trusted tenant required")
        token = secrets.token_bytes(32)
        result = fixture.exchange(token)
        if result != token:
            raise AssertionError("remote request/reply mismatch")
        record["checks"]["live_roundtrip"] = "PASS"

        proof = fixture.proof()
        if not isinstance(proof, dict):
            raise AssertionError("proof() must return a dict")
        if any(proof.get(k) is not True for k in TRUE_KEYS[:5]):
            raise AssertionError("JustYou, endpoint, server peer and tenant checks not established")
        record["checks"]["justyou_endpoint_binding"] = "PASS"

        # Different tenant and explicitly revoked service authorization must
        # both fail BEFORE a remote effect; fixture must inspect server logs.
        for kwargs in ({"tenant": fixture.tenant + "-unauthorized"},
                       {"authorized": False}):
            try:
                fixture.exchange(secrets.token_bytes(24), **kwargs)
            except (PermissionError, RuntimeError, TimeoutError):
                pass
            else:
                raise AssertionError("unauthorized exchange succeeded")
        proof = fixture.proof()
        if proof.get("no_effect_on_denial") is not True:
            raise AssertionError("server-side denial evidence missing")
        record["checks"]["tenant_authorization"] = "PASS"

        # These must be injected into the real remote service or network path.
        # Local mock exceptions are NOT acceptable fixture implementations.
        for kwargs in ({"timeout": True}, {"oversized": True}):
            started = time.monotonic()
            try:
                fixture.exchange(secrets.token_bytes(24), **kwargs)
            except (TimeoutError, RuntimeError, OSError):
                pass
            else:
                raise AssertionError("fault scenario unexpectedly succeeded")
            if time.monotonic() - started > 125:
                raise AssertionError("bounded failure exceeded 125 seconds")
        record["checks"]["timeout_and_response_bounds"] = "PASS"

        proof = fixture.proof()
        if any(k not in proof for k in KEYS):
            raise AssertionError("required evidence fields missing")
        if any(proof.get(k) is not True for k in TRUE_KEYS):
            raise AssertionError("required independent checks not verified")
        if any(not isinstance(proof.get(k), str) or not proof[k] or
               proof[k].lower() in ("unknown", "mock", "stub", "n/a")
               for k in ("runtime_commit", "client_host", "peer_host",
                         "transport_kind", "server_request_id")):
            raise AssertionError("live runtime/peer evidence missing")
        if proof["client_host"] == proof["peer_host"]:
            raise AssertionError("external peer host is required")
        # Never write untrusted proof values: may contain bearer-capability.
        record["proof"] = {k: proof[k] for k in TRUE_KEYS}
        record["checks"]["traceable_evidence"] = "PASS"
        record["status"] = "PASS"
        record["reason"] = "all five checks passed; experimental, not production approval"
    except Exception as exc:
        record["status"] = "BLOCKED" if all(v == "NOT_RUN" for v in record["checks"].values()) else "FAIL"
        # No exception string: may carry secret endpoint addresses or tokens.
        record["reason"] = type(exc).__name__
    finally:
        if fixture is not None and callable(getattr(fixture, "close", None)):
            try:
                fixture.close()
            except Exception:
                record["status"] = "FAIL"
                record["reason"] = "fixture_cleanup_failed"
        # Evidence file must not accidentally publish secrets or token values.
        with open(output, "w", encoding="utf-8") as fp:
            json.dump(record, fp, indent=2, sort_keys=True)
            fp.write("\n")
        print(json.dumps(record, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(run())
