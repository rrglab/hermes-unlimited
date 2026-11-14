# Tool → Capability → Junior Agent (experimental public library)

Hermes Unlimited can build **draft** one-tool Junior Agent specifications from existing Hermes tool schemas, MCP tools, connector metadata, or supplied OpenAPI 3.x specifications. This is a reusable Python library, not a second agent runtime. Alpha.8 registers `unlimited_junior_discovery` as a native Hermes tool, but does **not** automatically install generated agents.

## Goal

Stop hand-writing or updating a new agent for every SaaS API, MCP server, or upstream tool. Discover the underlying tool, normalize its contract, generate a narrowly scoped draft agent, generate negative test requirements, and detect schema changes. Later stages—live account connection, test execution, model qualification, approval and deployment—remain Hermes-host-controlled.

## Minimal example

```python
from unlimited.tool_to_agent_pipeline import build_pipeline

schema = [{
    "name": "gmail__list_messages",
    "description": "List messages matching a search query",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"]
    }
}]
first = build_pipeline("demo-tenant", "mcp", schema)
assert first["candidates"][0]["status"] == "DRAFT_UNVERIFIED"
assert first["candidates"][0]["agent_spec"]["tool_allowlist"] == ["gmail__list_messages"]
assert first["candidates"][0]["execution_authorized"] is False

# Run discovery again; detect changed and removed tool contracts.
second = build_pipeline("demo-tenant", "mcp", schema, previous=first["snapshot"])
assert second["candidates"][0]["change"] == "UNCHANGED"
```

For an existing **host-owned** SQLite database, use `sync_discovery(db_path, provider, tenant, source_key, callback)` from `unlimited.junior_pipeline_store`. This persists only names and fingerprints, scoped by provider, tenant and source. It does not start a scheduler or authorize any tool call. Invoke it only in trusted host code; never expose arbitrary storage paths to agents.

## Hermes native plugin integration (alpha.8)

When Hermes Unlimited is installed and JustYou validates the current profile, agents can call the **read-only discovery** operation:

```json
{"operation":"discover","source":"hermes","toolset":"file"}
```

To record and compare tool schema fingerprints in the profile's configured provider/tenant registry, invoke:

```json
{"operation":"sync","source":"hermes","toolset":"file"}
```

The same tool supports `source="connector"` with `query="search email"`, delegated to the existing Hermes managed-connector catalog. For `source="mcp"` and `source="openapi"`, a **trusted host** must provide `discover_junior_tool_schemas(source, namespace)`. Models cannot submit a raw schema, connection ID, OAuth token, API key, storage path, provider ID, tenant ID, or permission boolean to this native tool. An unavailable integration fails closed; it is not treated as installed. Neither `discover` nor `sync` qualifies a model or grants execution rights.

## Supported inputs

- `hermes`: schemas already collected from the running Hermes registry.
- `mcp`: standard MCP tool names/descriptions/input schemas, normalized without executing them.
- `connector`: schemas returned by the customer's existing connected-provider discovery interface; **no OAuth tokens enter this library**.
- `openapi`: inline OpenAPI 3.x paths and operation IDs, or normalized function schemas. Unsupported `$ref` parameters are rejected; no URLs are fetched.

## What is and is not automated

| Stage | Public implementation |
| --- | --- |
| Normalize schemas | Yes |
| Compute stable tool contract digests | Yes |
| Generate one-tool Junior draft | Yes |
| Suggest effect classification | Heuristic only, not authority |
| Generate static positive/negative test contract | Yes |
| Compare new/changed/removed tools | Yes |
| Persist scoped snapshots when trusted host calls it | Yes |
| Connect customer OAuth/API account | No: existing Hermes host owns this |
| Execute evals and qualify cheapest suitable model | Not yet |
| Grant execution permission | Never from generated metadata |
| Schedule recurring discovery | Not installed in this public package |

`DRAFT_UNVERIFIED` explicitly means a proposed configuration, not a working service. New or changed API schemas require new review and qualification. Accounts, tokens, role permissions, approval and execution remain outside this library. Avoid inventing an adapter if Hermes already offers the underlying tool.

## Contributions

Start from an actual MCP tool schema or OpenAPI operation, not from an agent persona. Include safe synthetic fixtures and tests for malformed schemas, tenant isolation, breaking contract changes, permission denials and connector errors. Reuse the free [community adapter catalog](../adapters/community/README.md) when an existing connector can be described rather than reimplemented.
