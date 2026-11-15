# Hermes Unlimited — public plugin architecture

## Canonical objective
Enable a provider to create, operate, and sell AI-native companies and services to independent customers through one native Hermes plugin.

## Ownership and boundaries

| Component | Responsibility | Status |
| --- | --- | --- |
| Hermes plugin entrypoint | Register tools, hooks and CLI without core override | Skeleton implemented |
| Provider control plane | Own company templates, catalog and customer lifecycle | Contract only |
| Company/tenant boundary | Isolate identity, storage, roles, costs and results | Contract only |
| JustYou | Mandatory verified identity binding before effects | Interface only |
| Company orchestration | Provision roles, tasks, model routing and lifecycle | Interface only |
| Service catalog and billing | Package, meter and invoice provider services | Interface only |
| Result harvesting | Return outcome and evidence, not a success guess | Interface only |
| Optional adapters | Captain's Bridge, Jackets, Veritas, The Thread, channels and compute | Deferred |

## Trust and execution
Observation and planning do not grant execution authority. A task receipt records an outcome, not a permit. The runtime must refuse effects if mandatory JustYou binding is absent or invalid. Credentials are requested through the Hermes profile-scoped secret API, not read from token files. Provider and customer tenants never share identities or data by default.

## Required journey / P0
1. Provider installs plugin and binds JustYou securely.
2. Provider creates an isolated company for a customer.
3. Provider configures roles, a service and a price/usage policy.
4. Customer submits a service request.
5. Hermes executes with verified identity and scoped tool access.
6. Provider harvests a real result and evidence, then accounts for usage.

## P1
Optional channel, memory, Captain's Bridge, model routing and external execution adapters; recovery, resume, idempotence and observability.

## P2
Marketplace, multi-provider federation, enterprise governance add-ons, large-scale analytics.

## Proof before release
- Install/validate from a clean public clone on Mac and Acer, using exact commit SHA.
- Unit and integration tests green locally; no GitHub Actions dependency.
- Live scoped provider→company→customer→task→result→usage happy path and negative isolation tests.
- Verify missing/invalid JustYou and missing credentials fail closed.
- Verify no bundled private code, credentials, personal data, hidden dependencies or self-updating behavior.
- Record a demo and publish a pinned catalog entry only after these checks.

## Explicit non-goals
Not a Hermes fork, one bespoke managed company, a replacement identity provider, a mandatory governance suite or a generic background autonomous worker.


## Optional OpenShell isolation and Nebius compute

OpenShell is **not** a new Unlimited authorization provider. The canonical technical transport is maintained in `nsolland/valo-gateway` (PR #111, merged 2026-11-15). It must be invoked from a separately deployed and authorized `ValoGateway` after genuine REHT clearance; this public plugin contains no OpenShell CLI dependency, provider credentials, direct shell execution, or permission to create execution permits. JustYou verifies caller identity and tenant binding, not REHT effect authority. Veritas independently records verified external outcomes; an OpenShell sandbox log or local receipt is not a Veritas proof.

A future host integration can pass a verified tenant-scoped request to a separately configured Gateway deployment, which in turn selects a fixed OpenShell sandbox and effect program. A host operator, not the user payload, must pin the gateway profile, sandbox, executable and target capability. Native Hermes Kanban tasks are not execution permits. No direct effect path from Unlimited tools to OpenShell CLI is registered.

Nebius is listed only as an optional infrastructure host for an OpenShell-capable runtime. Deploying an OpenShell Gateway on Nebius does not change JustYou/REHT/ValoGateway/Veritas ownership, and this catalog entry is **not** evidence that any Nebius instance or credentials have been provisioned or tested. Both integrations advertise `can_execute=False` until an external live qualification validates non-bypass, external effect readback, durable revocation/replay and signed evidence.
