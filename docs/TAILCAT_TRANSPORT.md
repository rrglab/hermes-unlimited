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

The current Python adapter implements only the **Tailcat transport**. Neither
JustYou endpoint resolution nor an AI Bridge binding service is implemented by
this PR. An actual protocol envelope, expiry, key rotation, replay defense,
service discovery, and mutually authenticated peer binding still need design
and independent implementation/testing. Do not treat the diagrams as complete.

## Adapter

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
python -m unittest tests.test_tailcat_transport -v
```

Tests exercise real locally spawned stub subprocesses and mocked probe calls;
they cannot prove real Tailcat peer connectivity,
DERP fallback, JustYou identity continuity, tenant isolation, live Hermes
execution, cancellation, or production readiness. The server-side service
is not implemented here. No native JustYou repo changes are required for the
transport contract at this point.
