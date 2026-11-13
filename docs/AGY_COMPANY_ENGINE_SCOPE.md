# AGY Autonomous Company Engine — public code scope

This public release candidate comprises the deterministic Company OS, objective decomposition, CAVO economics, durable company memory, Service Factory, adapter eligibility, customer connection contracts, A2UI status surfaces, and the Hermes host-facing worker interface.

## Verified

Offline tests, authorization-denial paths, tenant-scoped interfaces, simulated deterministic model routing, checkpoint recovery, cryptographic verification contracts, and outbox semantics have been exercised. Local Acer Python 3.12: 127 unittest cases (2 skipped); 125 pytest passed (2 skipped; 24 subtests).

## Not verified as production operation

The external model worker, cross-provider critic, outbound SMTP, Stripe settlement, and live customer delivery are not certified as functioning production flows by these offline tests. API/SMTP/payment effects require explicit host authorization, trusted identity, tenant scope and independently validated receipts. An accepted outbox entry is not proof of delivery or settlement. Model cost/ROI demonstrations are modeled values, not measured commercial results. The source code is published for review without activating external effects.

## Dependencies and provenance

Extracted and adapted from the privately developed AGY Autonomous Company Engine in nsolland/hermes-unlimited-dev, merged to its development branch via PR #6. This repo is licensed under Apache-2.0. Python standard library plus the existing declared cryptography dependency; optional Hermes runtime required for real model calls. The public core does not bundle private credentials, runtime state, customers, or live acceptance logs.

## Offline verification

From a clean checkout run `python -m unittest discover -s tests -q` and `python -m compileall -q unlimited`. Running `python -m pytest -q tests` with pytest installed provides additional test discovery. The Hermes runtime, live providers and effect adapters are not invoked by the default offline suite.

## Native mission execution safety

Native mission and Company OS cycle tools fail closed unless the trusted Hermes host supplies an explicit `authorize_mission(tenant, identity, company_id, objective_id)` callback. Offline deterministic fixture workers are not accepted as implicit real-world execution. The Company OS cycle additionally requires a host-supplied mission worker; live model routing is opt-in and remains unverified as a production service. The tests assert denial when these trusted host capabilities are absent.

The trusted Hermes host must also inject an outcome verifier with an actual independent critic. An internal deterministic worker and an unconfigured self-verifier are insufficient for real tenant mission completion.
