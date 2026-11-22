"""Native public management tools for provider-owned company/service lifecycle.

All provider, tenant and identity fields come exclusively from Hermes scoped
configuration plus validated JustYou session, never user-supplied tool args.
"""
import hashlib
import json
import sqlite3

SCHEMAS = (
    {
        "name": "unlimited_company_create",
        "description": "Create a tenant-scoped AI-native company in the provider registry.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "display_name": {"type": "string"}},
            "required": ["company_id", "display_name"], "additionalProperties": False},
    },
    {
        "name": "unlimited_service_publish",
        "description": "Publish a priced service belonging to a tenant-scoped company.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "service_id": {"type": "string"},
            "title": {"type": "string"}, "price_minor": {"type": "integer", "minimum": 0},
            "currency": {"type": "string"}},
            "required": ["company_id", "service_id", "title", "price_minor", "currency"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_service_request",
        "description": "Record a customer service request; recording does not execute it.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"},
            "service_id": {"type": "string"}, "payload": {"type": "object"}},
            "required": ["company_id", "request_id", "service_id", "payload"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_oversight_record",
        "description": "Record model-submitted unverified oversight time against a scoped service request in its currency; not independent evidence.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"},
            "entry_id": {"type": "string"},
            "phase": {"type": "string", "enum": ["pre_control","co_planning","live_monitoring","post_review"]},
            "minutes": {"type": "string"}, "hourly_rate": {"type": "string"}},
            "required": ["company_id","request_id","entry_id","phase","minutes","hourly_rate"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_oversight_costs",
        "description": "Record model-submitted unverified AI and recovery costs for a scoped request in its service currency; not independently measured.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"},
            "ai_cost": {"type": "string"}, "recovery_cost": {"type": "string"}},
            "required": ["company_id","request_id","ai_cost","recovery_cost"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_oversight_report",
        "description": "Read scoped CAVO-ready cost breakdown; never claim verified benefit from Hermes task status.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"}},
            "required": ["company_id","request_id"], "additionalProperties": False},
    },
    {
        "name": "unlimited_memory_recall",
        "description": "Read existing tenant-scoped Company Memory rows. Stored verification labels are not independently attested by this tool; no writes or effects.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "task_kind": {"type": "string"},
            "verified_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["company_id"], "additionalProperties": False},
    },
    {
        "name": "unlimited_specialist_factory",
        "description": "Discover host-reported tool definitions and draft specialist proposals; no verified access, effects or execution authority.",
        "parameters": {"type": "object", "properties": {
            "operation": {"type": "string", "enum": ["discover", "propose"]},
            "toolset": {"type": "string"},
            "objective": {"type": "string"},
            "selected_tools": {"type": "array", "items": {"type": "string"}}},
            "required": ["operation", "toolset"], "additionalProperties": False},
    },
    {
        "name": "unlimited_economic_evaluate",
        "description": "Compare unverified recorded costs to a model-submitted scenario cap; advisory arithmetic only, not budget approval, ROI, or execution.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "request_id": {"type": "string"},
            "scenario_cap": {"type": "string"}},
            "required": ["company_id", "request_id", "scenario_cap"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_company_list",
        "description": "List only companies in the bound provider and customer tenant.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "unlimited_service_dispatch",
        "description": "Retry or resume an existing service request using idempotent Hermes Kanban submission.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"}},
            "required": ["company_id", "request_id"], "additionalProperties": False},
    },
    {
        "name": "unlimited_a2ui_surface",
        "description": "Return a read-only A2UI 1.0 surface for the bound tenant; no action dispatch.",
        "parameters": {"type": "object", "properties": {
            "view": {"type": "string", "enum": ["companies", "requests"]},
            "company_id": {"type": "string"},
            "surface_id": {"type": "string"}},
            "required": ["view", "surface_id"], "additionalProperties": False},
    },
    {
        "name": "unlimited_service_result",
        "description": "Read the scoped native Hermes execution result of a service request.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"}},
            "required": ["company_id", "request_id"], "additionalProperties": False},
    },
)


