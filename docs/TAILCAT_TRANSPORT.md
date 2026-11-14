# JustYou endpoint transport using Tailcat (experimental)

## Boundary

**JustYou remains the stable principal address** (`@address`), whether the principal
is a person, service, agent, machine or organization. It owns identity/continuity
references, not transport, routing, execution or authorization.

**AI Bridge** owns resolution of a JustYou principal to one or more active
provider/endpoint bindings, and chooses an approved transport. Tailcat is a
replaceable connector that carries bytes between two already authorized peers.
It must never be used as the principal identifier or an authorization grant.

```
JustYou @principal
   -> AI Bridge: authorized service and ephemeral endpoint binding
   -> Tailcat: encrypted direct P2P or DERP fallback
   -> trusted service: application identity check and tenant authorization
   -> separately authorized external effect (if any)
```

The Python modules now implement Tailcat transport and an **opt-in host-injected
JustYou endpoint bridge** (`unlimited.justyou_endpoint_bridge`). It composes the
existing `JustYouVerifier.verify` signed-profile verification result with a
trusted host endpoint resolver and a separate trusted host authorization
callback, enforcing identity/provider/tenant/service equality and binding expiry
before any transport call. Neither endpoint discovery/storage nor an actual
AI Bridge endpoint registry is bundled; the host must supply both callbacks.
An application protocol envelope, key rotation, replay defense, peer key
attestation and live mutual authentication remain separately required.
This is a guarded integration contract, not a complete deployment.

## JustYou -> endpoint integration\n\n```python\nfrom unlimited.justyou_endpoint_bridge import JustYouEndpointBridge\nfrom unlimited.tailcat_transport import TailcatTransport\n\n# Host supplies a real JustYouVerifier (signed binding), trusted endpoint\n# registry and policy/authorization check. Never use model-supplied values.\nbridge = JustYouEndpointBridge(\n    verify_profile=justyou_verifier.verify,\n    resolve_endpoint=trusted_host_resolver,\n    authorize_endpoint=trusted_host_endpoint_authorizer,\n    transport=TailcatTransport(allow_argv_secret_exposure=True),\n)\n# provider/tenant/service must also come from trusted Hermes runtime context.\nreply = bridge.exchange(provider=host_provider, tenant=host_tenant,\n                        service=host_service, payload=b'hello')\n```\n\nThis demonstration does not provide a host registry, invoke live peers, or\ncreate an execution permit. Do not deploy without independent peer identity\nvalidation and endpoint authorization at the service boundary.\n\n## Adapter\n
`unlimited.tailcat_transport.TailcatTransport` invokes an externally installed
Tailcat CLI. There is no automatic connection, registered Hermes tool, UI
surface, background daemon, or host identity bypass.

- `ping(address, require_direct=False)` tests reachability.
- `exchange(address, port, payload, max_bytes=...)` connects to an explicit
  TCP port on the remote Tailcat server, sends bytes, and receives a bounded
  response. Stdout is read through a pipe with a strict `max_bytes + 1` cap;
  responses above the limit terminate the subprocess. No unbounded temporary
  file or subprocess stdout buffer is used. A timeout kills the child process.
- Only opaque `tc...` addresses are accepted. DNS-derived public addresses are
  deliberately not supported.
- Fail closed for missing executable, bad input, timeouts, and nonzero exits.

## Security and deployment

Tailcat addresses include a preshared bearer capability; never log, publish,
put in prompts, or embed in public URLs. **The upstream Tailcat CLI takes that
secret as a command-line argument**, which may be visible to other local
processes or host audit tooling. This adapter cannot remove that exposure.
Calls fail closed unless the operator explicitly constructs the transport with
`allow_argv_secret_exposure=True`; that opt-in does **not** make the CLI safe
against hostile local users. Do not activate the adapter on shared or untrusted
hosts. Run it in an isolated, tightly permissioned environment or use a
transport that does not expose bearer secrets in argv. Sharing a Tailcat address is not proof
of JustYou identity. For persistent peers use allowlisted client keys and
independent service-level authentication. The published Tailcat threat model
is experimental and not designed for hostile unrelated tenants.

Public Tailcat DERP services keep metadata and are rate-limited with no SLA.
For enterprise or defense deployments evaluate private DERP relays and
offline/no-connectivity behavior. Tailcat cannot make an offline machine
reachable without some available networking path.

Transport fallback: prefer the host's existing, managed Tailscale/Headscale
path for long-lived estate; use Tailcat only for bounded ephemeral sessions.
No implicit fallback to unencrypted transport is allowed.

## Tests and evidence

```sh
python -m unittest tests.test_tailcat_transport tests.test_justyou_endpoint_bridge -v
```

Tests exercise real locally spawned stub subprocesses and mocked probe calls;
they cannot prove real Tailcat peer connectivity,
DERP fallback, JustYou identity continuity, tenant isolation, live Hermes
execution, cancellation, or production readiness. The server-side service
is not implemented here. No native JustYou repo changes are required for the
transport contract at this point.

## Minimum live E2E gate (release blocker)

Run `python tests/tailcat_live_e2e_gate.py` on a **tightly isolated**
operator-controlled node. Without a fixture it exits nonzero with
`status=BLOCKED`; this is intentional. Offline tests do not count.

Set `TAILCAT_LIVE_FIXTURE=your_trusted_fixture_module` and
`TAILCAT_LIVE_OPT_IN=YES` only after a **real external** Tailcat peer,
a mutually authenticated application service, and the real Hermes
runtime / signed JustYou verification / trusted endpoint resolver /
endpoint policy callbacks are configured. The fixture must export
`build()`, returning an object implementing `exchange(payload, *,
tenant=None, authorized=True, timeout=False, oversized=False)`,
`tenant`, `proof()`, and optionally `close()`. Its normal
`exchange` MUST use the full live chain, never mocks. The two fault
flags must inject failures in the real service/network, not simply
raise synthetic local exceptions. The `authorized=False` scenario
must revoke actual host authorization; alternate tenant must use
an unauthorized tenant and fail before network dispatch.

The gate records five checks: real peer roundtrip, signed JustYou/
endpoint/server authentication, tenant plus revoked authorization,
bounded timeout plus oversized response, and traceable nonsecret
evidence. It emits `tailcat-e2e-evidence.json` locally and returns
nonzero on missing fixture, any failure, or missing proof. **A PASS is
only a bounded experimental integration result**, not authorization
for production deployment, multitenant use or merger. The fixture
operator must independently inspect server logs to prove denied calls
had zero remote effects. Never upload raw Tailcat addresses, logs,
tokens, or CLI arguments. The JSON contains only boolean proof
flags; evidence identifiers must be referenced separately in a
secured evidence store.

No live fixture or external peer is included in this PR. Until an
actual run on the PR head yields an independently reviewed five-check
PASS, the PR must stay Draft. DERP fallback, replay defense, rotation,
mutual authentication and local argv-capability exposure remain
separate security blockers for production.
