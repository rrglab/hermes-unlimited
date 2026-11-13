"""Read-only A2UI 1.0 surfaces for Hermes Unlimited.

No execution privileges or identity assertions are conveyed by UI messages.
An authenticated Hermes host supplies the trusted JustYou identity and the
existing ProviderStore performs tenant authorization before data is exported.
The host owns transport, renderer registration, and event dispatch.
"""
from __future__ import annotations

import json
import re

BASIC_CATALOG = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
_SAFE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_BYTES = 65536
_ALLOWED_COMPONENTS = frozenset({"Column", "Row", "Card", "Text", "Button"})


class A2UIValidationError(ValueError):
    """A2UI envelope cannot be safely published."""


def _surface_id(value):
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise A2UIValidationError("INVALID_SURFACE_ID")
    return value


def validate_envelope(envelope):
    """Validate our restricted outgoing v1.0 subset (not a full spec validator)."""
    try:
        raw = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise A2UIValidationError("INVALID_JSON") from exc
    if len(raw.encode("utf-8")) > _MAX_BYTES:
        raise A2UIValidationError("MESSAGE_TOO_LARGE")
    if not isinstance(envelope, dict) or envelope.get("version") != "1.0":
        raise A2UIValidationError("UNSUPPORTED_VERSION")
    keys = set(envelope) - {"version"}
    if len(keys) != 1 or not keys <= {"createSurface", "updateDataModel", "deleteSurface"}:
        raise A2UIValidationError("UNSUPPORTED_ENVELOPE")
    kind = next(iter(keys))
    body = envelope[kind]
    if not isinstance(body, dict):
        raise A2UIValidationError("INVALID_BODY")
    _surface_id(body.get("surfaceId"))
    if kind == "createSurface":
        if set(body) != {"surfaceId", "catalogId", "components", "dataModel", "sendDataModel"}:
            raise A2UIValidationError("INVALID_SURFACE_FIELDS")
        if body["catalogId"] != BASIC_CATALOG or body["sendDataModel"] is not False:
            raise A2UIValidationError("INVALID_CATALOG_OR_DATA_EXPORT")
        if not isinstance(body["dataModel"], dict):
            raise A2UIValidationError("INVALID_DATA_MODEL")
        components = body["components"]
        if not isinstance(components, list) or not components or len(components) > 256:
            raise A2UIValidationError("INVALID_COMPONENTS")
        ids = []
        for node in components:
            if not isinstance(node, dict) or not _SAFE_ID.fullmatch(str(node.get("id", ""))):
                raise A2UIValidationError("INVALID_COMPONENT_ID")
            if node.get("component") not in _ALLOWED_COMPONENTS:
                raise A2UIValidationError("COMPONENT_NOT_ALLOWED")
            ids.append(node["id"])
        if len(set(ids)) != len(ids) or "root" not in ids:
            raise A2UIValidationError("INVALID_COMPONENT_TREE")
        for node in components:
            for key in ("children", "child"):
                if key in node:
                    children = node[key] if key == "children" else [node[key]]
                    if not isinstance(children, list) or any(x not in ids for x in children):
                        raise A2UIValidationError("INVALID_CHILD_REFERENCE")
            # This adapter is an output builder, not a general A2UI parser.
            # Lock down every emitted field to prevent executable functions,
            # bindings or actions from being smuggled through passive nodes.
            fields = {
                "Column": {"id", "component", "children"},
                "Row": {"id", "component", "children"},
                "Card": {"id", "component", "child"},
                "Text": {"id", "component", "text"},
            }
            if node["component"] == "Button":
                raise A2UIValidationError("INTERACTIVE_ACTION_UNBOUND")
            if set(node) != fields[node["component"]]:
                raise A2UIValidationError("UNEXPECTED_COMPONENT_FIELDS")
            if node["component"] == "Text" and not isinstance(node["text"], str):
                raise A2UIValidationError("UNSAFE_DYNAMIC_CONTENT")
            if node["component"] in {"Column", "Row"} and not isinstance(node["children"], list):
                raise A2UIValidationError("INVALID_CHILDREN")
    elif kind == "updateDataModel":
        if set(body) != {"surfaceId", "path", "value"} or body["path"] != "/":
            raise A2UIValidationError("INVALID_DATA_UPDATE")
    elif set(body) != {"surfaceId"}:
        raise A2UIValidationError("INVALID_DELETE")
    return envelope


def _text(identifier, value):
    return {"id": identifier, "component": "Text", "text": str(value)}


