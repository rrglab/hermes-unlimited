# AI Workforce — qualification and work mandates (preview)

**Don't just deploy agents. Qualify their work, verify their competence, and keep permissions explicit.**

AI Workforce is a proposed **optional** Hermes Unlimited integration for customers who want traceable digital-worker skills and bounded assignments. Existing Hermes models, profiles, tools, subscriptions, and company workflows remain the runtime; AI Workforce does not create a parallel model or agent platform.

## How it is designed to work

- **Passport:** references the assessed model configuration and its provenance. Changing the deployed model, adapter, or relevant configuration can invalidate prior qualifications.
- **EmplAI:** canonical capability identity, verification, domain-specific Shu–Ha–Ri assessment, and matching against work requirements. A candidate match is not permission to act.
- **relAIon:** append-only developmental and observed-outcome evidence lineage. It does not assign work or grant tool rights.
- **JACKETS:** issued Jacket mandate, scoped Tool Belt, required Badge, Room rules and live Session. The operator-facing Work Permit is a view of this state, not a second permission system.
- **Hermes Unlimited:** consumes optional external qualification and admission checks before selected job/mission handoffs. Hermes and its existing JustYou bindings still own customer profile and task orchestration.
- **REHT / applicable effect gateway:** any consequential action still needs its own fresh authorization. A Passport, a competence grade, or a successful JACKETS preflight never creates an effect permit.

## Who benefits

Providers serving customer support, analysis, software delivery, operational research, and other tasks where the same agent may be useful in one domain but unqualified in another. The objective is to make *what the worker has actually demonstrated* visible, separate from *what the worker is authorized to do*.

## Release status — not installed in this public plugin

This page is a **product preview, not release documentation for working public plugin functionality**. As of 15 November 2026, the opt-in workforce adapter exists in private `nsolland/hermes-unlimited-dev` and was tested locally. The released `rrglab/hermes-unlimited` core does **not** ship EmplAI/JACKETS integration, external model attestors, production trusted witnesses, or automatic tenant onboarding for the feature.

The integration remains blocked from public functional release until:

1. A reproducible public install route (including pinned, license-reviewed optional EmplAI, relAIon and JACKETS dependencies) and clean-install tests exist.
2. Native Hermes service dispatch, mission and T3 handoffs are tested with actual configured host adapters, isolation and bypass cases, not solely mock evidence.
3. Qualification policy, trusted evidence verifiers, model identity measurement and current revocation are reviewed for the intended deployment class.
4. Public API, backwards compatibility, tenant opt-in, uninstallation, and the JustYou fail-closed boundary pass tests against the **exact** proposed public commit.
5. A separate release decision is recorded and the approved public artifact is verified after publication.

See [EmplAI](https://github.com/nsolland/emplai), [relAIon](https://github.com/nsolland/relaion), [JACKETS](https://github.com/nsolland/jackets), and the [workforce ownership map](https://github.com/nsolland/valo-core/blob/main/WORKFORCE_INTEGRATION_MAP.md).
