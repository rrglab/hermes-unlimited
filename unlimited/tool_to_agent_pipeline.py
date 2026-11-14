"""Vendor-neutral tool -> capability -> draft junior pipeline.

Tool data is untrusted. This builds reviewable, deterministic draft proposals,
not runnable agents, OAuth connections, permissions, or model certifications.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from hashlib import sha256
import json
import re

# Public core: intentionally independent of private specialist factories.
# Schema descriptions are untrusted and never authorize the corresponding tool.
def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

@dataclass(frozen=True)
class Capability:
    tool_name: str
    description: str
    parameters: Mapping[str, Any]
    required: tuple[str, ...]
    schema_digest: str


def discover_capabilities(schemas: Sequence[Mapping[str, Any]]) -> tuple[Capability, ...]:
    entries: list[Capability] = []
    seen: set[str] = set()
    for raw in schemas:
        name = raw["name"]
        params = raw["parameters"]
        props = params.get("properties", {})
        required = params.get("required", [])
        if (not isinstance(props, dict) or not isinstance(required, list)
                or any(not isinstance(k, str) or k not in props for k in required)):
            raise ValueError("INVALID_TOOL_PARAMETERS")
        if name in seen:
            raise ValueError("DUPLICATE_TOOL_NAME")
        seen.add(name)
        description = raw.get("description", "")
        entries.append(Capability(name, description, params, tuple(required),
                          _digest({"name": name, "parameters": params,
                                   "description": description})))
    return tuple(entries)


_EFFECT_READ = re.compile(r"^(get|list|search|find|read|fetch|query|inspect|describe|lookup|retrieve|view)_", re.I)
_EFFECT_WRITE = re.compile(r"^(create|update|delete|remove|send|post|put|patch|upload|write|edit|publish|transfer|pay|refund|execute|run|trigger|start|stop)_", re.I)


def normalize_tool_schemas(source: str, schemas: Sequence[Mapping[str, Any]], *, max_tools: int = 100) -> tuple[Capability, ...]:
    """Accept already-discovered Hermes, MCP, OpenAPI or host-provided tool schemas.

    We deliberately do not fetch arbitrary URLs, resolve $refs, or run code from
    discovered specifications. A host parser must supply bounded function schemas.
    """
    if source not in ("hermes", "mcp", "openapi", "connector"):
        raise ValueError("UNSUPPORTED_TOOL_SOURCE")
    if not isinstance(schemas, (list, tuple)) or len(schemas) > max_tools or not schemas:
        raise ValueError("INVALID_DISCOVERY_SIZE")
    rows = []
    for raw in schemas:
        if not isinstance(raw, dict):
            raise ValueError("INVALID_TOOL_SCHEMA")
        fn = raw.get("function", raw)
        if not isinstance(fn, dict):
            raise ValueError("INVALID_TOOL_SCHEMA")
        if source == "openapi" and "operationId" in fn:
            name = fn["operationId"]
            description = fn.get("summary", fn.get("description", ""))
            params = fn.get("parameters_schema", fn.get("inputSchema"))
        else:
            name = fn.get("name")
            description = fn.get("description", "")
            params = fn.get("parameters", fn.get("inputSchema"))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", name):
            raise ValueError("INVALID_TOOL_NAME")
        if not isinstance(params, dict) or params.get("type") != "object":
            raise ValueError("INVALID_TOOL_SCHEMA")
        rows.append({"name": name, "description": str(description)[:1500],
                     "parameters": params, "effect": "unknown"})
    return discover_capabilities(rows)


def extract_openapi_tools(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract bounded inline OpenAPI operations; never fetch URLs or resolve refs."""
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        raise ValueError("INVALID_OPENAPI_VERSION")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or len(paths) > 80:
        raise ValueError("INVALID_OPENAPI_PATHS")
    tools: list[dict[str, Any]] = []
    for path, item in sorted(paths.items()):
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            raise ValueError("INVALID_OPENAPI_PATH")
        for method, op in sorted(item.items()):
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(op, dict) or "$ref" in op:
                raise ValueError("OPENAPI_REFERENCES_UNSUPPORTED")
            name = op.get("operationId")
            if not name:
                continue
            params = op.get("parameters", [])
            if not isinstance(params, list) or len(params) > 40:
                raise ValueError("INVALID_OPENAPI_PARAMETERS")
            properties: dict[str, Any] = {}
            required: list[str] = []
            for param in params:
                if not isinstance(param, dict) or "$ref" in param:
                    raise ValueError("OPENAPI_REFERENCES_UNSUPPORTED")
                key, schema = param.get("name"), param.get("schema")
                if not isinstance(key, str) or not isinstance(schema, dict) or "$ref" in schema:
                    raise ValueError("INVALID_OPENAPI_PARAMETER")
                properties[key] = schema
                if param.get("required") is True:
                    required.append(key)
            tools.append({"operationId": name, "summary": op.get("summary", ""),
                          "parameters_schema": {"type": "object", "properties": properties,
                                                "required": required},
                          "http_method": method.upper(), "http_path": path})
            if len(tools) > 100:
                raise ValueError("TOO_MANY_OPENAPI_OPERATIONS")
    if not tools:
        raise ValueError("NO_OPENAPI_OPERATIONS")
    return tools


