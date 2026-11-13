# Optional Tailcat transport (experimental)

This is an opt-in adapter, **not** a replacement for Hermes orchestration,
the host identity provider, Tailscale/Headscale network administration,
HEIMEL policy, or REHT execution clearance.

## Scope

- `unlimited.tailcat_transport.TailcatTransport` invokes an **externally installed**
  `tailcat` binary, without shell expansion.
- Supports a connectivity probe (`ping`, optional direct-path requirement) and
  a bounded request/reply stream (`exchange`).
- No Hermes tools, A2UI controls, background daemons, network listeners,
  or outbound operations are automatically enabled.
- Tailcat peer addresses are bearer capabilities containing a pre-shared key.
  Never place addresses in prompts, logs, public repos, telemetry, or URLs.
- A successful tunnel or ping does **not** authorize any action or identify a tenant.
  The calling host must independently verify identity, tenant, peer, permissible
  service, and (for external effects) execution clearance.
- Fail closed for missing CLI, invalid addresses, timeouts, and nonzero exits.

## Example (trusted operator context only)

```python
from unlimited.tailcat_transport import TailcatTransport
transport = TailcatTransport(timeout_seconds=10)
# address must arrive through a secret/out-of-band authenticated channel
# available = transport.ping(address)
# reply = transport.exchange(address, b"hello")
```

## Verification

```sh
python -m unittest tests.test_tailcat_transport -v
```

The tests mock the executable and network; they do **not** establish live
peer-to-peer, DERP fallback, latency, multi-tenant isolation, or production
readiness. Before enabling the adapter for customer work, test actual binaries
with two machines (direct and DERP fallback), enforce peer allowlists/short-lived
keys, verify address redaction, and measure cancellation and output bounds.
Subprocess stdout is currently checked **after** collection, so this prototype
must not be used against an untrusted unlimited-output peer.

## Decision record

Maintain Tailscale/Headscale for persistent managed mesh. Evaluate Tailcat for
ephemeral, narrowly-scoped connections. No new authorization semantics are
introduced into REHT/VAIG/RACS/Veritas by this transport adapter.
