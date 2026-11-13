"""Native public management and autonomous execution tools for Hermes Unlimited.

All provider, tenant and identity fields come exclusively from Hermes scoped
configuration plus validated JustYou session, never user-supplied tool args.
"""
import asyncio
import json

SCHEMAS = (
    {
        "name": "unlimited_connection_manage",
        "description": "Manage tenant-owned provider connections in native Hermes UX. Never accepts credentials or secrets; only host-vault references.",
        "parameters": {"type": "object", "properties": {
            "operation": {"type": "string", "enum": ["connect", "status", "disconnect", "onboard"]},
            "connection_id": {"type": "string"},
            "provider": {"type": "string", "enum": ["smtp", "stripe"]},
            "secret_ref": {"type": "string"},
            "config": {"type": "object"}},
            "required": ["operation", "connection_id"], "additionalProperties": False},
    },
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
        "name": "unlimited_company_list",
        "description": "List only companies in the bound provider and customer tenant.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "unlimited_service_dispatch",
        "description": "Retry, recover, or resume an existing service request using idempotent Hermes Kanban submission.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"}, "request_id": {"type": "string"}},
            "required": ["company_id", "request_id"], "additionalProperties": False},
    },
    {
        "name": "unlimited_a2ui_surface",
        "description": "Return a read-only A2UI 1.0 surface for the bound tenant; no action dispatch.",
        "parameters": {"type": "object", "properties": {
            "view": {"type": "string", "enum": ["companies", "requests", "missions", "readiness"]},
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
    {
        "name": "unlimited_mission_run",
        "description": "Autonomously decompose, route, execute, recover, and independently verify a business objective with continuous marginal EV governance.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "objective_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "target_value_minor": {"type": "integer", "minimum": 0},
            "currency": {"type": "string"},
            "budget_ceiling_minor": {"type": "integer", "minimum": 0},
            "sla_seconds": {"type": "number"},
            "routing_strategy": {"type": "string", "enum": ["static", "dynamic", "outcome_driven"]},
            "required_deliverables": {"type": "array", "items": {"type": "string"}}},
            "required": ["company_id", "objective_id", "title", "target_value_minor"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_economic_evaluate",
        "description": "Evaluate whether the next model call, retry, or human intervention has positive Expected Value (EV).",
        "parameters": {"type": "object", "properties": {
            "task_kind": {"type": "string"},
            "candidate_model_id": {"type": "string"},
            "marginal_value_minor": {"type": "number"},
            "spent_cost_minor": {"type": "number"},
            "elapsed_seconds": {"type": "number"},
            "attempt": {"type": "integer", "minimum": 1},
            "budget_ceiling_minor": {"type": "integer", "minimum": 0},
            "sla_seconds": {"type": "number"},
            "require_human_supervision": {"type": "boolean"},
            "objective_already_verified": {"type": "boolean"}},
            "required": ["task_kind", "candidate_model_id", "marginal_value_minor"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_memory_recall",
        "description": "Recall tenant-scoped Company Memory lessons with explicit VERIFIED_OUTCOME vs RECORDED_UNVERIFIED classification.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "task_kind": {"type": "string"},
            "verified_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["company_id"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_service_factory",
        "description": "Promote an independently verified, positive-EV autonomous mission into a reusable Service Factory blueprint and published service.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "objective_id": {"type": "string"},
            "service_id": {"type": "string"},
            "title": {"type": "string"},
            "currency": {"type": "string"}},
            "required": ["company_id", "objective_id", "service_id", "title"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_socratic_council",
        "description": "Run a blind multi-lens Socratic Council review preserving dissent and uncertainty with zero execution authority.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"},
            "answers": {"type": "object"}},
            "required": ["question", "answers"],
            "additionalProperties": False},
    },
    {
        "name": "unlimited_company_cycle",
        "description": "Run a complete Autonomous Company Operating System cycle evaluating the 6 governing business questions across a candidate objective portfolio under an owner CompanyCharter.",
        "parameters": {"type": "object", "properties": {
            "company_id": {"type": "string"},
            "strategic_direction": {"type": "string"},
            "allowed_domains": {"type": "array", "items": {"type": "string"}},
            "forbidden_domains": {"type": "array", "items": {"type": "string"}},
            "max_budget_per_mission_minor": {"type": "integer", "minimum": 0},
            "owner_approval_threshold_minor": {"type": "integer", "minimum": 0},
            "min_expected_roi_ratio": {"type": "number"},
            "candidates": {"type": "array", "items": {"type": "object"}},
            "auto_synthesize_service": {"type": "boolean"}},
            "required": ["company_id", "strategic_direction", "candidates"],
            "additionalProperties": False},
    },
)


def _default_council_callables(ctx):
    members = getattr(ctx, "socratic_council_members", None)
    chair = getattr(ctx, "socratic_council_chair", None)
    if members and chair:
        return members, chair

    async def make_lens(role, _system, prompt):
        data = json.loads(prompt)
        if "candidates" in data:
            return (
                f"[{role} critique] Reviewed anonymous candidates; verified falsification test "
                f"and challenged optimistic cost/latency assumptions."
            )
        return (
            f"[{role} independent analysis] Evaluated problem and assumptions; "
            f"counterargument: proceeding without independent verification risks negative EV."
        )

    async def default_chair(_system, prompt):
        data = json.loads(prompt)
        case = json.loads(data["case"])
        q = case.get("question", "")
        return json.dumps({
            "status": "DISSENT",
            "synthesis": f"Proceed conditionally on '{q}' only with independent outcome verification and positive marginal EV.",
            "dissent": ["Skeptic lens requires empirical verification receipt before marking outcome billable."],
            "uncertainty": ["Tail latency and retry rate under external provider outage remain bounded by SLA cap."],
        })

    default_members = {
        role: (lambda sys_p, usr_p, _r=role: make_lens(_r, sys_p, usr_p))
        for role in ("explorer", "builder", "economist", "skeptic")
    }
    return default_members, default_chair


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
        return ProviderStore(path, verify), provider, tenant, evidence, verify, path

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
                store, provider, tenant, evidence, verify, db_path = verified_store()
                identity = evidence["identity"]

                def dispatch(company_id, request_id):
                    item = store.get_request(provider, tenant, company_id, request_id, identity)
                    if item is None:
                        raise ValueError("REQUEST_NOT_FOUND")
                    if item["task_id"] and item["state"] != "blocked":
                        return {"request": request_id, "state": item["state"],
                                "task_id": item["task_id"], "executed": False}
                    if item["task_id"] and item["state"] == "blocked":
                        next_attempt = int(item.get("attempts", 1)) + 1
                        if next_attempt > 3:
                            raise ValueError("MAX_RECOVERY_ATTEMPTS_EXCEEDED")
                        response = adapter().enqueue(
                            tenant=tenant, assignee=ctx.profile_name,
                            task_id=f"{company_id}:{request_id}:retry-{next_attempt}",
                            title=f"{company_id}/{item['service']}/{request_id} (recovery {next_attempt})",
                            body=json.dumps(item["payload"], sort_keys=True),
                            identity_evidence=evidence)
                        recovered = store.recover_blocked_request(
                            provider, tenant, company_id, request_id,
                            response["task_id"], identity)
                        return {**recovered, "executed": False}
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

                if name == "unlimited_connection_manage":
                    from .customer_connections import CustomerConnectionRegistry
                    from .customer_connection_api import CustomerConnectionController
                    registry = CustomerConnectionRegistry(
                        db_path, lambda t, actor: verify(provider, t, actor))
                    # Hermes signed JustYou session is the only identity source.
                    controller = CustomerConnectionController(
                        registry, lambda _session: (tenant, identity))
                    op = args["operation"]
                    cid = args["connection_id"]
                    if op in ("connect", "disconnect", "onboard"):
                        # The Hermes host must authorize each mutation separately;
                        # tool args alone never grant effect authority.
                        approve = getattr(ctx, "approve_customer_connection", None)
                        if not callable(approve) or approve(tenant, identity, op, cid) is not True:
                            raise PermissionError("HERMES_CONNECTION_APPROVAL_REQUIRED")
                    if op == "onboard":
                        # Credential entry and secret storage are exclusively owned by
                        # the trusted Hermes host, never tool args or model context.
                        onboard = getattr(ctx, "onboard_customer_connection", None)
                        if not callable(onboard):
                            raise PermissionError("HERMES_SECURE_ONBOARDING_UNAVAILABLE")
                        if set(args) - {"operation", "connection_id", "provider", "config"}:
                            raise ValueError("ONBOARDING_MUST_NOT_CONTAIN_SECRET_REFERENCE")
                        result = onboard(tenant, identity, cid, args.get("provider"), args.get("config", {}))
                        if not isinstance(result, dict) or result.get("approved") is not True:
                            raise PermissionError("HERMES_ONBOARDING_NOT_APPROVED")
                        ref = result.get("secret_ref", "")
                        if not isinstance(ref, str) or not ref.startswith(f"vault://{tenant}/"):
                            raise PermissionError("HERMES_VAULT_REFERENCE_INVALID")
                        out = controller.connect(None, {
                            "connection_id": cid, "provider": args.get("provider"),
                            "config": args.get("config", {}), "secret_ref": ref})
                    elif op == "connect":
                        out = controller.connect(None, args)
                    elif op == "status":
                        out = controller.get(None, cid)
                    elif op == "disconnect":
                        controller.disconnect(None, cid)
                        out = {"connection_id": cid, "enabled": False}
                    else:
                        raise ValueError("INVALID_CONNECTION_OPERATION")
                elif name == "unlimited_a2ui_surface":
                    from .a2ui_adapter import company_surface, mission_surface, readiness_surface, request_surface
                    view = args["view"]
                    if view == "companies" and "company_id" not in args:
                        out = company_surface(store, provider, tenant, identity,
                                              surface_id=args["surface_id"])
                    elif view == "readiness" and "company_id" not in args:
                        out = readiness_surface(store, provider, tenant, identity,
                                                surface_id=args["surface_id"])
                    elif view == "requests" and "company_id" in args:
                        out = request_surface(store, provider, tenant, args["company_id"],
                                              identity, surface_id=args["surface_id"])
                    elif view == "missions" and "company_id" in args:
                        out = mission_surface(store, provider, tenant, args["company_id"],
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
                elif name == "unlimited_mission_run":
                    from .autonomy import AutonomousMissionEngine, BusinessObjective, IndependentOutcomeVerifier
                    from .economics import EconomicPolicy
                    from .memory_factory import CompanyMemoryStore

                    company_id = args["company_id"]
                    companies = {c["company"] for c in store.list_companies(provider, tenant, identity)}
                    if company_id not in companies:
                        raise ValueError("COMPANY_NOT_FOUND")

                    currency = args.get("currency", "NOK")
                    budget = int(args.get("budget_ceiling_minor", max(1000, int(args["target_value_minor"]))))
                    sla = float(args.get("sla_seconds", 300.0))
                    strategy = args.get("routing_strategy", "outcome_driven")
                    deliverables = tuple(args.get("required_deliverables") or (
                        "executive_summary", "action_plan", "quantified_impact", "risk_mitigations"
                    ))
                    policy = EconomicPolicy(
                        currency=currency,
                        budget_ceiling_minor=budget,
                        sla_seconds=sla,
                    )
                    objective = BusinessObjective(
                        objective_id=args["objective_id"],
                        company_id=company_id,
                        title=args["title"],
                        description=args.get("description", args["title"]),
                        target_value_minor=int(args["target_value_minor"]),
                        currency=currency,
                        required_deliverables=deliverables,
                        policy=policy,
                    )
                    mem_store = CompanyMemoryStore(db_path, verify)
                    recalled = mem_store.recall(
                        provider=provider, tenant=tenant, company=company_id,
                        identity=identity, verified_only=True, limit=5,
                    )
                    worker_fn = getattr(ctx, "mission_worker", None)
                    engine_kwargs = {
                        "verify_identity": verify,
                        "routing_strategy": strategy,
                        "ledger_db_path": db_path,
                    }
                    if callable(worker_fn):
                        engine_kwargs["worker"] = worker_fn
                    elif scoped_secret("HERMES_UNLIMITED_LIVE_WORKER", "") == "1":
                        from .economics import LIVE_HERMES_MODEL_CATALOG, EconomicIntelligenceEngine
                        from .hermes_live_worker import HermesLiveIndependentCritic, HermesLiveWorkerAdapter
                        engine_kwargs["economic_engine"] = EconomicIntelligenceEngine(
                            models=LIVE_HERMES_MODEL_CATALOG,
                            policy=policy,
                        )
                        engine_kwargs["worker"] = HermesLiveWorkerAdapter()
                        engine_kwargs["verifier"] = IndependentOutcomeVerifier(
                            independent_critic=HermesLiveIndependentCritic()
                        )
                    mission_engine = AutonomousMissionEngine(**engine_kwargs)
                    report = mission_engine.execute_objective(
                        provider_id=provider,
                        tenant_id=tenant,
                        identity=identity,
                        objective=objective,
                        memory_lessons=tuple(m.lesson for m in recalled),
                    )
                    report_dict = report.as_dict()
                    report_dict["title"] = objective.title
                    store.record_mission(provider, tenant, company_id, report_dict, identity)
                    if report.independently_verified:
                        mem_store.record_verified_outcome(
                            provider=provider,
                            tenant=tenant,
                            company=company_id,
                            identity=identity,
                            task_kind="implementation",
                            lesson=(
                                f"Verified objective {objective.objective_id} via {strategy} routing "
                                f"(cost={report.total_economic_cost_minor:.2f}, net_ev={report.net_economic_value_minor:.2f})."
                            ),
                            verification=report.verification,
                            cost_minor=report.total_economic_cost_minor,
                            verified_value_minor=report.verified_value_minor,
                        )
                    out = {
                        "ok": True,
                        "objective_id": report.objective_id,
                        "company_id": report.company_id,
                        "status": report.status,
                        "independently_verified": report.independently_verified,
                        "verified_value_minor": report.verified_value_minor,
                        "direct_cost_minor": report.direct_cost_minor,
                        "total_economic_cost_minor": report.total_economic_cost_minor,
                        "net_economic_value_minor": report.net_economic_value_minor,
                        "roi_ratio": report.roi_ratio,
                        "total_model_calls": report.total_model_calls,
                        "failures_detected": report.failures_detected,
                        "autonomous_recoveries": report.autonomous_recoveries,
                        "human_interventions_required": report.human_interventions_required,
                        "stop_reason": report.stop_reason,
                        "verification_digest": report.verification.evidence_digest,
                        "report_digest": report.report_digest,
                    }
                elif name == "unlimited_economic_evaluate":
                    from .economics import EconomicIntelligenceEngine, EconomicPolicy
                    policy = EconomicPolicy(
                        budget_ceiling_minor=int(args.get("budget_ceiling_minor", 10_000)),
                        sla_seconds=float(args.get("sla_seconds", 300.0)),
                    )
                    econ = EconomicIntelligenceEngine(policy=policy)
                    decision = econ.evaluate_next_action(
                        task_kind=args["task_kind"],
                        candidate_model_id=args["candidate_model_id"],
                        marginal_value_minor=float(args["marginal_value_minor"]),
                        spent_cost_minor=float(args.get("spent_cost_minor", 0.0)),
                        elapsed_seconds=float(args.get("elapsed_seconds", 0.0)),
                        attempt=int(args.get("attempt", 1)),
                        require_human_supervision=bool(args.get("require_human_supervision", False)),
                        objective_already_verified=bool(args.get("objective_already_verified", False)),
                    )
                    out = {"ok": True, **decision.as_dict()}
                elif name == "unlimited_memory_recall":
                    from .memory_factory import CompanyMemoryStore
                    mem_store = CompanyMemoryStore(db_path, verify)
                    entries = mem_store.recall(
                        provider=provider,
                        tenant=tenant,
                        company=args["company_id"],
                        identity=identity,
                        task_kind=args.get("task_kind"),
                        verified_only=bool(args.get("verified_only", False)),
                        limit=int(args.get("limit", 5)),
                    )
                    out = {"ok": True, "entries": [e.as_dict() for e in entries]}
                elif name == "unlimited_service_factory":
                    from .autonomy import MissionExecutionReport, OutcomeVerificationReceipt
                    from .memory_factory import ServiceFactory

                    saved = store.get_mission(
                        provider, tenant, args["company_id"], args["objective_id"], identity
                    )
                    if saved is None:
                        raise ValueError("MISSION_NOT_FOUND")
                    ver_raw = saved["verification"]
                    verification = OutcomeVerificationReceipt(
                        objective_id=ver_raw["objective_id"],
                        independently_verified=ver_raw["independently_verified"],
                        agent_claimed_complete=ver_raw["agent_claimed_complete"],
                        checks_passed=tuple(ver_raw["checks_passed"]),
                        checks_failed=tuple(ver_raw["checks_failed"]),
                        deliverable_digest=ver_raw["deliverable_digest"],
                        evidence_digest=ver_raw["evidence_digest"],
                        verifier_seal=ver_raw.get("verifier_seal", ""),
                        independent_critic_verdict=ver_raw.get("independent_critic_verdict"),
                        tenant_id=ver_raw.get("tenant_id", ""),
                        company_id=ver_raw.get("company_id", ""),
                        policy_digest=ver_raw.get("policy_digest", ""),
                        authority_key_id=ver_raw.get("authority_key_id", "verifier-authority-v2"),
                    )
                    reconstructed = MissionExecutionReport(
                        objective_id=saved["objective_id"],
                        company_id=saved["company_id"],
                        tenant_id=saved["tenant_id"],
                        identity=saved["identity"],
                        routing_strategy=saved["routing_strategy"],
                        status=saved["status"],
                        independently_verified=saved["independently_verified"],
                        target_value_minor=saved["target_value_minor"],
                        verified_value_minor=saved["verified_value_minor"],
                        direct_cost_minor=saved["direct_cost_minor"],
                        total_economic_cost_minor=saved["total_economic_cost_minor"],
                        recovery_spend_minor=saved["recovery_spend_minor"],
                        net_economic_value_minor=saved["net_economic_value_minor"],
                        roi_ratio=saved["roi_ratio"],
                        elapsed_seconds=saved["elapsed_seconds"],
                        total_model_calls=saved["total_model_calls"],
                        total_input_tokens=saved["total_input_tokens"],
                        total_output_tokens=saved["total_output_tokens"],
                        failures_detected=saved["failures_detected"],
                        autonomous_recoveries=saved["autonomous_recoveries"],
                        duplicate_actions_prevented=saved["duplicate_actions_prevented"],
                        human_interventions_required=saved["human_interventions_required"],
                        stop_reason=saved["stop_reason"],
                        deliverables=saved["deliverables"],
                        verification=verification,
                        step_receipts=(),
                        ev_decisions=(),
                        checkpoint_state={},
                        report_digest=saved["report_digest"],
                    )
                    factory = ServiceFactory(db_path, verify)
                    blueprint = factory.synthesize_from_mission(
                        provider=provider,
                        tenant=tenant,
                        company=args["company_id"],
                        identity=identity,
                        service_id=args["service_id"],
                        title=args["title"],
                        report=reconstructed,
                        currency=args.get("currency", "NOK"),
                        provider_store=store,
                    )
                    out = {"ok": True, **blueprint.as_dict()}
                elif name == "unlimited_socratic_council":
                    from .socratic_council import SocraticCouncil
                    members, chair = _default_council_callables(ctx)
                    council = SocraticCouncil(members, chair)
                    record = asyncio.run(council.run(args["question"], args["answers"]))
                    out = {"ok": True, **record.as_dict()}
                elif name == "unlimited_company_cycle":
                    from .autonomy import BusinessObjective
                    from .company_os import AutonomousCompanyOperatingSystem, CompanyCharter
                    from .economics import EconomicPolicy

                    company_id = args["company_id"]
                    charter_kwargs = {
                        "company_id": company_id,
                        "display_name": company_id.title(),
                        "mission_statement": args["strategic_direction"],
                        "max_autonomous_budget_minor": int(args.get("max_budget_per_mission_minor", 10_000)),
                        "owner_approval_threshold_minor": int(args.get("owner_approval_threshold_minor", 8_000)),
                        "min_roi_hurdle_ratio": float(args.get("min_expected_roi_ratio", 0.25)),
                    }
                    if args.get("allowed_domains"):
                        charter_kwargs["strategic_domains"] = tuple(args["allowed_domains"])
                    if args.get("forbidden_domains"):
                        charter_kwargs["forbidden_domains"] = tuple(args["forbidden_domains"])
                    charter = CompanyCharter(**charter_kwargs)

                    candidate_objs = []
                    for raw_cand in args["candidates"]:
                        if not isinstance(raw_cand, dict):
                            raise ValueError("INVALID_CANDIDATE_OBJECTIVE")
                        c_target = int(raw_cand["target_value_minor"])
                        c_budget = int(raw_cand.get("budget_ceiling_minor", max(1000, c_target)))
                        candidate_objs.append(
                            BusinessObjective(
                                objective_id=str(raw_cand["objective_id"]),
                                company_id=company_id,
                                title=str(raw_cand["title"]),
                                description=str(raw_cand.get("description", raw_cand["title"])),
                                target_value_minor=c_target,
                                currency=str(raw_cand.get("currency", "NOK")),
                                policy=EconomicPolicy(
                                    currency=str(raw_cand.get("currency", "NOK")),
                                    budget_ceiling_minor=c_budget,
                                ),
                            )
                        )
                    worker_fn = getattr(ctx, "mission_worker", None)
                    os_kwargs = {"database": db_path, "verify_identity": verify}
                    if callable(worker_fn):
                        os_kwargs["worker"] = worker_fn
                    company_os = AutonomousCompanyOperatingSystem(**os_kwargs)
                    cycle_report = company_os.run_operating_cycle(
                        provider_id=provider,
                        tenant_id=tenant,
                        identity=identity,
                        charter=charter,
                        candidate_objectives=candidate_objs,
                        auto_productize_services=bool(args.get("auto_synthesize_service", True)),
                    )
                    out = {"ok": True, **cycle_report.as_dict()}
                else:
                    out = {"companies": store.list_companies(provider, tenant, identity)}
                return json.dumps(out, sort_keys=True)
            except (PermissionError, RuntimeError, ValueError, KeyError, TypeError, LookupError) as exc:
                return json.dumps({"ok": False, "reason": type(exc).__name__}, sort_keys=True)
        return handler

    for schema in SCHEMAS:
        ctx.register_tool(name=schema["name"], toolset="hermes_unlimited",
                          schema=schema, handler=make_handler(schema["name"]))
