"""Native public management tools for provider-owned company/service lifecycle.

All provider, tenant and identity fields come exclusively from Hermes scoped
configuration plus validated JustYou session, never user-supplied tool args.
"""
import json

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
        "name": "unlimited_offer_catalog",
        "description": "Discover provider offers; catalog entries do not imply readiness, billing or execution.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
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


def register_company_tools(ctx, scoped_secret, scoped_identity):
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
                        task_id=f"{company_id}:{request_id}",
                        title=f"{company_id}/{item['service']}/{request_id}",
                        body=json.dumps(item["payload"], sort_keys=True),
                        identity_evidence=evidence)
                    store.attach_task(provider, tenant, company_id, request_id,
                                      response["task_id"], identity)
                    return {"request": request_id, "state": "running",
                            "task_id": response["task_id"], "executed": False}
                if name == "unlimited_offer_catalog":
                    from .offer_catalog import service_offer_catalog
                    out = {"offers": service_offer_catalog()}
                elif name == "unlimited_a2ui_surface":
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
            except (PermissionError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                return json.dumps({"ok": False, "reason": type(exc).__name__}, sort_keys=True)
        return handler

    for schema in SCHEMAS:
        ctx.register_tool(name=schema["name"], toolset="hermes_unlimited",
                          schema=schema, handler=make_handler(schema["name"]))
