"""Native Hermes Tool -> Junior discovery entrypoint; read-only and fail-closed.

Tool schemas are sourced from Hermes or a trusted host, never from a model
argument. No provider credential or authorization flag is accepted here.
"""
from __future__ import annotations

import json

SCHEMA = {
    "name": "unlimited_junior_discovery",
    "description": "Discover installed Hermes/MCP/connector/OpenAPI tools and generate tenant-scoped draft junior agents; optionally sync schema fingerprints. Never activates agents or accounts.",
    "parameters": {"type": "object", "properties": {
        "operation": {"type": "string", "enum": ["discover", "sync"]},
        "source": {"type": "string", "enum": ["hermes", "connector", "mcp", "openapi"]},
        "toolset": {"type": "string", "maxLength": 100},
        "query": {"type": "string", "maxLength": 160},
        "namespace": {"type": "string", "maxLength": 160},
    }, "required": ["operation", "source"], "additionalProperties": False},
}


def _discover_host_tools(ctx, source: str, args: dict) -> tuple[str, list[dict]]:
    from .junior_pipeline_store import source_key
    if source == "hermes":
        key = source_key(source, toolset=args.get("toolset"))
        if set(args) - {"operation", "source", "toolset"}:
            raise ValueError("INVALID_DISCOVERY_ARGUMENTS")
        # Use the registry provided by Hermes, never dynamically run tools.
        registry = getattr(ctx, "tool_registry", None)
        if registry is None:
            from tools.registry import registry
        names = [name for name in registry.get_all_tool_names()
                 if registry.get_toolset_for_tool(name) == args["toolset"]
                 and name != SCHEMA["name"]]
        if len(names) > 100:
            raise ValueError("TOO_MANY_DISCOVERED_TOOLS")
        definitions = registry.get_definitions(set(names), quiet=True)
        schemas = [entry.get("function", {}) for entry in definitions]
    elif source == "connector":
        key = source_key(source, query=args.get("query"))
        if set(args) - {"operation", "source", "query"}:
            raise ValueError("INVALID_DISCOVERY_ARGUMENTS")
        from tools.connectors.search import connector_entries_by_group
        groups, failure = connector_entries_by_group([args["query"]])
        if failure:
            raise PermissionError("HERMES_CONNECTOR_UNAVAILABLE")
        schemas = [entry.schema["function"] for entry in groups[0]]
    else:
        key = source_key(source, namespace=args.get("namespace"))
        if set(args) - {"operation", "source", "namespace"}:
            raise ValueError("INVALID_DISCOVERY_ARGUMENTS")
        # Account-owned runtime must have discovered schema without trusting
        # raw model-authored JSON or fetching arbitrary URLs.
        reader = getattr(ctx, "discover_junior_tool_schemas", None)
        if not callable(reader):
            raise PermissionError("HERMES_TRUSTED_DISCOVERY_UNAVAILABLE")
        schemas = reader(source, args["namespace"])
    if not isinstance(schemas, (list, tuple, dict)) or not schemas:
        raise ValueError("NO_DISCOVERED_TOOLS")
    return key, schemas


def register_junior_discovery(ctx, scoped_secret, scoped_identity):
    def handler(args=None, **_kwargs):
        if not isinstance(args, dict) or set(args) - set(SCHEMA["parameters"]["properties"]):
            return json.dumps({"ok": False, "reason": "INVALID_ARGUMENTS"})
        if args.get("operation") not in ("discover", "sync") or args.get("source") not in (
                "hermes", "connector", "mcp", "openapi"):
            return json.dumps({"ok": False, "reason": "INVALID_ARGUMENTS"})
        try:
            tenant, evidence = scoped_identity()
            if evidence.get("verified") is not True or not evidence.get("identity"):
                raise PermissionError("JUSTYOU_NOT_VERIFIED")
            provider = scoped_secret("HERMES_UNLIMITED_PROVIDER_ID", "")
            if not provider:
                raise PermissionError("PROVIDER_NOT_CONFIGURED")
            from .tool_to_agent_pipeline import build_pipeline
            key, schemas = _discover_host_tools(ctx, args["source"], args)
            if args["operation"] == "sync":
                db_path = scoped_secret("HERMES_UNLIMITED_REGISTRY_DB", "")
                if not db_path:
                    raise PermissionError("REGISTRY_NOT_CONFIGURED")
                from .junior_pipeline_store import sync_discovery
                out = sync_discovery(db_path, provider, tenant, key,
                    lambda previous: build_pipeline(tenant, args["source"], schemas, previous=previous))
            else:
                out = build_pipeline(tenant, args["source"], schemas)
            return json.dumps(out, sort_keys=True)
        except (PermissionError, ValueError, RuntimeError, TypeError, KeyError, ImportError, OSError) as exc:
            # Never return exception message or echo any discovered description,
            # connection identity, account metadata or credentials on failure.
            return json.dumps({"ok": False, "reason": type(exc).__name__}, sort_keys=True)

    ctx.register_tool(name=SCHEMA["name"], toolset="hermes_unlimited", schema=SCHEMA, handler=handler)