def company_surface(store, provider, tenant, identity, *, surface_id):
    """Read authorized company list and emit a renderable A2UI 1.0 surface.

    JustYou identity is checked by ProviderStore; no caller-supplied
    verification flags, tenant switching, or function calls are accepted.
    """
    sid = _surface_id(surface_id)
    companies = store.list_companies(provider, tenant, identity)
    if not isinstance(companies, list) or len(companies) > 100:
        raise A2UIValidationError("INVALID_COMPANY_LIST")
    nodes = [{"id": "root", "component": "Column", "children": ["heading"]}]
    nodes.append(_text("heading", "Hermes Unlimited · Companies"))
    for i, company in enumerate(companies):
        if not isinstance(company, dict) or not isinstance(company.get("company"), str) or not isinstance(company.get("name"), str):
            raise A2UIValidationError("INVALID_COMPANY")
        node_id = f"company_{i}"
        nodes[0]["children"].append(node_id)
        nodes.append(_text(node_id, company["name"]))
    message = {"version": "1.0", "createSurface": {
        "surfaceId": sid,
        "catalogId": BASIC_CATALOG,
        "sendDataModel": False,
        "components": nodes,
        "dataModel": {},
    }}
    return validate_envelope(message)


def request_surface(store, provider, tenant, company, identity, *, surface_id):
    """Read authorized requests for exactly one company, without effects."""
    sid = _surface_id(surface_id)
    requests = store.list_requests(provider, tenant, company, identity)
    if not isinstance(requests, list) or len(requests) > 100:
        raise A2UIValidationError("INVALID_REQUEST_LIST")
    nodes = [{"id": "root", "component": "Column", "children": ["heading"]}]
    nodes.append(_text("heading", "Mission Control · Requests"))
    for i, req in enumerate(requests):
        if not isinstance(req, dict) or any(not isinstance(req.get(k), str) for k in ("request", "service", "state")):
            raise A2UIValidationError("INVALID_REQUEST")
        node_id = f"request_{i}"
        nodes[0]["children"].append(node_id)
        nodes.append(_text(node_id, f"{req['request']} · {req['service']} · {req['state']}"))
    return validate_envelope({"version": "1.0", "createSurface": {
        "surfaceId": sid, "catalogId": BASIC_CATALOG, "sendDataModel": False,
        "components": nodes, "dataModel": {},
    }})


def mission_surface(store, provider, tenant, company, identity, *, surface_id):
    """Read authorized autonomous missions and economic EV summaries for one company."""
    sid = _surface_id(surface_id)
    missions = store.list_missions(provider, tenant, company, identity)
    if not isinstance(missions, list) or len(missions) > 100:
        raise A2UIValidationError("INVALID_MISSION_LIST")
    nodes = [{"id": "root", "component": "Column", "children": ["heading"]}]
    nodes.append(_text("heading", "Captain's Bridge · Autonomous Missions & EV"))
    for i, m in enumerate(missions):
        if not isinstance(m, dict) or not isinstance(m.get("objective"), str) or not isinstance(m.get("status"), str):
            raise A2UIValidationError("INVALID_MISSION")
        node_id = f"mission_{i}"
        nodes[0]["children"].append(node_id)
        verified_tag = "VERIFIED" if m.get("independently_verified") else "UNVERIFIED"
        net_val = m.get("net_value_minor", 0.0)
        nodes.append(_text(
            node_id,
            f"{m['objective']} · {m['status']} · {verified_tag} · net_ev={net_val:.1f}",
        ))
    return validate_envelope({"version": "1.0", "createSurface": {
        "surfaceId": sid, "catalogId": BASIC_CATALOG, "sendDataModel": False,
        "components": nodes, "dataModel": {},
    }})


def readiness_surface(store, provider, tenant, identity, *, surface_id):
    """Read-only A2UI 1.0 Captain's Bridge surface displaying the 15-area Product Readiness Matrix."""
    from .company_os import PRODUCT_READINESS_MATRIX

    sid = _surface_id(surface_id)
    # Enforce tenant & JustYou authorization via ProviderStore before exporting any UI surface
    store.list_companies(provider, tenant, identity)
    nodes = [{"id": "root", "component": "Column", "children": ["heading"]}]
    nodes.append(_text("heading", "Captain's Bridge · 15-Area Product Readiness Matrix"))
    for i, item in enumerate(PRODUCT_READINESS_MATRIX):
        node_id = f"area_{i}"
        nodes[0]["children"].append(node_id)
        nodes.append(_text(node_id, f"{item['area']} · {item['status']}"))
    return validate_envelope({"version": "1.0", "createSurface": {
        "surfaceId": sid, "catalogId": BASIC_CATALOG, "sendDataModel": False,
        "components": nodes, "dataModel": {},
    }})


def delete_surface(surface_id):
    return validate_envelope({"version": "1.0", "deleteSurface": {"surfaceId": _surface_id(surface_id)}})


def encode_jsonl(messages):
    """Preserve A2UI message framing for an ordered transport."""
    return "".join(json.dumps(validate_envelope(message), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n" for message in messages)
