# AGY public slice: adapter maturity evidence policy

Extracted as an isolated, advisory component from the private Autonomous Company Engine (DEV merge #6). It provides a fail-closed maturity and per-tenant capability eligibility check. No private customer data, credentials, model calls, provider integrations, or live execution code is included.

This is not an execution authorization service. A trusted host must independently verify pinned build evidence, enforce identity, authorization, revocation, and real effects. The bundled module deliberately has no default approvals: metadata never certifies itself. JustYou is mandatory but cannot pass without host-provided evidence.

This PR does not release the full AGY Company OS, Mission Engine, Live Worker, Service Factory or live customer connectors. Their production status remains unverified. No customer delivery or measurable business outcome is claimed.