def register_company_tools(ctx, scoped_secret, scoped_identity, declared_schemas=()):
    from .runtime import ProviderStore

    def adapter():
        from .hermes_kanban import HermesKanban, board_for
        tenant, _ = scoped_identity()
        provider = scoped_secret("HERMES_UNLIMITED_PROVIDER_ID", "")
        return HermesKanban(hermes=scoped_secret("HERMES_UNLIMITED_HERMES_CLI", "hermes"),
                            board=board_for(provider, tenant))

    def verified_store():
        tenant, evidence = scoped_identity()
        provider = scoped_secret("HERMES_UNLIMITED_PROVIDER_ID", "")
        path = scoped_secret("HERMES_UNLIMITED_REGISTRY_DB", "")
        if not provider or not path:
            raise PermissionError("REGISTRY_NOT_CONFIGURED")
        # Identity is tied to the signed session verified on each operation;
        # this closure never trusts a claimed identity passed via tool args.
        def verify(expected_provider, expected_tenant, identity):
            return (expected_provider == provider and expected_tenant == tenant
                    and evidence.get("verified") is True
                    and identity == evidence.get("identity"))
        return ProviderStore(path, verify), provider, tenant, evidence

    def make_handler(name):
        def handler(args=None, **_kwargs):
            if not isinstance(args, dict):
                args = {}
            schema = next(item for item in SCHEMAS if item["name"] == name)
            required = set(schema["parameters"].get("required", ()))
            permitted = set(schema["parameters"]["properties"])
            if set(args) - permitted or not required.issubset(args):
                return json.dumps({"ok": False, "reason": "INVALID_ARGUMENTS"})
            try:
                store, provider, tenant, evidence = verified_store()
                identity = evidence["identity"]
                def dispatch(company_id, request_id):
                    item = store.get_request(provider, tenant, company_id, request_id, identity)
                    if item is None:
                        raise ValueError("REQUEST_NOT_FOUND")
                    if item["task_id"]:
                        return {"request": request_id, "state": item["state"],
                                "task_id": item["task_id"], "executed": False}
                    response = adapter().enqueue(
                        tenant=tenant, assignee=ctx.profile_name,
                        task_id="request-" + hashlib.sha256(f"{company_id}\0{request_id}".encode()).hexdigest(),
                        title=f"{company_id}/{item['service']}/{request_id}",
                        body=json.dumps(item["payload"], sort_keys=True),
                        identity_evidence=evidence)
                    store.attach_task(provider, tenant, company_id, request_id,
                                      response["task_id"], identity)
                    return {"request": request_id, "state": "blocked",
                            "task_id": response["task_id"], "authorization_required": True,
                            "executed": False}
                if name == "unlimited_a2ui_surface":
                    from .a2ui_adapter import company_surface, request_surface
                    view = args["view"]
                    if view == "companies" and "company_id" not in args:
                        out = company_surface(store, provider, tenant, identity,
                                              surface_id=args["surface_id"])
                    elif view == "requests" and "company_id" in args:
                        out = request_surface(store, provider, tenant, args["company_id"],
                                              identity, surface_id=args["surface_id"])
                    else:
                        raise ValueError("INVALID_A2UI_VIEW_ARGUMENTS")
                elif name in {"unlimited_oversight_record", "unlimited_oversight_costs",
                                   "unlimited_oversight_report"}:
                    from .oversight_ledger import OversightLedger
                    ledger = OversightLedger(store)
                    scope = (provider, tenant, args["company_id"], args["request_id"])
                    if name == "unlimited_oversight_record":
                        out = ledger.record(*scope, args["entry_id"], args["phase"],
                                            args["minutes"], args["hourly_rate"], identity)
                    elif name == "unlimited_oversight_costs":
                        out = ledger.record_costs(*scope, args["ai_cost"],
                                                  args["recovery_cost"], identity)
                    else:
                        out = ledger.report(*scope, identity)
                elif name == "unlimited_memory_recall":
                    from .memory_recall import recall_existing
                    out = recall_existing(store, provider, tenant, args["company_id"],
                                          identity, task_kind=args.get("task_kind"),
                                          verified_only=args.get("verified_only", False),
                                          limit=args.get("limit", 5))
                elif name == "unlimited_specialist_factory":
                    from .specialist_discovery import (
                        LocalPluginDeclarations,
                        inspect_host_registry,
                    )
                    host_registry = getattr(ctx, "tool_registry", None)
                    if host_registry is None:
                        # Hermes PluginContext 0.23.1 does not expose a public
                        # tool_registry; fall back ONLY to our own bundled,
                        # non-live declarations and label them accordingly.
                        if args["toolset"] != "hermes_unlimited":
                            raise PermissionError("HOST_REGISTRY_REQUIRED_FOR_EXTERNAL_TOOLSET")
                        registry = LocalPluginDeclarations(tuple(declared_schemas) + SCHEMAS)
                        source = "LOCAL_PLUGIN_DECLARATION_ONLY"
                    else:
                        registry = host_registry
                        source = "HOST_REPORTED_SCHEMA"
                    out = inspect_host_registry(
                        registry, toolset=args["toolset"], operation=args["operation"],
                        objective=args.get("objective"), selected_tools=args.get("selected_tools"),
                        source=source)
                elif name == "unlimited_economic_evaluate":
                    from .economic_scenario import evaluate_cost_scenario
                    from .oversight_ledger import OversightLedger
                    out = evaluate_cost_scenario(
                        OversightLedger(store), provider, tenant, args["company_id"],
                        args["request_id"], identity, scenario_cap=args["scenario_cap"])
                elif name == "unlimited_company_create":
                    out = store.create_company(provider, tenant, args["company_id"],
                                               args["display_name"], identity)
                elif name == "unlimited_service_publish":
                    out = store.publish_service(
                        provider, tenant, args["company_id"], args["service_id"],
                        args["title"], args["price_minor"], args["currency"], identity)
                elif name == "unlimited_service_request":
                    store.request_service(
                        provider, tenant, args["company_id"], args["request_id"],
                        args["service_id"], args["payload"], identity)
                    try:
                        out = dispatch(args["company_id"], args["request_id"])
                    except RuntimeError:
                        # The request stays durably queued; retry via service_dispatch.
                        out = {"request": args["request_id"], "state": "queued",
                               "executed": False, "dispatch_pending": True}
                elif name == "unlimited_service_dispatch":
                    out = dispatch(args["company_id"], args["request_id"])
                elif name == "unlimited_service_result":
                    item = store.get_request(provider, tenant, args["company_id"],
                                             args["request_id"], identity)
                    if item is None:
                        raise ValueError("REQUEST_NOT_FOUND")
                    if not item["task_id"]:
                        out = {"request": args["request_id"], "state": "queued",
                               "completed": False, "independently_verified": False}
                    else:
                        result = adapter().result(tenant=tenant, assignee=ctx.profile_name,
                                                  task_id=item["task_id"])
                        if result.get("found") is not True:
                            raise ValueError("SCOPED_TASK_NOT_FOUND")
                        store.record_task_result(provider, tenant, args["company_id"],
                                                 args["request_id"], item["task_id"],
                                                 result, identity)
                        out = {"request": args["request_id"], "task_id": item["task_id"],
                               **result}
                else:
                    out = {"companies": store.list_companies(provider, tenant, identity)}
                return json.dumps(out, sort_keys=True)
            except sqlite3.IntegrityError:
                return json.dumps({"ok": False, "reason": "REGISTRY_CONFLICT"}, sort_keys=True)
            except (sqlite3.Error, ArithmeticError, OverflowError):
                return json.dumps({"ok": False, "reason": "STORAGE_OR_ARITHMETIC_ERROR"}, sort_keys=True)
            except (PermissionError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                # Preserve the public generic error contract. Never leak
                # the internal exception message or security policy details.
                return json.dumps({"ok": False, "reason": type(exc).__name__}, sort_keys=True)
        return handler

    for schema in SCHEMAS:
        ctx.register_tool(name=schema["name"], toolset="hermes_unlimited",
                          schema=schema, handler=make_handler(schema["name"]))
