# Contributing to Hermes Unlimited

Hermes Unlimited welcomes external contributions to its **public, reusable components**: adapters, interoperability layers, tests, documentation, diagnostics, and agent workflows.

The repository has a protected-in-practice competition baseline: **do not push directly to main**. Propose changes using a fork and a pull request. Maintainers review and merge only after local verification. An open PR does not imply release or inclusion in a competition submission.

## Start here

1. Check existing issues and `docs/PUBLIC_CONTRIBUTION_INVENTORY.md`; open an issue for changes that affect public APIs or dependencies.
2. Fork the repository and create a branch named `feat/<topic>`, `fix/<topic>`, or `docs/<topic>`.
3. Keep a PR limited to one coherent change; include its user-facing use case.
4. Provide tests that work from a clean public checkout, with fakes or local mock servers. No credentials or private packages.
5. Run `python -m unittest discover -s tests -v` locally. Document actual results, runtime and commit SHA; never claim tests were run if they were not.
6. Open a PR using the supplied checklist. Maintainers review correctness, isolation, safety, licenses and usability.
7. Do not merge your own PR or assume an external contribution is approved.

## Third-party adapter standard

Each adapter should contain:
- A stable, documented interface and supported upstream version or API.
- A clean installation path, complete example, and explicit requirements.
- Credential injection via trusted profile-scoped host configuration; never persist or print raw secrets.
- Bounded timeouts, typed errors, retries only where safe, and clear handling for unavailable services.
- Request idempotency when possible; no false claims of completion from a submission acknowledgment.
- Tenant and resource ownership checks before actions and readback.
- Unit/contract tests for successes, negative scope, timeouts, malformed responses, duplicate submissions and failed upstream requests.
- Upstream URL, exact dependency version and SPDX license identification. Don't vendor third-party source without license analysis and attribution.

An adapter that only declares metadata must be labelled `catalog-only`, not production-ready.

## Contribution boundaries

You retain copyright in your contributions and submit them under this repository's Apache-2.0 license, unless a contribution is clearly designated as independently licensed and approved by maintainers. You must have the right to submit the code. Cite third-party projects and preserve their licenses. In particular, don't paste AGPL/GPL source into Apache-licensed modules without review.

Never submit customer records, contact details, access tokens, private endpoints, proprietary modules, copied conversations, or unlicensed media. Use synthetic test fixtures.

## Review and release

Reviewers check reproducible local tests, security and licensing, readable documentation, and real use. Maintainers may reject an incompatible integration or request a smaller change.

PRs targeting `main` must not be merged without an explicit release decision. New functionality can be developed on separate feature branches without changing the competition baseline.

For security-sensitive findings, **do not open a public exploit issue or post credentials**. Contact the maintainers privately using the repository's security reporting mechanism if enabled; otherwise use the contact address shown in the README without including secrets in initial contact.


## Free community adapters

Generate a proposal with:
    python -m unlimited.community_adapters scaffold my-service --directory adapters/community

Share the resulting manifest, API contract implementation, test cases and
documentation via pull request. Catalog discovery never installs or authorizes
code. JustYou and the existing per-tenant adapter gate remain mandatory.
Apache-2.0 covers contributions to this repo; third-party costs and licenses
must be disclosed separately. Do not mark your own proposal approved.


Validate all manifests with
`python -m unlimited.community_adapters validate`. A scaffold now includes
an inert example adapter.py to help contributors package their own API
integration. It is intentionally not auto-imported. The working outbound
webhook adapter in unlimited/webhook_delivery.py illustrates the host-
injected capability and identity boundary; it may be reused under Apache-2.0.
