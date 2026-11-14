"""Hermes Unlimited native public core.

Hermes owns task execution; JustYou verifies the profile. Plugin tools never
accept tenant, assignee, identity, or execution authority from request payloads.
"""
import json

STATUS_SCHEMA = {
    "name": "hermes_unlimited_status",
    "description": "Report Hermes Unlimited readiness and identity integration status.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
TASK_SCHEMA = {
    "name": "unlimited_company_task",
    "description": "Queue a scoped company task in Hermes Kanban for the bound JustYou profile.",
    "parameters": {"type": "object", "properties": {
        "request_id": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 256},
        "body": {"type": "string", "maxLength": 8192}},
        "required": ["request_id", "title"], "additionalProperties": False},
}
RESULT_SCHEMA = {
    "name": "unlimited_company_result",
    "description": "Read the real Hermes Kanban state for a scoped company task.",
    "parameters": {"type": "object", "properties": {
        "task_id": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"}},
        "required": ["task_id"], "additionalProperties": False},
}


def get_status(profile_name):
    return {
        "product": "Hermes Unlimited",
        "profile": profile_name,
        "stage": "PUBLIC_CORE_INTEGRATION",
        "company_creation_ready": False,
        "customer_execution_ready": False,
        "identity_verified": False,
        "authority_granted": False,
        "production_ready": False,
    }


def _modules():
    try:
        from .unlimited.justyou import JustYouVerifier
        from .unlimited.hermes_kanban import HermesKanban
    except ImportError:
        from unlimited.justyou import JustYouVerifier
        from unlimited.hermes_kanban import HermesKanban
    return JustYouVerifier, HermesKanban


def register(ctx):
    def scoped_secret(name, default=""):
        # Only the JustYou session credential is a secret. Other values live in
        # the native Hermes plugin settings (config.yaml), scoped by plugin id.
        if name == "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN":
            from agent.secret_scope import get_secret
            return get_secret(name, default)
        getter = getattr(ctx, "get_config", None)
        return getter(name, default) if callable(getter) else default

    def scoped_identity():
        JustYouVerifier, _ = _modules()
        try:
            from .unlimited.justyou_host import trusted_components
        except ImportError:
            from unlimited.justyou_host import trusted_components
        tenant = scoped_secret("HERMES_UNLIMITED_TENANT_ID", "")
        expected = scoped_secret("HERMES_UNLIMITED_JUSTYOU_IDENTITY", "")
        if not tenant or not expected:
            raise PermissionError("PROFILE_SCOPE_NOT_CONFIGURED")
        try:
            store, resolver, token = trusted_components(ctx, scoped_secret)
        except (OSError, ValueError, ImportError, TypeError) as exc:
            raise PermissionError("JUSTYOU_HOST_UNAVAILABLE") from exc
        verifier = JustYouVerifier(
            store, resolver, ctx.profile_name, token)
        evidence = verifier.verify()
        if evidence.get("verified") is not True or evidence.get("identity") != expected:
            raise PermissionError("JUSTYOU_NOT_VERIFIED")
        return tenant, evidence

    def status_handler(args=None, **_kwargs):
        if args not in (None, {}):
            return json.dumps({"available": False, "reason": "UNEXPECTED_ARGUMENTS"})
        status = get_status(ctx.profile_name)
        try:
            tenant, evidence = scoped_identity()
            status.update(identity_verified=True, tenant_configured=bool(tenant),
                          binding_digest=evidence["binding_digest"])
        except (PermissionError, RuntimeError):
            pass
        return json.dumps(status, sort_keys=True)

    def task_handler(args=None, **_kwargs):
        if not isinstance(args, dict) or set(args) - {"request_id", "title", "body"}:
            return json.dumps({"queued": False, "reason": "INVALID_ARGUMENTS"})
        try:
            tenant, evidence = scoped_identity()
            _, HermesKanban = _modules()
            try:
                from .unlimited.hermes_kanban import board_for
            except ImportError:
                from unlimited.hermes_kanban import board_for
            provider = scoped_secret("HERMES_UNLIMITED_PROVIDER_ID", "")
            adapter = HermesKanban(hermes=scoped_secret("HERMES_UNLIMITED_HERMES_CLI", "hermes"),
                                   board=board_for(provider, tenant))
            response = adapter.enqueue(
                tenant=tenant, assignee=ctx.profile_name,
                task_id=args["request_id"], title=args["title"],
                body=args.get("body", ""), identity_evidence=evidence)
            return json.dumps(response, sort_keys=True)
        except (PermissionError, RuntimeError, ValueError, KeyError) as exc:
            return json.dumps({"queued": False, "reason": type(exc).__name__}, sort_keys=True)

    def result_handler(args=None, **_kwargs):
        if not isinstance(args, dict) or set(args) != {"task_id"}:
            return json.dumps({"found": False, "reason": "INVALID_ARGUMENTS"})
        try:
            tenant, _ = scoped_identity()
            _, HermesKanban = _modules()
            try:
                from .unlimited.hermes_kanban import board_for
            except ImportError:
                from unlimited.hermes_kanban import board_for
            provider = scoped_secret("HERMES_UNLIMITED_PROVIDER_ID", "")
            adapter = HermesKanban(hermes=scoped_secret("HERMES_UNLIMITED_HERMES_CLI", "hermes"),
                                   board=board_for(provider, tenant))
            return json.dumps(adapter.result(tenant=tenant, assignee=ctx.profile_name,
                                             task_id=args["task_id"]), sort_keys=True)
        except (PermissionError, RuntimeError, ValueError, KeyError) as exc:
            return json.dumps({"found": False, "reason": type(exc).__name__}, sort_keys=True)

    for schema, handler in ((STATUS_SCHEMA, status_handler), (TASK_SCHEMA, task_handler),
                            (RESULT_SCHEMA, result_handler)):
        ctx.register_tool(name=schema["name"], toolset="hermes_unlimited",
                          schema=schema, handler=handler)

    # Provider registry tools inherit the same trusted scoped identity.
    try:
        from .unlimited.tools import register_company_tools
    except ImportError:
        from unlimited.tools import register_company_tools
    register_company_tools(ctx, scoped_secret, scoped_identity)

    try:
        from .feedback_task_model.hermes_hooks import register_feedback_hooks
    except ImportError:
        from feedback_task_model.hermes_hooks import register_feedback_hooks
    if callable(getattr(ctx, "register_hook", None)):
        register_feedback_hooks(ctx)
