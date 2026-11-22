"""Host-scoped, read-only specialist capability previews.

A registry record means only that the host reported a definition; it does not
prove a tool is callable, authorized, safe, or independently verified.
"""
from __future__ import annotations

import hashlib
import json
import re

TOOLSET = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def inspect_host_registry(registry, *, toolset, operation, objective=None, selected_tools=None,
                          source="HOST_REPORTED_SCHEMA"):
    if not isinstance(toolset, str) or not TOOLSET.fullmatch(toolset):
        raise ValueError("INVALID_TOOLSET")
    if operation not in ("discover", "propose"):
        raise ValueError("INVALID_OPERATION")
    if source not in ("HOST_REPORTED_SCHEMA", "LOCAL_PLUGIN_DECLARATION_ONLY"):
        raise ValueError("UNKNOWN_DISCOVERY_SOURCE")
    if registry is None or not all(callable(getattr(registry, name, None)) for name in
        ("get_all_tool_names", "get_toolset_for_tool", "get_definitions")):
        raise PermissionError("TRUSTED_HERMES_REGISTRY_REQUIRED")
    names = registry.get_all_tool_names()
    if not isinstance(names, (list, tuple, set)) or len(names) > 500:
        raise ValueError("HOST_REGISTRY_INVALID")
    if any(not isinstance(n, str) or not n or len(n) > 128 for n in names):
        raise ValueError("HOST_REGISTRY_SCOPE_INVALID")
    names = sorted(n for n in names if n != "unlimited_specialist_factory" and
                   registry.get_toolset_for_tool(n) == toolset)
    if len(names) > 100:
        raise ValueError("HOST_REGISTRY_SCOPE_INVALID")
    if len(set(names)) != len(names):
        raise ValueError("HOST_REGISTRY_DUPLICATE")
    definitions = registry.get_definitions(set(names), quiet=True)
    if not isinstance(definitions, (list, tuple)) or len(definitions) > 100:
        raise ValueError("HOST_DEFINITIONS_INVALID")
    catalog = {}
    for definition in definitions:
        if not isinstance(definition, dict) or not isinstance(definition.get("function"), dict):
            raise ValueError("HOST_DEFINITION_INVALID")  # noqa: TRY004 - stable untrusted schema contract
        info = definition["function"]
        name = info.get("name")
        params = info.get("parameters")
        if name not in names or name in catalog or not isinstance(params, dict) or params.get("type") != "object":
            raise ValueError("HOST_DEFINITION_UNEXPECTED")
        digest = hashlib.sha256(json.dumps({"name": name, "parameters": params},
                        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        catalog[name] = {"name": name, "schema_digest": digest, "effect": "unknown",
                         "availability_verified": False, "execution_authorized": False}
    if len(catalog) != len(names):
        raise ValueError("HOST_DEFINITION_MISSING")
    entries = [catalog[n] for n in names]
    if operation == "discover":
        if objective is not None or selected_tools is not None:
            raise ValueError("DISCOVER_ARGUMENTS_INVALID")
        return {"capabilities": entries, "source": source,
                "authority": "NONE", "execution_authorized": False}
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 2048:
        raise ValueError("OBJECTIVE_INVALID")
    if not isinstance(selected_tools, list) or not (1 <= len(selected_tools) <= 30) or any(
        not isinstance(n, str) or n not in catalog for n in selected_tools
    ) or len(set(selected_tools)) != len(selected_tools):
        raise ValueError("UNDISCOVERED_OR_DUPLICATE_TOOL")
    draft = {"objective": objective.strip(), "tools": selected_tools,
             "capability_digests": [catalog[n]["schema_digest"] for n in selected_tools]}
    return {"proposal": draft, "status": "DRAFT_UNVERIFIED", "source": source,
            "effects_reviewed": False, "availability_verified": False,
            "authority": "NONE", "execution_authorized": False}

class LocalPluginDeclarations:
    """Explicitly declared schemas of this plugin, not live Hermes registry state."""

    def __init__(self, schemas):
        if not isinstance(schemas, (list, tuple)):
            raise ValueError("PLUGIN_DECLARATIONS_INVALID")  # noqa: TRY004 - stable schema contract
        self._schemas = {}
        for schema in schemas:
            if not isinstance(schema, dict) or not isinstance(schema.get("name"), str):
                raise ValueError("PLUGIN_DECLARATION_INVALID")  # noqa: TRY004 - stable schema contract
            if schema["name"] in self._schemas:
                raise ValueError("PLUGIN_DECLARATION_DUPLICATE")
            self._schemas[schema["name"]] = schema

    def get_all_tool_names(self):
        return list(self._schemas)

    def get_toolset_for_tool(self, name):
        return "hermes_unlimited" if name in self._schemas else None

    def get_definitions(self, names, quiet=False):
        if set(names) - set(self._schemas):
            raise ValueError("UNDECLARED_PLUGIN_TOOL")
        return [{"function": self._schemas[name]} for name in sorted(names)]
