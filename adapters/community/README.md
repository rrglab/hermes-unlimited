# Free community adapters

These manifests let people *discover* free integration connectors. This
directory does not install or run remote software. Upstream services and APIs
may be paid, rate-limited, or require separate subscriptions.

Start: `python -m unlimited.community_adapters list`.
Generate a manifest: `python -m unlimited.community_adapters scaffold my-service --directory adapters/community`.
Replace placeholders with real upstream API documentation, capabilities and
license. Submit a pull request with an independent test suite, installation
notes and clear costs/limitations. Use existing Hermes MCP/CLI/API tools.

A discovered adapter is not enabled. JustYou is mandatory; only the existing
trusted host-controlled adapter gate can admit pinned reviewed code with
per-tenant capability scope. Do not equate an adapter's presence with a
working connection or independently verified execution.

Third-party contributions remain free and open under this repository's
Apache-2.0 contribution terms unless explicitly accepted under another
compatible license. Contributors retain their copyright. Include upstream
attribution; do not vendor GPL/AGPL code into this repository.

## Existing inventory

The community catalog has starter entries for Ember, Slack, GitHub, Cloudflare,
Outlook, Matrix, Zulip and Mattermost, plus six legacy upstream descriptors.
They are links and capability proposals, not confirmed working connectors.
Real adapters require API integration and independently checked acceptance.

The Hermes tool named unlimited_adapter_discover lists or inspects entries.
It returns execution_enabled: false; actual admission remains with the
existing host adapter gate and JustYou tenant scope.

## Contributor workflow

1. Run: python -m unlimited.community_adapters scaffold my-service --directory adapters/community
2. Replace placeholder URLs, adapter license, and capabilities. Document upstream license separately.
3. Reuse Hermes MCP, CLI and channel functionality rather than cloning upstream servers.
4. Supply contract and negative tests: authorization, tenant, malformed responses, timeouts.
5. Run: python -m pytest -q tests/test_community_adapters.py
6. Open an adapter proposal issue and PR. Review does not grant execution.

Metadata and contributions are free. Upstream services or API usage may cost
money. Never submit access tokens, customer messages, or private endpoints.


## Working thin delivery primitive

The module `unlimited/webhook_delivery.py` implements an **outgoing**
Slack-compatible JSON webhook POST. This can target Ember's or Slack's
existing incoming-webhook endpoint, without running either service. The
native Hermes tool `unlimited_adapter_chat_post` is intentionally disabled
unless the trusted host supplies:

- a valid JustYou session/profile binding (normal Hermes plugin scope);
- `tenant_adapter_registry` with the existing verified, capability-scoped
  `chat.message.send` authorization;
- `approve_adapter_effect` for explicit effect approval;
- `resolve_adapter_destination`, providing an HTTPS `WebhookDestination`
  using host-managed credentials, never a model-supplied URL.

For example a trusted host can register the adapter as a VERIFIED
`AdapterRegistration` with independent tests, configure the tenant capability
grant, and inject the callbacks after deployment approval. **The community
catalog does not do this automatically.** The tool accepts only an adapter
identifier, connection reference and message text; it never accepts a
destination URL, identity or tenant from the agent.

Ember itself does not provide signed outgoing bot webhooks. Receiving messages
requires a separately authenticated ingress; the outbound delivery primitive
is not an ingress gateway. An HTTP 2xx proves upstream acceptance only, not
that a message was viewed or that an agent completed work.

Contributor preflight:
    python -m unlimited.community_adapters validate
    python -m pytest -q tests/test_community_adapters.py tests/test_webhook_delivery.py

A generated scaffold includes adapter.json, README.md and adapter.py. The
template explicitly raises NotImplementedError and is never automatically
imported. Unit and live readback evidence must be supplied separately.
