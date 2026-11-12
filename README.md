![Hermes Unlimited — by REHT](assets/brand/github-banner.svg)

[![Hermes Unlimited by REHT](assets/brand/hermes-unlimited-badge.svg)](https://valoresearch.org/hermes-unlimited/)
[![Tests](https://github.com/rrglab/hermes-unlimited/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/rrglab/hermes-unlimited/actions/workflows/tests.yml)
[![CodeQL](https://github.com/rrglab/hermes-unlimited/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/rrglab/hermes-unlimited/actions/workflows/codeql.yml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

<div align="center">

**Don't hire another bot. Launch a company.**

Create AI-native companies for yourself and your customers. Publish services. Receive orders. Put Hermes workers to work. Retrieve the result.

**[Explore the product → valoresearch.org/hermes-unlimited](https://valoresearch.org/hermes-unlimited/)** · **[Discuss a provider pilot →](mailto:njaal@valoresearch.org?subject=Hermes%20Unlimited%20provider%20pilot)**

*A REHT Research Group product. Built on NousResearch Hermes Agent.*

</div>

![Meet your AI crew — Hermes Unlimited by REHT](assets/brand/hermes-hero.jpg)

<details>
<summary><strong>Meet the AI crew — creative, production and operations roles</strong></summary>

![Creative and coordination crew](assets/brand/hermes-crew.jpg)

![The makers — Producer, Builder, Creator and Director](assets/brand/hermes-makers.jpg)

![The operators — Coder, Tester, Debugger, Deployer, Operator and Janitor](assets/brand/hermes-operators.jpg)

![The Critics — The Skeptic and The Cynic](assets/brand/hermes-critics.jpg)

</details>

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for providers to create and operate AI-native companies and deliver services to their own customers.

## What works

- Installable Hermes plugin with eleven native tools and no Hermes core override.
- Provider/tenant-scoped company and service registry backed by SQLite.
- Priced service publishing and durable customer request intake with idempotent native Kanban submission; completed worker execution is asynchronous.
- JustYou session + signed Hermes profile binding verifier, with no token files bundled.
- Native Hermes Kanban task submission and scoped state reader, including request-to-task result association.
- Fail-closed checks for missing identity, mismatched profile, tenant boundaries and duplicate request IDs.

The native tool handles for company creation, service publishing and requests are functional with a trusted JustYou verifier supplied by the Hermes host.

## Green Core — live acceptance (11 November 2026)

A bounded, synthetic end-to-end acceptance run on the **Acer Hermes Unlimited runtime** completed successfully. This validates the installed customer-flow integration; the public repository's smaller native plugin core is a separate implementation and is **not** claimed to contain every runtime component exercised below.

- Company `acceptance-1111` was created from the support-desk template with three isolated Hermes profiles (triage, responder, knowledge).
- Three company-scoped JustYou identities were verified; the registry, session renewer and learning timer were active.
- Native Hermes Kanban task `t_5d8dce9d` was assigned to the triage profile, executed by a real worker and completed with exit code `0` and a customer-support handoff summary.
- The result was harvested into company-scoped memory once. A subsequent harvest recognized the duplicate without creating a second record.
- The learned entry was classified `RECORDED_UNVERIFIED`: it is an agent self-report, **not independently verified evidence**. No external customer contact or external effect was performed.

**Acceptance verdict:** GREEN for synthetic company creation → identity isolation → task execution → handoff → scoped learning capture. **Still open:** independent output verification, externally reproducible customer onboarding and production readiness. The runtime acceptance is not a substitute for green local tests against the public repository's exact commit.

## Future developments

**Our direction: AI-native companies as a service.**

Hermes Unlimited is evolving from a native Hermes plugin into a platform where a provider can **create, operate, and scale AI-native companies for customers**—with people and agents working as one organization.

| Area | What we are building toward |
| --- | --- |
| **Captain's Bridge** | One operating cockpit for companies, teams, missions, communications, customers, and results. |
| **AI Crew** | Coordinated agent roles—helpers, specialists, routers, coordinators, and directors—with clear ownership and handoffs. |
| **Mission Control** | Goals that persist across sessions, task execution, attention management, retries, completion, and measurable outcomes. |
| **AI Bridge** | Choice of models, providers, and routing strategies based on capability, latency, budget, and workload. |
| **Company Memory** | Durable context and organizational learning, with optional integration of The Thread. |
| **Service Factory** | Turn repeatable agent work into customer-facing services, intake, delivery, and reusable packages. |
| **Business Engine** | Revenue, cost, AI ROI, billing, and continuous improvement of company economics. |
| **Communications** | Customer and team interaction through supported phone, email, and messaging channels. |
| **Integrations & add-ons** | Modular tools, virtual work environments, and optional governance or evidence capabilities. |

### AI crew roles

The crew is a **role model for work**, not a fixed set of separate models or mandatory agents. One agent may perform multiple roles, and roles can be reassigned by the coordinator.

| Role family | Roles | Responsibility |
| --- | --- | --- |
| **Direction** | Director, Coordinator, Router | Set direction, break down goals, assign work, and select the right execution path. |
| **Creative** | Creator, Composer, Storyteller | Design ideas and produce creative content. |
| **Production** | Producer, Builder, Coder | Make concrete deliverables: software, artifacts, and customer work. |
| **Quality** | Tester, Debugger, Reviewer | Validate results, identify failures, and repair defects. |
| **Operations** | Deployer, Operator, Janitor, Maintainer | Release and run services, monitor outcomes, clean up stale state, and keep systems healthy. |
| **Support** | Helper, Specialist | Assist execution with targeted skills and domain knowledge. |
| **Independent Review &amp; Critique** | The Skeptic, The Cynic | Challenge evidence, assumptions, costs, customer value, and each other's conclusions; report actionable concerns to the Coordinator. |

Roles are envisioned capabilities; the illustrations are a visual identity, not proof of live autonomous execution.


### The Humor Gallery — serious AI, ridiculous personalities

**The Humor Gallery** is an original cast of comic AI work archetypes. Their job is to reveal real organizational failure modes through short, memorable scenes and, eventually, optional evaluation routines. Characters are original; classic comedy is **inspiration for the failure mode**, not a source of copied scripts, likenesses, voices, or character designs. The gallery is a **creative concept**, not a claim that these runtime agents are implemented.

| Original character | Comedy inspiration | Practical responsibility | Expected output |
| --- | --- | --- | --- |
| **The Critics: The Skeptic & The Cynic** | Theatrical balcony critics (Statler & Waldorf) | Independently question evidence, assumptions, cost and customer value. | Specific objections and recommended verification. |
| **The Reality Checker** | Monty Python's *Dead Parrot* | Compare cheerful status claims with real observations and effects. | Claim-versus-observation discrepancy with supporting evidence. |
| **The Confused: The Literalist & The Interpreter** | Abbott & Costello's *Who's on First?* and The Two Ronnies' *Four Candles* | Expose ambiguous names, instructions, ownership, and handoffs before work starts. | Clarification questions, unambiguous restatement, and examples. |
| **The Bureaucrat** | *Yes Minister* | Detect procedural loops, circular approvals, and administrative delay. | List of unnecessary gates and a simpler permitted path. |
| **The Boundary Tester** | Wesensteen's submarine captain | Challenge assumptions about borders, scope and hidden operating constraints. | Boundary cases and concrete negative tests. |
| **The Normality Inspector** | Leif Juster's *Mot normalt* | Notice deviations that teams have normalized or stopped questioning. | Anomaly report and baseline comparison. |
| **The Overconfident Expert** | *Fleksnes* | Stress-test unjustified confidence and unsupported competence claims. | Confidence calibration questions and missing-proof list. |
| **The Misinterpreter** | Wesensteen's *Hos tannlegen* and verbal misunderstandings | Catch situations where participants agree on words but mean different things. | Terminology conflicts and clarified intent. |
| **The Contrarian** | Monty Python's *Argument Clinic* | Test whether disagreement contains reasoning or is merely opposition. | Steelmanned counterargument with a falsification test. |
| **The Obstruction Detector** | British bureaucratic satire | Distinguish necessary controls from process that prevents delivery. | Delay cause, accountable owner, and actionable simplification. |
| **The Improvisers** | Swedish *Macken* (Roy & Roger) | Explore low-cost practical workarounds when the standard route fails. | Bounded alternative proposal with assumptions and trade-offs. |
| **The Logical Satirist** | Hasse & Tage | Apply a claim's logic consistently to expose contradictions. | Counterexample or contradiction. |
| **The Obsolescence Inspector** | Galenskaparna's *Stinsen brinner* | Identify workflows kept alive after their underlying purpose has vanished. | Retirement or modernization recommendation. |
| **The Strategist** | *Blackadder* | Challenge weak plans, wrong priorities and excessive complexity. | Simpler strategy with explicit trade-offs. |
| **The Frustrated Operator** | *Fawlty Towers* | Detect broken operational handoffs and poor customer experiences. | Failure timeline, owner and recovery action. |
| **The Social Skeptic** | Larry David's observational comedy | Challenge whether customers actually want or understand an offering. | Customer-value hypothesis and validation test. |
| **The Diagnostician** | *House* | Compare competing explanations before declaring a root cause. | Ranked hypotheses and discriminating tests. |
| **The Minimalist** | *Parks and Recreation*'s Ron Swanson | Remove unnecessary agents, meetings, tools and workflow stages. | Smallest viable implementation and cost delta. |
| **The Bullshit Detector** | George Carlin's language criticism | Flag inflated claims, jargon and unsupported marketing statements. | Plain-language claim and proof checklist. |
| **The Questioner** | Socratic questioning | Surface unstated premises and test reasoning with targeted questions. | Assumptions and falsification questions. |
| **The Makers** | Original Hermes Unlimited production crew | Producer, Builder, Creator and Director turn goals into concrete assets. | Traceable production deliverables. |
| **The Operators** | Original Hermes Unlimited execution crew | Coder, Tester, Debugger, Deployer, Operator and Janitor build, validate and maintain outputs. | Working artifacts, tests, releases and maintenance records. |

These characters **observe, question, test and recommend**. They do not grant execution authority, silently mutate customer data, or override a company owner's decisions. The Coordinator can commission a review; a Reviewer or Tester validates findings; the owner decides consequential changes. The Critic is not the same role as a deterministic permission gate.

#### Character-led episode collection

The first episodes already sketched for the Hermes Unlimited Comedy Crew are:

| Episode | Working title | Failure mode |
| --- | --- | --- |
| **01 — The Critics** | *Who Reviews the Reviewers?* | Independent reviewers must themselves be reviewable; a third auditor challenges The Skeptic and The Cynic. |
| **02 — The Confused** | *Who's Running Who?* | Circular delegation and ambiguous role ownership. |
| **03 — The Minimalist** | *Fourteen Agents and a Shell Script* | Overengineering a task that requires a simpler tool. |
| **04 — The Operators** | *It Works on My Machine* | A local success is mistaken for a tested, deployable system. |

An initial Gemini-produced visual episode for *The Critics* was created outside this repository; the table is a concept slate, not a claim that all four videos are published here.

#### Animated micro-series: *The Humor Gallery — AI Gone Wrong*

1. **The Deployment Is Just Resting** — a service is unresponsive while the team insists it is “optimizing.” *Reality Checker* demands a live result, while *The Critics* comment from the balcony. Failure mode: status optimism without evidence.
2. **Who's Running What?** — Router, Coordinator and Builder all interpret the same task name differently. *The Confused* map the handoffs. Failure mode: ambiguous ownership and instruction semantics.
3. **We Can't See the Boundary Underwater** — a confident operator assumes a boundary does not apply because it cannot be seen. *Boundary Tester* introduces explicit negative cases. Failure mode: invisible constraints ignored.
4. **The Committee That Approved Nothing** — every approval refers to another approval. *The Bureaucrat* documents the loop and *Obstruction Detector* proposes a lawful shorter route. Failure mode: progress confused with process.
5. **Everything Is Perfectly Normal** — a dashboard labels repeated breakdowns “normal operations.” *Normality Inspector*, *Overconfident Expert* and *The Critics* test that claim. Failure mode: normalization of deviance.

**Video production brief:** English voice and on-screen text; original charming 3D robot characters consistent with the Hermes mascot; midnight, ivory and champagne-gold palette; correct gold infinity mark; brand lockup **Hermes Unlimited — by REHT**. Episodes can be cut into 8–12-second scenes for Gemini/Veo and assembled into 30–40-second stories. Preserve consistent character silhouettes and voices across episodes. Do not recreate copyrighted sketches, dialogue or performers.

**Pilot acceptance:** At least one scene should demonstrate an actual testable failure mode using synthetic inputs, a verifiable observation, a useful critique and an actionable correction. Measure whether users can correctly describe the failure and fix after watching. Entertainment alone does not prove an AI capability.


### The intended customer journey

1. **Create a company** — define its owner, purpose, customers, services, and operating limits.
2. **Assemble the crew** — choose agent roles, models, tools, and communication channels.
3. **Launch missions** — set goals, delegate work, supervise execution, and handle exceptions.
4. **Harvest outcomes** — collect deliverables, results, costs, and feedback.
5. **Improve and scale** — reuse what works across customers, services, and companies.

This is the **product direction**, not a statement that every capability above is already shipped in this public repository. The native core and its current scope are described in *What works* and *Boundary* below.

## Native tools

- `hermes_unlimited_status`
- `unlimited_company_create`
- `unlimited_company_list`
- `unlimited_service_dispatch`
- `unlimited_service_result`
- `unlimited_service_publish`
- `unlimited_service_request`
- `unlimited_company_task`
- `unlimited_company_result`
- `unlimited_creative_render`
- `unlimited_creative_result`

## Trusted profile setup

The plugin accepts trusted JustYou objects injected by Hermes (`ctx.justyou_session_store`, `ctx.justyou_resolver`) or connects to the canonical JustYou service through a loopback-only session validator and signed profile-binding cache. It fails closed if either verification is unavailable. Hermes profile-scoped secrets must provide:

- `HERMES_UNLIMITED_PROVIDER_ID`
- `HERMES_UNLIMITED_TENANT_ID`
- `HERMES_UNLIMITED_JUSTYOU_IDENTITY`
- `HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN` or `HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN_FILE` (private mode `0600`, reread on each operation)
- `HERMES_UNLIMITED_REGISTRY_DB`
- Optional `HERMES_UNLIMITED_HERMES_CLI`

Without host injection, configure these additional profile-scoped values:

- `HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL` (`http://127.0.0.1:<port>` only)
- `JUSTYOU_BINDINGS_FILE` (private, signed JustYou binding export)
- `JUSTYOU_AUTHORITY_KEY_ID`
- `JUSTYOU_AUTHORITY_KEY_FILE` (private, public verification key for Ed25519)
- Optional `JUSTYOU_AUTHORITY_KIND` (defaults to `ed25519`; `hmac` only for explicitly configured prototype deployments)

The JustYou canonical Python package (`protocol.authoritative_binding`) must be installed into the Hermes runtime. A bindings JSON file is a cache; every binding and version announcement is signature-verified, and every operation revalidates the active session. No JustYou material is bundled with this repository.

The session token is read from trusted Hermes profile scope or a private file maintained by the session renewer. Do not put credentials, customer data or keys in the plugin repository.

## Tenant-isolated Kanban boards

Hermes Unlimited pins every Kanban create/list operation to a dedicated board computed from the **trusted provider and tenant**. Hermes tenant filtering alone is not a hard isolation boundary; each board has its own SQLite queue and worker scope.

Provision the board **before** dispatch using the provider/tenant values from the trusted Hermes profile:

```bash
python3 -c 'from unlimited.hermes_kanban import board_for; print(board_for("YOUR_PROVIDER_ID", "YOUR_TENANT_ID"))'
hermes kanban boards create <printed-board-slug>
```

Do not set the board to `default` or reuse a board across customers. Missing boards must fail closed; no fallback to the active board. Board provisioning alone is not a proof of worker completion or independent customer-delivery verification.

## Validate

```bash
python3 -m unittest discover -s tests -v
hermes plugins validate . --install-deps
```

Local green tests remain canonical. Public GitHub Actions independently run
offline unit tests on Python 3.11–3.13 and CodeQL security analysis on pull
requests. CI results are advisory and do not attest to live Hermes dispatch,
customer effects, or production readiness. Dependabot checks action updates.

## Installation and execution disclosures (catalog rule 13)

- **Network:** The core does not send mandatory telemetry. Hermes workers can contact model providers selected and paid for by the host. Optional creative rendering can contact the host-configured render backend; the ComfyUI client sends workflows to the configured ComfyUI server and reads outputs.
- **Local files and persistence:** Provider, company, service and customer-request metadata are stored in the configured SQLite registry. The host-provided JustYou verifier may read a signed binding export, a private session-token file and a public verification-key file outside plugin data; paths are explicit profile configuration, never discovered by scanning arbitrary files.
- **Shell and background work:** The plugin invokes the local `hermes kanban` CLI to create and read worker tasks on an explicitly provisioned tenant board. Hermes, not the plugin, owns scheduling and workers. No additional privileged daemon, unattended shell job or self-updater is installed.
- **Secrets:** Identity, tenant and authority are resolved from host/profile scope; no API credentials, private keys or bearer tokens ship with the repository. Secrets remain in the host's configured stores.
- **Approvals:** No auto-approval, disabling of Hermes guards or core override. Missing authorization fails closed. The plugin may submit work only after trusted JustYou verification.
- **Limits:** No live payment settlement, no independently attested worker effects and no claim of production customer fulfillment. A Hermes task marked `done` is not proof of customer acceptance.

## Boundary

Hermes owns the worker, channels, scheduler and Kanban execution. JustYou supplies verified identity. Unlimited supplies provider/customer company and service semantics, task routing and result retrieval. Task state is not independent evidence. Company Memory (The Thread), Captain's Bridge, Jackets, Veritas, model routing and commercial optimization are optional integrations and are not bundled here.

See `docs/ARCHITECTURE.md`. The public code is Apache-2.0 licensed; private customer data and separately licensed extensions are not included.

## Optional ComfyUI creative engine

`unlimited.comfyui.ComfyUI` provides an opt-in HTTP client for an existing
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server. It submits an
API-format workflow to `/prompt`, reads `/history/{prompt_id}` and downloads
output descriptors from `/view`. No ComfyUI runtime, models, weights, workflow
templates or GPU are installed or bundled. Configure the origin explicitly:

```python
from unlimited.comfyui import ComfyUI

creative = ComfyUI("http://127.0.0.1:8188")
ack = creative.submit(api_format_workflow)
result = creative.result(ack["prompt_id"])
if result["state"] == "completed":
    print(result["outputs"])
```

Use only a trusted deployment and reviewed workflows. The calling Hermes
service must enforce tenant permissions, cost ceilings, allowed nodes and
output ownership; this low-level client does not grant execution authority.
ComfyUI is separately licensed (GPL-3.0) and is not redistributed here. A
successful offline test does not establish a live GPU workflow or finished media.

## Visual identity

The GitHub hero is [`assets/brand/github-banner.svg`](assets/brand/github-banner.svg). The official product lockup is [`assets/brand/wordmark.svg`](assets/brand/wordmark.svg). Use [`assets/brand/icon.svg`](assets/brand/icon.svg) for app icons and [`assets/brand/infinity.svg`](assets/brand/infinity.svg) where the standalone infinity mark is needed.

Brand colors: midnight `#0B0F17`, champagne gold `#C9A76A`, and ivory `#F8F9F5`. The product name is **Hermes Unlimited**; the endorsement is **by REHT**. These assets are product branding, not a claim that optional integrations are included in this repository.
