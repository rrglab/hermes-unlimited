# OpenCyber Harness adoption (bounded, not production verified)

Upstream: https://github.com/mitkox/opencyber
Pinned study commit: `daf274cb61996fd14b8a97df332457e2970b5b63`.
Upstream license: Apache-2.0 (separate third-party terms apply to bundled tools).

## What is adopted
- MCP tool metadata: declared `shape`, `effects`, `scope`, engagement requirement, target-derived content flag.
- Result envelope: `ok`, exact tool binding, `coverage`, `limitations`, `provenance`, evidence SHA-256, structured refusal.
- Compact MCP discovery model, to prevent loading hundreds of full tool schemas into agent context.
- Fail-closed schema handling; no false claim that a successful call implies complete coverage or independently verified target state.

## Deployment boundary
This is a **parser and adapter only**, not a live MCP connection, not execution authorization, and not evidence verification.
A future Hermes host integration can consume capabilities through Toolshed, have an independent authority check before tool effects, and associate resulting evidence with Veritas. No authority is inferred from OpenCyber metadata.

For a dedicated Linux amd64 lab, use upstream's pinned release-image digest and documented **blue-team offline** launcher profile; the release tag alone is not immutable. No live targets, device passthrough, network egress, host networking, shared multi-tenant volume, or arbitrary `oc_bash`/`oc_python` by default. In-process scope checks and an audit hash chain are insufficient as security boundaries.

Read and comply with upstream `docs/SECURITY_MODEL.md`, `docs/CONTRACTS.md`, `docs/MCP_INTEGRATION.md`, and `THIRD_PARTY_NOTICES.md`. Do not copy its Docker image or third-party binaries into Unlimited without verifying redistribution licenses.

## Verify
```sh
python -m unittest discover -s integrations/opencyber -p 'test_*.py' -v
```

## Next verification gate
On Acer: start official beta with strict offline blue-team profile, check image digest, run `opencyber-doctor --json` and `opencyber-mcp --self-test`, read `oc_catalog` (including contract digest), then run a synthetic supplied-file test with no external network. This gate is **not yet completed**.