def infer_effect(name: str) -> str:
    """Heuristic is informational only; never authorization."""
    short = name.split("__")[-1].split(".")[-1]
    if _EFFECT_READ.match(short):
        return "read"
    if _EFFECT_WRITE.match(short):
        return "write"
    return "unknown"


def build_pipeline(tenant: str, source: str, schemas: Sequence[Mapping[str, Any]],
                   *, previous: Mapping[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(tenant, str) or not tenant.strip():
        raise ValueError("TENANT_REQUIRED")
    if source == "openapi" and isinstance(schemas, dict):
        schemas = extract_openapi_tools(schemas)
    capabilities = normalize_tool_schemas(source, schemas)
    previous = previous or {}
    if not isinstance(previous, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                            for k, v in previous.items()):
        raise ValueError("INVALID_PRIOR_SNAPSHOT")
    out = []
    hashes = {}
    for cap in sorted(capabilities, key=lambda c: c.tool_name):
        hashes[cap.tool_name] = cap.schema_digest
        effect_hint = infer_effect(cap.tool_name)
        # Expose model-test preparation, but never label a candidate ready to execute.
        out.append({
            "agent_id": "junior-" + _digest({"tenant": tenant, "source": source,
                                              "name": cap.tool_name, "schema": cap.schema_digest})[:18],
            "source": source,
            "tool": cap.tool_name,
            "capability": {"description": cap.description, "required_parameters": list(cap.required),
                           "schema_digest": cap.schema_digest},
            "effect_hint_unverified": effect_hint,
            "agent_spec": {
                "kind": "hermes-tool-junior-v1",
                "role": "Single-tool junior for " + cap.tool_name,
                "tool_allowlist": [cap.tool_name],
                "model": None,
                "model_selection": "QUALIFICATION_REQUIRED",
                "instruction_contract": "Use only the assigned tool for the stated task. "
                                        "Do not claim success without a tool result. "
                                        "Escalate ambiguous requests or unauthorized effects.",
                "delegation": "ESCALATE_TO_PARENT_SPECIALIST",
                "schema_pin": cap.schema_digest,
                "connection": "HERMES_HOST_OWNED_ONLY",
            },
            "change": ("NEW" if cap.tool_name not in previous else
                       "CHANGED" if previous[cap.tool_name] != cap.schema_digest else "UNCHANGED"),
            "status": "DRAFT_UNVERIFIED",
            "has_credentials": False, "model_qualified": False, "execution_authorized": False,
            "test_plan": {"valid_minimal_arguments": list(cap.required),
                          "negative_cases": ["missing_required_argument", "invalid_argument_type",
                                             "unavailable_connection", "unauthorized_identity",
                                             "schema_digest_changed"],
                          "task_evaluation": "REQUIRES_INDEPENDENT_VERIFIED_TRIALS",
                          "model_selection": "CHEAPEST_QUALIFIED_NOT_PRESELECTED"},
            "next": ["host_effect_review", "account_connection_check", "task_evals",
                     "model_qualification", "host_authorization", "bounded_activation"],
        })
    removed = sorted(set(previous) - set(hashes))
    return {"tenant": tenant, "source": source, "count": len(out), "candidates": out,
            "snapshot": hashes, "removed_tools": removed, "revalidate": bool(removed or any(
                c["change"] == "CHANGED" for c in out)), "execution_authorized": False}
