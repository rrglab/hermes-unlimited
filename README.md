![Hermes Unlimited — by REHT](assets/brand/github-banner.svg)

[![Hermes Unlimited by REHT](assets/brand/hermes-unlimited-badge.svg)](https://valoresearch.org/hermes-unlimited/)
[![Tests](https://github.com/rrglab/hermes-unlimited/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/rrglab/hermes-unlimited/actions/workflows/tests.yml)
[![CodeQL](https://github.com/rrglab/hermes-unlimited/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/rrglab/hermes-unlimited/actions/workflows/codeql.yml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

<div align="center">

**Don't hire another bot. Launch a company.**

Create AI-native companies for yourself and your customers. Turn business goals into scoped missions, coordinate workers, evaluate economics, learn from outcomes, and publish repeatable services.

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

## Release status — 0.1.0-alpha.7

**This repository (`rrglab/hermes-unlimited`) is the canonical public code release of Hermes Unlimited by REHT Research Group.** The AGY Autonomous Company Engine was merged into public `main` in [PR #16](https://github.com/rrglab/hermes-unlimited/pull/16) at commit [`deb7cc91`](https://github.com/rrglab/hermes-unlimited/commit/deb7cc91fd9c1dca1fbd858defaac532eb01d98e). The current public release extends the AGY core with a read-only community adapter directory and a bounded, host-approved chat webhook transport. Development remains private; published code is scoped, tested, and labeled with its actual operational maturity.

| Release | Source / purpose | What it contains | Distribution |
| --- | --- | --- | --- |
| **0.1.0-alpha.7** | `rrglab/hermes-unlimited` public source | Alpha.6 core plus free community adapter discovery and host-approved Slack-compatible outbound chat transport; 19 registered Hermes tools and three feedback hooks | Public source; **not yet approved or pinned in Nous catalog** |
| **0.1.0-alpha.6** | `rrglab/hermes-unlimited@9836141dedf12239e5558d4ccd6be910f657f34f` | AGY Company OS, Mission Engine, CAVO economics, Company Memory, Service Factory, A2UI, 17 native tools and three feedback hooks | Submitted for Nous catalog review in [PR #155722](https://github.com/NousResearch/hermes-agent/pull/155722); **not yet merged** |
| **0.1.0-alpha.5** | Earlier `rrglab` manifest version | Transitional public core before full AGY merge | Superseded |
| **0.1.0-alpha.4** | Original competition pin `nsolland/hermes-unlimited@09cd80374b994fa38abc5ed6b8904b98ac9b3554` | Bounded company/service/Kanban core with ten native tools | **Still pinned in the merged Nous plugin catalog** |

The [original hackathon catalog PR #153503](https://github.com/NousResearch/hermes-agent/pull/153503) merged on 13 November 2026 and remains pinned to `nsolland` alpha.4. [PR #155722](https://github.com/NousResearch/hermes-agent/pull/155722) proposes migrating the **existing** catalog entry to `rrglab` alpha.6 (17 tools, three hooks). Alpha.7 is a subsequent public-source release candidate with two additional adapter tools; it is **not** part of PR #155722. Catalog availability changes only after an independently reviewed and merged SHA-bump PR. Do not equate public GitHub source availability with catalog installation.

### Experimental Tool → Agent pipeline (public source)

A source-only, standalone [Tool → Capability → Junior Agent library](docs/TOOL_TO_AGENT_PIPELINE.md) is included for testing and community contributions. It normalizes Hermes/MCP/connector/OpenAPI tool definitions, generates one-tool draft Junior profiles, suggests test contracts, and detects contract changes through optional tenant-scoped SQLite fingerprints. It **does not install agents, connect accounts, choose models, or grant tool permissions**. This library is not registered as a new Hermes plugin tool in the current alpha; the tool count and catalog pin below are unchanged.

### What is implemented in the public core

- **Company OS / Mission Engine:** company charters, goal alignment, objective decomposition, scoped mission processing, retry and recovery controls. Hermes native mission execution requires explicit trusted-host authorization and a non-fixture worker; it fails closed without them.
- **CAVO economics:** routing, expected-value/cost/ROI estimates, budget and SLA checks. Offline estimates are not measured customer ROI.
- **Company Memory:** durable tenant-scoped experience with distinct `VERIFIED_OUTCOME` and `RECORDED_UNVERIFIED` classifications. The Thread is an optional external memory integration, not this embedded store.
- **Service Factory:** promotes qualifying verified, positive-value mission outputs into reusable service blueprints and catalog entries.
- **Customer and service lifecycle:** SQLite company registry, priced service publishing, durable request intake, per-tenant Kanban boards, idempotent dispatch/recovery and scoped result reads.
- **Connections and effects:** tenant-bound SMTP/Stripe connection contracts with vault references, explicit effect approval and non-delivery/non-settlement receipt semantics; there is no claim of live customer billing or payment capture.
- **Trust and adapters:** mandatory JustYou signed session/profile verification; optional tenant-scoped adapter eligibility; no receipt or model-generated claim authorizes an external effect by itself.
- **Captain's Bridge / A2UI:** read-only company, request, mission and readiness surfaces, with a scoped local bridge. This is not yet a complete customer-facing operations cockpit.
- **Hermes worker interface:** mission execution requires an explicitly host-provided worker and independent verifier. The plugin does not bootstrap Hermes internals or provide autonomous provider credentials; offline tests do **not** verify external provider operation.

**Evidence:** Initial AGY [PR #16](https://github.com/rrglab/hermes-unlimited/pull/16) passed Python 3.11–3.13 and CodeQL checks. Subsequent hardening [#22](https://github.com/rrglab/hermes-unlimited/pull/22), upstream catalog validation [#23](https://github.com/rrglab/hermes-unlimited/pull/23), and private-runtime removal [#24](https://github.com/rrglab/hermes-unlimited/pull/24) were merged. Hosted Hermes validation for alpha.6 passed capability matching, security scan and no-core-override checks. Alpha.7 retains its own CI/review requirement; earlier green results do not prove subsequent code. These results do not establish productive customer outcomes. See [AGY scope and limits](docs/AGY_COMPANY_ENGINE_SCOPE.md).

## Green Core — live acceptance (11 November 2026)

A bounded, synthetic end-to-end acceptance run on the **Acer Hermes Unlimited runtime** completed successfully. This validates a historical Acer runtime customer-flow integration. The AGY core is now public, but the historical acceptance is **not** evidence that the current public release has reproduced the same real-worker integration.

- Company `acceptance-1111` was created from the support-desk template with three isolated Hermes profiles (triage, responder, knowledge).
- Three company-scoped JustYou identities were verified; the registry, session renewer and learning timer were active.
- Native Hermes Kanban task `t_5d8dce9d` was assigned to the triage profile, executed by a real worker and completed with exit code `0` and a customer-support handoff summary.
- The result was harvested into company-scoped memory once. A subsequent harvest recognized the duplicate without creating a second record.
- The learned entry was classified `RECORDED_UNVERIFIED`: it is an agent self-report, **not independently verified evidence**. No external customer contact or external effect was performed.

**Historical acceptance verdict:** GREEN for synthetic company creation → identity isolation → task execution → handoff → scoped learning capture. **Still open:** independent output verification, externally reproducible customer onboarding and production readiness. The runtime acceptance is not a substitute for green local tests against the public repository's exact commit.

## Product roadmap and broader platform

**Our direction: AI-native companies as a service.**

The public AGY core now implements several of the foundations below. The table describes the **broader product direction**; it does not claim that every integration or UI is shipped and production-verified.

| Area | What we are building toward |
| --- | --- |
| **Captain's Bridge** | One operating cockpit for companies, teams, missions, communications, customers, and results. |
| **AI Crew** | Coordinated agent roles—helpers, specialists, routers, coordinators, and directors—with clear ownership and handoffs. |
| **Mission Control** | Company OS and mission execution logic are implemented; production-scale orchestration and measurable customer outcomes remain open. |
| **AI Bridge** | Model selection and economic routing logic are implemented; live multi-provider performance is not independently verified. |
| **Company Memory** | Embedded tenant-scoped store is implemented; The Thread remains optional external integration. |
| **Service Factory** | Reusable blueprints/catalog entries are implemented; externally verified customer delivery remains open. |
| **Business Engine** | CAVO calculations are implemented; live billing, measured ROI and real settlement remain open. |
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

This is the **broader customer journey**, not an assertion that every external channel, real-world effect or operational integration is live. Refer to *What is implemented in the public core* and *Boundary* for the code/evidence distinction.

## Version and distribution policy

- **Public source:** `plugin.yaml` is the canonical version for this repository (`0.1.0-alpha.7`). Tool and hook counts refer to that file, not to an older catalog pin.
- **Nous catalog:** installs remain pinned to reviewed commits. The approved entry is alpha.4; PR #155722 proposes alpha.6. Alpha.7 must receive a separate catalog review and exact SHA pin before it can be installed through `hermes plugins update hermes-unlimited`.
- **Compatibility:** `requires_hermes: ">=0.21.5"` is a declared minimum, not proof of external provider availability. A provider must configure JustYou, tenant-isolated boards, and explicit host approvals.
- **Maturity:** adapter discovery is metadata only. The chat-post adapter provides outbound delivery through an existing host-approved webhook; it is not a Slack/Ember agent, does not provide message readback and does not activate integrations automatically.

## Native Hermes tools (19 declared in alpha.7)

The tool registry in [`plugin.yaml`](plugin.yaml) is the authoritative install manifest. All operations are scoped by trusted Hermes provider, tenant and JustYou identity, not by model-supplied identity fields.

| Area | Tools |
| --- | --- |
| Provider/company | `hermes_unlimited_status`, `unlimited_company_create`, `unlimited_company_list`, `unlimited_company_task`, `unlimited_company_result` |
| Services/Kanban | `unlimited_service_publish`, `unlimited_service_request`, `unlimited_service_dispatch`, `unlimited_service_result` |
| Autonomous missions | `unlimited_mission_run`, `unlimited_company_cycle`, `unlimited_economic_evaluate` |
| Learning and production | `unlimited_memory_recall`, `unlimited_service_factory` |
| Interface and review | `unlimited_a2ui_surface`, `unlimited_socratic_council` |
| Connections | `unlimited_connection_manage` |
| Community adapters | `unlimited_adapter_discover` (read-only metadata), `unlimited_adapter_chat_post` (host-approved outbound webhook) |

The autonomous mission/cycle handlers require a trusted-host `authorize_mission` callback, a real host worker and an independent verifier/critic; missing capabilities are denied. The former in-process research adapter was excluded from the catalog-safe package; it remains recoverable from Git history before this release. Live execution must be supplied and authorized by the Hermes host. SMTP/Stripe effects are separately approval-gated. The Socratic Council is an advisory review, not an authority layer.

## Trusted profile setup

The plugin accepts trusted JustYou objects injected by Hermes (`ctx.justyou_session_store`, `ctx.justyou_resolver`) or connects to a JustYou service through a loopback-only session validator and Ed25519-signed profile binding cache. It fails closed if either verification is unavailable. The required secret is `HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN`, supplied through the host-scoped Hermes secret store. Configure the remaining non-secret values through the native Hermes plugin config:

- `HERMES_UNLIMITED_PROVIDER_ID`
- `HERMES_UNLIMITED_TENANT_ID`
- `HERMES_UNLIMITED_JUSTYOU_IDENTITY`
- `HERMES_UNLIMITED_REGISTRY_DB`
- Optional `HERMES_UNLIMITED_HERMES_CLI`

Without host injection, configure these additional non-secret plugin settings:

- `HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL` (`http://127.0.0.1:<port>` only)
- `JUSTYOU_BINDINGS_FILE` (private, signed JustYou binding export)
- `JUSTYOU_AUTHORITY_KEY_ID`
- `JUSTYOU_AUTHORITY_KEY_FILE` (private, public verification key for Ed25519)
- Optional `JUSTYOU_AUTHORITY_KIND` (defaults to `ed25519`; other values are rejected)

The Ed25519 binding verification implementation is included in `unlimited/authoritative_binding.py`; the plugin does not import an undeclared `protocol.authoritative_binding` package. `cryptography>=41,<47` is declared in `plugin.yaml`. A bindings JSON file is a cache, not authority; every binding and version announcement is signature-verified, and every operation revalidates the active session. No private keys, signed live identities, or tokens are bundled.

The session token is read from the trusted Hermes profile secret store; a token-file fallback is not implemented. Do not put credentials, customer data or keys in the plugin repository.

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

Local green tests remain canonical. Public GitHub Actions run offline unit tests on Python 3.11–3.13, CodeQL, and Hermes' upstream plugin catalog validator on supported Python 3.14. CI results are advisory and do not attest to live Hermes dispatch,
customer effects, or production readiness. Dependabot checks action updates.

## Installation and execution disclosures (catalog rule 13)

- **Network:** The 19 declared tools do not send mandatory telemetry. Host-provisioned workers and explicitly authorized SMTP/Stripe adapters may contact selected external services; ComfyUI remains an optional, unregistered client. Network calls may incur external provider charges.
- **Local files and persistence:** Provider, company, service and customer-request metadata are stored in the configured SQLite registry. The JustYou verifier may read a signed binding export and public verification-key file from explicitly configured paths, never by scanning arbitrary files.
- **Shell and background work:** The plugin invokes the local `hermes kanban` CLI to create and read worker tasks on an explicitly provisioned tenant board. Hermes, not the plugin, owns scheduling and workers. No additional privileged daemon, unattended shell job or self-updater is installed.
- **Secrets:** Identity, tenant and authority are resolved from host/profile scope; no API credentials, private keys or bearer tokens ship with the repository. Secrets remain in the host's configured stores.
- **Approvals:** No auto-approval, disabling of Hermes guards or core override. Missing authorization fails closed. The plugin may submit work only after trusted JustYou verification.
- **Limits:** No production-verified payment settlement or customer fulfillment is claimed. Verified local logic is distinct from live external delivery and measured business value. A Hermes task marked `done` is not proof of customer acceptance.

## Boundary

Hermes owns the base agent runtime, channels, scheduler and Kanban execution. JustYou supplies verified identity. **AGY is the Hermes Unlimited functional company core**: Company OS, missions, economic decisions, embedded Company Memory, service production and evidence-aware results. Task state and internal receipts are not independent authority. The Thread external memory, full Captain's Bridge product UI, optional Jackets integrations, Veritas and commercial live backends remain separate, optional or partially implemented; their presence must not be inferred from the bundled core.

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


## Free community adapter directory (alpha.7 preview)

Hermes Unlimited can index community-provided adapters for existing services
without reimplementing those services. The first entries cover Ember, Slack,
GitHub, Cloudflare, Outlook, Matrix, Zulip and Mattermost.

Commands:
    python -m unlimited.community_adapters list
    python -m unlimited.community_adapters inspect ember
    python -m unlimited.community_adapters scaffold my-service --directory adapters/community

The native Hermes tool `unlimited_adapter_discover` is read-only. Starter entries
are catalog-only, not working service connections. Contributions and discovery
are free; provider subscriptions and API usage may have their own costs.
JustYou remains mandatory and production admission is controlled by the
existing tenant-scoped host adapter gate.
See adapters/community/README.md for contributions.


A thin outbound Slack-compatible webhook transport is also implemented as
`unlimited_adapter_chat_post`, using existing Hermes JustYou identity,
tenant-scoped admission and host-managed destinations. It does not authorize
itself, run Ember/Slack, or claim message readback. The default community
catalog entries remain non-executable until independently reviewed and
approved by the existing host adapter gate.
