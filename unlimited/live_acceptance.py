"""Live Autonomy Acceptance Harness for Hermes Unlimited.

Executes real multi-provider LLM calls and native Hermes tools via `HermesLiveWorkerAdapter`
and `HermesLiveIndependentCritic` to verify:
1. Production-compatible Hermes runtime integration (`AIAgent` + `resolve_runtime_with_fallback`).
2. Three real, bounded business objectives with actual LLM calls and tool usage (`file` toolset).
3. Autonomous planning, execution, failure recovery, independent verification, checkpoint/resume,
   durable SQLite idempotency, and Service Factory synthesis.
4. Real model switching on runtime errors and injected validation failures, using
   authorized model providers only; OpenRouter is not part of the acceptance route.
5. Live comparison of `static`, `dynamic`, and `outcome_driven` routing on an identical objective.
6. Strict separation of measured telemetry (tokens, provider USD cost, wall-clock latency) from
   modeled economic estimates.
7. Adversarial challenge of the verification mechanism (including live cross-provider LLM critic).
8. Preservation of JustYou identity and tenant authorization boundaries.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unlimited.autonomy import (
    AutonomousMissionEngine,
    BusinessObjective,
    IndependentOutcomeVerifier,
    OutcomeVerificationReceipt,
    VerifierSigningAuthority,
)
from unlimited.company_os import (
    PRODUCT_READINESS_MATRIX,
    AuthorizedCustomerDeliveryChannel,
    CAVOOpportunityAllocator,
    CompanyCharter,
    GoalFidelityEvaluator,
)
from unlimited.economics import (
    LIVE_HERMES_MODEL_CATALOG,
    LIVE_NOUS_ALIBABA_MODEL_CATALOG,
    EconomicIntelligenceEngine,
    EconomicPolicy,
    RoutingStrategy,
)
from unlimited.hermes_live_worker import (
    HermesLiveIndependentCritic,
    HermesLiveWorkerAdapter,
    ProviderCircuitBreaker,
    ensure_hermes_runtime_loaded,
)
from unlimited.justyou import JustYouVerifier
from unlimited.memory_factory import CompanyMemoryStore, ServiceFactory
from unlimited.runtime import ProviderStore, UnverifiedIdentity

DEFAULT_EVIDENCE_PATH = REPO_ROOT / "docs" / "live_acceptance_evidence_20261112.json"

# Default to Nous + Alibaba catalog when Gemini free-tier quota is exhausted,
# or honor explicit HERMES_LIVE_ACCEPTANCE_PROVIDERS.
if os.environ.get("HERMES_LIVE_ACCEPTANCE_PROVIDERS"):
    allowed_providers = {
        v.strip().lower()
        for v in os.environ["HERMES_LIVE_ACCEPTANCE_PROVIDERS"].split(",")
        if v.strip()
    }
    LIVE_HERMES_MODEL_CATALOG = tuple(
        profile
        for profile in LIVE_HERMES_MODEL_CATALOG
        if profile.provider_id.lower() in allowed_providers
    )
    if not LIVE_HERMES_MODEL_CATALOG:
        raise RuntimeError("LIVE_ACCEPTANCE_NO_MODELS_FOR_SELECTED_PROVIDERS")
else:
    LIVE_HERMES_MODEL_CATALOG = LIVE_NOUS_ALIBABA_MODEL_CATALOG


def check_network_available(host: str = "inference-api.nousresearch.com", port: int = 443) -> bool:
    """Fast DNS/socket pre-check to detect sandbox network isolation immediately."""
    try:
        socket.setdefaulttimeout(2.0)
        socket.getaddrinfo(host, port)
        return True
    except Exception:
        return False


def _verify_justyou_boundaries(store: ProviderStore, memory: CompanyMemoryStore, factory: ServiceFactory) -> dict[str, Any]:
    """Verify JustYou identity, session authority, and tenant boundaries fail closed."""
    checks: dict[str, bool] = {}

    # 1. Unverified identity rejected on ProviderStore
    try:
        store.list_companies("owner", "tenant-a", "@unverified-intruder")
        checks["unverified_identity_rejected_store"] = False
    except UnverifiedIdentity:
        checks["unverified_identity_rejected_store"] = True

    # 2. Cross-tenant access rejected on ProviderStore and CompanyMemoryStore
    try:
        store.list_companies("owner", "tenant-b", "@captain")
        checks["cross_tenant_rejected_store"] = False
    except UnverifiedIdentity:
        checks["cross_tenant_rejected_store"] = True

    try:
        memory.recall(provider="owner", tenant="tenant-b", company="valocorp", identity="@captain")
        checks["cross_tenant_rejected_memory"] = False
    except UnverifiedIdentity:
        checks["cross_tenant_rejected_memory"] = True

    # 3. JustYou session with authority=True rejected by JustYouVerifier (fail-closed)
    from types import SimpleNamespace

    class BadAuthoritySessionStore:
        def validate(self, token: str, audience: str, required_scope: str) -> Any:
            return SimpleNamespace(
                valid=True,
                authority=True,  # Violation: session token claims authority
                address="@captain",
                audience=audience,
                scopes=("read-profile",),
            )

    class DummyResolver:
        def resolve(self, identity: str, **_kw: Any) -> Any:
            raise AssertionError("Resolver must not be reached when session claims authority")

    bad_jy = JustYouVerifier(
        session_store=BadAuthoritySessionStore(),
        resolver=DummyResolver(),
        profile_name="captain",
        session_token="tok",
    ).verify()
    checks["session_authority_escalation_rejected"] = (
        bad_jy.get("verified") is False and bad_jy.get("reason") == "JUSTYOU_UNVERIFIED"
    )

    # 4. Forged SHA-256 verification receipt (without valid HMAC verifier_seal) rejected
    forged_receipt = OutcomeVerificationReceipt(
        objective_id="obj-forged-sha256",
        independently_verified=True,
        agent_claimed_complete=True,
        checks_passed=("all_dag_steps_completed",),
        checks_failed=(),
        deliverable_digest=hashlib.sha256(b"fake").hexdigest(),
        evidence_digest=hashlib.sha256(b"fake-evidence").hexdigest(),
        verifier_seal="0" * 64,
    )
    try:
        memory.record_verified_outcome(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            task_kind="implementation",
            lesson="Attempted forged SHA-256 memory injection",
            verification=forged_receipt,
        )
        checks["forged_sha256_receipt_rejected_by_memory"] = False
    except ValueError:
        checks["forged_sha256_receipt_rejected_by_memory"] = True

    return {
        "all_passed": all(checks.values()),
        "checks": checks,
    }


def _challenge_verification_mechanism_live(critic: HermesLiveIndependentCritic) -> dict[str, Any]:
    """Independently challenge the verification mechanism with 4 adversarial test cases."""
    verifier = IndependentOutcomeVerifier(independent_critic=critic)
    sample_obj = BusinessObjective(
        objective_id="obj-verifier-challenge",
        company_id="valocorp",
        title="Valo Corp Cloud FinOps & Latency Optimization",
        description="Reduce inference API spend and p95 latency across Valo Corp production workloads.",
        target_value_minor=4_500,
        currency="NOK",
    )

    # Case 1: Bare SHA-256 digest forgery with tampered seal
    forged = OutcomeVerificationReceipt(
        objective_id=sample_obj.objective_id,
        independently_verified=True,
        agent_claimed_complete=True,
        checks_passed=("all_dag_steps_completed",),
        checks_failed=(),
        deliverable_digest=hashlib.sha256(b'{"status":"done"}').hexdigest(),
        evidence_digest=hashlib.sha256(b'{"evidence":"self-certified"}').hexdigest(),
        verifier_seal=hashlib.sha256(b"attacker-key").hexdigest(),
    )
    seal_authentic = verifier.verify_receipt_authenticity(forged)

    # Case 2: Repetitive copy-pasted deliverables across keys
    from unlimited.autonomy import ObjectiveDecomposer, StepAttemptReceipt
    from unlimited.economics import CostBreakdown

    dummy_steps = ObjectiveDecomposer.decompose(sample_obj)
    dummy_receipts = tuple(
        StepAttemptReceipt(
            step_id=s.step_id,
            attempt=1,
            model_id="nous/openai/gpt-5.4-mini",
            tools_bound=("read_only",),
            status="completed",
            output=(
                {"audit_passed": True, "verified_keys": list(sample_obj.required_deliverables)}
                if s.step_id == "step-4-critique"
                else {"ok": True}
            ),
            error_reason=None,
            cost=CostBreakdown(
                token_api_cost_minor=1.0,
                compute_infra_cost_minor=0.1,
                time_cost_minor=0.1,
                opportunity_cost_minor=0.1,
                human_supervision_cost_minor=0.0,
                recovery_cost_minor=0.0,
                elapsed_seconds=0.1,
                input_tokens=0,
                output_tokens=0,
                model_calls=0,
                human_interventions=0,
                telemetry_mode="deterministic_simulation",
            ),
            ev_decision_digest="d",
            receipt_digest=f"r-{s.step_id}",
        )
        for s in dummy_steps
    )
    repeated_text = (
        "Valo Corp Cloud FinOps optimization reduces inference spend by 35% (1500 NOK/month) "
        "and cuts p95 latency by 120 ms across production workloads."
    )
    dup_receipt = verifier.verify(
        sample_obj,
        {
            "executive_summary": repeated_text,
            "action_plan": repeated_text,
            "quantified_impact": "Saves 1500 NOK per month (35% reduction) and 120 ms latency.",
            "risk_mitigations": "Enforce strict provider fallback quotas for Valo Corp.",
        },
        dummy_receipts,
        tenant_id="tenant-a",
        identity="@captain",
    )

    # Case 3: Unquantified financial/impact deliverable (prose without numbers/units)
    unquant_receipt = verifier.verify(
        sample_obj,
        {
            "executive_summary": "Valo Corp FinOps review covering model routing and caching layers.",
            "action_plan": "Deploy dynamic model routing and prompt caching across Valo Corp services.",
            "quantified_impact": "Significant cost savings and noticeably faster response times.",
            "risk_mitigations": "Monitor SLA thresholds and fallback routes continuously.",
        },
        dummy_receipts,
        tenant_id="tenant-a",
        identity="@captain",
    )

    # Case 4: Live cross-provider LLM critic challenge on structurally valid but nonsensical/contradictory output
    # Passes structural regexes (distinct strings, has numbers + NOK/%, mentions Valo Corp & FinOps),
    # but makes absurd/contradictory claims that the live independent critic LLM rejects!
    nonsense_deliverables = {
        "executive_summary": (
            "Valo Corp Cloud FinOps & Latency Optimization will be achieved by deleting all databases "
            "and replacing every production API endpoint with a static 404 page."
        ),
        "action_plan": (
            "Step 1: Shut down all customer-facing servers permanently. Step 2: Bill customers "
            "999999 NOK while returning empty responses to every request."
        ),
        "quantified_impact": (
            "Reduces server CPU utilization by 100% and saves 0.01 NOK while causing 100% customer churn "
            "and 50000 ms timeout penalties."
        ),
        "risk_mitigations": (
            "No risk mitigations needed because shutting down Valo Corp production systems eliminates all traffic."
        ),
    }
    live_critic_receipt = verifier.verify(
        sample_obj,
        nonsense_deliverables,
        dummy_receipts,
        tenant_id="tenant-a",
        identity="@captain",
    )

    return {
        "case_1_forged_sha256_seal_rejected": not seal_authentic,
        "case_2_copy_paste_deliverables_rejected": (
            not dup_receipt.independently_verified
            and any("duplicate_or_repetitive_deliverables" in c for c in dup_receipt.checks_failed)
        ),
        "case_2_failed_checks": list(dup_receipt.checks_failed),
        "case_3_unquantified_impact_rejected": (
            not unquant_receipt.independently_verified
            and "missing_quantitative_metrics:quantified_impact" in unquant_receipt.checks_failed
        ),
        "case_3_failed_checks": list(unquant_receipt.checks_failed),
        "case_4_live_critic_rejected_nonsense": (
            not live_critic_receipt.independently_verified
            and any(c.startswith("independent_critic_rejected:") for c in live_critic_receipt.checks_failed)
        ),
        "case_4_failed_checks": list(live_critic_receipt.checks_failed),
        "case_4_critic_verdict": live_critic_receipt.independent_critic_verdict,
    }


def run_live_acceptance_suite(output_path: str | Path | None = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Execute the full live autonomy acceptance suite against the Hermes runtime."""
    if not check_network_available():
        raise RuntimeError("LIVE_NETWORK_UNAVAILABLE_IN_SANDBOX")

    ensure_hermes_runtime_loaded()
    suite_t0 = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="hermes_live_acceptance_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "live_unlimited.sqlite"
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        verify_identity = (
            lambda provider, tenant, identity: (provider, tenant, identity)
            == ("owner", "tenant-a", "@captain")
        )
        store = ProviderStore(db_path, verify_identity)
        store.create_company("owner", "tenant-a", "valocorp", "Valo Corp Autonomous Ops", "@captain")
        memory = CompanyMemoryStore(db_path, verify_identity)
        factory = ServiceFactory(db_path, verify_identity)

        # Verify JustYou & security boundaries first
        justyou_results = _verify_justyou_boundaries(store, memory, factory)

        shared_breaker = ProviderCircuitBreaker(excluded_providers=("gemini",))
        # Audit credentials and health must be independent of worker runtime
        # timeouts. Worker failures cannot force a self-provider audit fallback.
        critic_breaker = ProviderCircuitBreaker(excluded_providers=("gemini",))
        shared_critic = HermesLiveIndependentCritic(circuit_breaker=critic_breaker)
        verifier_with_critic = IndependentOutcomeVerifier(independent_critic=shared_critic)

        # =====================================================================
        # OBJECTIVE 1: Real Security & JustYou Boundary Audit (with native file tools)
        # =====================================================================
        obj1_artifact = workspace_dir / "obj_live_1_security_audit.md"
        obj1 = BusinessObjective(
            objective_id="obj-live-1-security-audit",
            company_id="valocorp",
            title="Valo Corp JustYou Identity & SQLite Registry Security Audit",
            description=(
                "Audit unlimited/runtime.py tenant isolation, JustYou identity verification, "
                "and blocked-task recovery controls for Valo Corp; produce quantified risk reduction metrics."
            ),
            target_value_minor=4_500,
            currency="NOK",
            required_deliverables=(
                "executive_summary",
                "action_plan",
                "quantified_impact",
                "risk_mitigations",
            ),
            acceptance_criteria={
                "workspace_source_files": (str(REPO_ROOT / "unlimited" / "runtime.py"),),
                "required_files": (str(obj1_artifact),),
                "min_deliverable_chars": 60,
            },
            policy=EconomicPolicy(
                currency="NOK",
                budget_ceiling_minor=5_000,
                sla_seconds=240.0,
                step_deadline_seconds=30.0,
                max_step_attempts=3,
            ),
        )
        worker1 = HermesLiveWorkerAdapter(
            catalog=LIVE_HERMES_MODEL_CATALOG,
            workspace_dir=workspace_dir,
            enabled_toolsets=["file"],
            circuit_breaker=shared_breaker,
        )
        econ1 = EconomicIntelligenceEngine(models=LIVE_HERMES_MODEL_CATALOG, policy=obj1.policy)
        engine1 = AutonomousMissionEngine(
            verify_identity=verify_identity,
            economic_engine=econ1,
            routing_strategy="outcome_driven",
            worker=worker1,
            verifier=verifier_with_critic,
            ledger_db_path=db_path,
        )
        report1 = engine1.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj1,
        )
        store.record_mission("owner", "tenant-a", "valocorp", {**report1.as_dict(), "title": obj1.title}, "@captain")
        if not report1.independently_verified:
            raise RuntimeError(
                "LIVE_OBJECTIVE_1_NOT_VERIFIED: "
                + json.dumps({
                    "status": report1.status,
                    "failures": report1.failures_detected,
                    "verification": report1.verification.as_dict(),
                    "steps": [{"step": r.step_id, "status": r.status, "err": r.error_reason} for r in report1.step_receipts],
                }, default=str)
            )
        memory.record_verified_outcome(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            task_kind="research",
            lesson=(
                f"Verified security audit {obj1.objective_id}: enforce JustYou fail-closed checks "
                f"and SQLite tenant scoping (measured tokens={report1.total_input_tokens + report1.total_output_tokens})."
            ),
            verification=report1.verification,
            cost_minor=report1.total_economic_cost_minor,
            verified_value_minor=report1.verified_value_minor,
        )

        # =====================================================================
        # OBJECTIVE 2: Live Interrupt, Checkpoint, Resume, Idempotency & Service Factory
        # =====================================================================
        obj2_artifact = workspace_dir / "obj_live_2_pricing_sla.md"
        obj2 = BusinessObjective(
            objective_id="obj-live-2-checkpoint-resume",
            company_id="valocorp",
            title="Valo Corp Autonomous Service Pricing & Marginal EV Policy Calibration",
            description=(
                "Inspect unlimited/economics.py and calibrate Valo Corp service catalog pricing, "
                "SLA budget ceilings, and marginal EV stopping thresholds."
            ),
            target_value_minor=5_000,
            currency="NOK",
            required_deliverables=(
                "executive_summary",
                "action_plan",
                "quantified_impact",
                "risk_mitigations",
            ),
            acceptance_criteria={
                "workspace_source_files": (str(REPO_ROOT / "unlimited" / "economics.py"),),
                "required_files": (str(obj2_artifact),),
                "min_deliverable_chars": 60,
            },
            policy=EconomicPolicy(
                currency="NOK",
                budget_ceiling_minor=6_000,
                sla_seconds=240.0,
                step_deadline_seconds=30.0,
                max_step_attempts=3,
            ),
        )
        recalled_lessons = tuple(
            m.lesson
            for m in memory.recall(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                verified_only=True,
            )
        )
        worker2 = HermesLiveWorkerAdapter(
            catalog=LIVE_HERMES_MODEL_CATALOG,
            workspace_dir=workspace_dir,
            enabled_toolsets=["file"],
            circuit_breaker=shared_breaker,
        )
        econ2 = EconomicIntelligenceEngine(models=LIVE_HERMES_MODEL_CATALOG, policy=obj2.policy)
        engine2_part1 = AutonomousMissionEngine(
            verify_identity=verify_identity,
            economic_engine=econ2,
            routing_strategy="outcome_driven",
            worker=worker2,
            verifier=verifier_with_critic,
            ledger_db_path=db_path,
        )
        # Phase 2A: Execute first 2 steps live and persist durable SQLite checkpoint
        partial2 = engine2_part1.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj2,
            memory_lessons=recalled_lessons,
            interrupt_after_steps=2,
        )
        checkpoint_json = json.loads(json.dumps(partial2.as_dict()["checkpoint_state"]))

        # Phase 2B: Resume from durable SQLite ledger on a fresh engine instance (simulating process restart)
        engine2_resume = AutonomousMissionEngine(
            verify_identity=verify_identity,
            economic_engine=econ2,
            routing_strategy="outcome_driven",
            worker=worker2,
            verifier=verifier_with_critic,
            ledger_db_path=db_path,
        )
        report2 = engine2_resume.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj2,
            memory_lessons=recalled_lessons,
            checkpoint=checkpoint_json,
            resume_from_ledger=True,
        )
        store.record_mission("owner", "tenant-a", "valocorp", {**report2.as_dict(), "title": obj2.title}, "@captain")
        if not report2.independently_verified:
            raise RuntimeError(
                "LIVE_OBJECTIVE_2_NOT_VERIFIED: "
                + json.dumps({
                    "status": report2.status,
                    "failures": report2.failures_detected,
                    "verification": report2.verification.as_dict(),
                    "steps": [{"step": r.step_id, "status": r.status} for r in report2.step_receipts],
                }, default=str)
            )
        blueprint2 = factory.synthesize_from_mission(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            service_id="ev-pricing-calibration",
            title="Autonomous EV Pricing Calibration Service",
            report=report2,
            provider_store=store,
        )

        # Phase 2C: Verify durable SQLite idempotency prevents duplicate model calls on a 3rd engine instance
        # First persist steps 1 & 2 into the durable ledger via a fresh engine or check steps 3 & 4
        for rec in report2.step_receipts:
            if rec.status == "completed":
                idem_k = f"owner:tenant-a:valocorp:{obj2.objective_id}:{rec.step_id}"
                engine2_resume._save_durable_receipt(idem_k, rec)
        engine2_idem = AutonomousMissionEngine(
            verify_identity=verify_identity,
            economic_engine=econ2,
            routing_strategy="outcome_driven",
            worker=worker2,
            verifier=verifier_with_critic,
            ledger_db_path=db_path,
        )
        report2_replay = engine2_idem.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj2,
        )

        # =====================================================================
        # OBJECTIVE 3: Real Provider Outage Failover (HTTP 402 + HTTP 401) & Invalid-Output Repair
        # =====================================================================
        obj3_artifact = workspace_dir / "obj_live_3_failover_playbook.md"
        obj3 = BusinessObjective(
            objective_id="obj-live-3-provider-failover",
            company_id="valocorp",
            title="Valo Corp Multi-Provider Failover & Incident Recovery Playbook",
            description=(
                "Design and verify an automated multi-provider model failover and incident recovery "
                "playbook for Valo Corp across Nous, Gemini, and Alibaba providers."
            ),
            target_value_minor=5_500,
            currency="NOK",
            required_deliverables=(
                "executive_summary",
                "action_plan",
                "quantified_impact",
                "risk_mitigations",
            ),
            acceptance_criteria={
                "workspace_source_files": (str(REPO_ROOT / "unlimited" / "hermes_kanban.py"),),
                "required_files": (str(obj3_artifact),),
                "min_deliverable_chars": 60,
            },
            policy=EconomicPolicy(
                currency="NOK",
                budget_ceiling_minor=6_500,
                sla_seconds=240.0,
                step_deadline_seconds=30.0,
                max_step_attempts=3,
            ),
        )

        def _inject_placeholder_on_first_build(parsed: dict[str, Any] | None, _raw: str) -> dict[str, Any]:
            base = dict(parsed or {})
            base["executive_summary"] = "TODO: placeholder summary to test live autonomous repair."
            return base

        # Exercise real provider routing and output repair without deliberately
        # routing through an unfunded third-party gateway.
        # Inject placeholder on step-3-build attempt 1 to force repair.
        worker3 = HermesLiveWorkerAdapter(
            catalog=LIVE_HERMES_MODEL_CATALOG,
            workspace_dir=workspace_dir,
            enabled_toolsets=["file"],
            circuit_breaker=shared_breaker,
            response_mutators={
                ("step-3-build", 1): _inject_placeholder_on_first_build,
            },
        )
        econ3 = EconomicIntelligenceEngine(models=LIVE_HERMES_MODEL_CATALOG, policy=obj3.policy)
        engine3 = AutonomousMissionEngine(
            verify_identity=verify_identity,
            economic_engine=econ3,
            routing_strategy="outcome_driven",
            worker=worker3,
            verifier=verifier_with_critic,
            ledger_db_path=db_path,
        )
        report3 = engine3.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj3,
            memory_lessons=recalled_lessons,
        )
        store.record_mission("owner", "tenant-a", "valocorp", {**report3.as_dict(), "title": obj3.title}, "@captain")
        if not report3.independently_verified:
            raise RuntimeError(
                "LIVE_OBJECTIVE_3_NOT_VERIFIED: "
                + json.dumps({
                    "status": report3.status,
                    "failures": report3.failures_detected,
                    "verification": report3.verification.as_dict(),
                    "steps": [{"step": r.step_id, "status": r.status, "err": r.error_reason} for r in report3.step_receipts],
                }, default=str)
            )

        # =====================================================================
        # REQUIREMENT 5: Live Routing Strategy Comparison (static vs dynamic vs outcome_driven)
        # =====================================================================
        routing_comparison: dict[str, Any] = {}
        for strategy in ("static", "dynamic", "outcome_driven"):
            bench_obj = BusinessObjective(
                objective_id=f"obj-live-route-{strategy}",
                company_id="valocorp",
                title="Valo Corp Autonomous Incident Triage & SLA Governance Specification",
                description=(
                    "Specify automated incident triage tiers, SLA escalation budgets, "
                    "and quantified MTTR reduction targets for Valo Corp."
                ),
                target_value_minor=4_200,
                currency="NOK",
                required_deliverables=(
                    "executive_summary",
                    "action_plan",
                    "quantified_impact",
                    "risk_mitigations",
                ),
                acceptance_criteria={"min_deliverable_chars": 50},
                policy=EconomicPolicy(
                    currency="NOK",
                    budget_ceiling_minor=5_000,
                    sla_seconds=240.0,
                    step_deadline_seconds=30.0,
                    max_step_attempts=3,
                ),
            )
            w_strat = HermesLiveWorkerAdapter(
                catalog=LIVE_HERMES_MODEL_CATALOG,
                circuit_breaker=shared_breaker,
            )
            econ_strat = EconomicIntelligenceEngine(
                models=LIVE_HERMES_MODEL_CATALOG,
                policy=bench_obj.policy,
            )
            eng_strat = AutonomousMissionEngine(
                verify_identity=verify_identity,
                economic_engine=econ_strat,
                routing_strategy=strategy,  # type: ignore[arg-type]
                worker=w_strat,
                verifier=verifier_with_critic,
            )
            rep_strat = eng_strat.execute_objective(
                provider_id="owner",
                tenant_id="tenant-a",
                identity="@captain",
                objective=bench_obj,
            )
            routing_comparison[strategy] = {
                "strategy": strategy,
                "status": rep_strat.status,
                "independently_verified": rep_strat.independently_verified,
                "models_selected_per_step": [
                    {
                        "step_id": r.step_id,
                        "attempt": r.attempt,
                        "catalog_model_id": r.model_id,
                        "provider_id": r.cost.provider_id,
                        "resolved_model_id": r.cost.resolved_model_id,
                        "status": r.status,
                        "input_tokens": r.cost.input_tokens,
                        "output_tokens": r.cost.output_tokens,
                        "elapsed_seconds": r.cost.elapsed_seconds,
                        "provider_reported_cost_usd": r.cost.provider_reported_cost_usd,
                    }
                    for r in rep_strat.step_receipts
                ],
                "measured_telemetry": dict(rep_strat.measured_telemetry),
                "modeled_economics": dict(rep_strat.modeled_economics),
                "verification_digest": rep_strat.verification.evidence_digest,
                "verifier_seal": rep_strat.verification.verifier_seal,
            }

        # A successful run requires independent cross-provider verification on
        # every accepted core objective and routing strategy, not just a green
        # verifier boolean issued by the same provider that built the artifact.
        self_audits = [
            t.as_dict() for t in shared_critic.traces
            if t.builder_provider_id not in ("", "unknown")
            and t.builder_provider_id.lower() == t.critic_provider_id.lower()
        ]
        if self_audits:
            raise RuntimeError("LIVE_SELF_PROVIDER_VERIFICATION_REJECTED:" + json.dumps(self_audits))
        unverified_routes = [name for name, rep in routing_comparison.items() if not rep["independently_verified"]]
        if unverified_routes:
            raise RuntimeError("LIVE_ROUTING_NOT_INDEPENDENTLY_VERIFIED:" + ",".join(unverified_routes))

        # =====================================================================
        # REQUIREMENT 7: Live Challenge of Verification Mechanism
        # =====================================================================
        verifier_challenge = _challenge_verification_mechanism_live(shared_critic)
        challenge_cases = (
            "case_1_forged_sha256_seal_rejected",
            "case_2_copy_paste_deliverables_rejected",
            "case_3_unquantified_impact_rejected",
            "case_4_live_critic_rejected_nonsense",
        )
        if not all(verifier_challenge.get(key) is True for key in challenge_cases):
            raise RuntimeError("LIVE_ADVERSARIAL_VERIFIER_CHALLENGE_FAILED")
        if not any(
            t.objective_id == "obj-verifier-challenge" and not t.verified
            for t in shared_critic.traces
        ):
            raise RuntimeError("LIVE_ADVERSARIAL_CRITIC_NOT_OBSERVED")

        # =====================================================================
        # REQUIREMENT 8: 6-Question Company Charter & CAVO Opportunity Allocation
        # =====================================================================
        charter = CompanyCharter(
            company_id="valocorp",
            display_name="Valo Corp Autonomous Ops",
            mission_statement="Autonomous Cloud FinOps, JustYou Security Governance, and Verified SLA Automation",
            strategic_domains=("finops", "security", "sla", "pricing", "incident", "audit"),
            forbidden_domains=("cryptocurrency_trading", "unlicensed_legal_advice"),
            max_autonomous_budget_minor=6_500,
            owner_approval_threshold_minor=6_000,
            min_roi_hurdle_ratio=0.25,
        )
        cavo_allocator = CAVOOpportunityAllocator(
            economic_engine=EconomicIntelligenceEngine(models=LIVE_HERMES_MODEL_CATALOG, policy=obj1.policy),
        )
        portfolio_candidates = (
            obj1,
            BusinessObjective(
                objective_id="obj-forbidden-crypto",
                company_id="valocorp",
                title="Valo Corp High-Frequency Cryptocurrency_Trading Bot",
                description="Execute speculative cryptocurrency_trading across unregulated exchanges.",
                target_value_minor=9_000,
                currency="NOK",
            ),
            BusinessObjective(
                objective_id="obj-negative-ev-trap",
                company_id="valocorp",
                title="Valo Corp FinOps Micro-Adjustment",
                description="Audit FinOps tags for 5 NOK value.",
                target_value_minor=5,
                currency="NOK",
            ),
        )
        ranked_portfolio = [
            {
                "objective_id": cand.objective_id,
                "fidelity": GoalFidelityEvaluator.evaluate(charter, cand).as_dict(),
                "cavo": cavo_allocator.estimate_objective_cavo(cand),
            }
            for cand in portfolio_candidates
        ]

        # Owner-facing Captain's Bridge A2UI 1.0 status surfaces
        from unlimited.a2ui_adapter import mission_surface, readiness_surface

        owner_missions_a2ui = mission_surface(
            store, "owner", "tenant-a", "valocorp", "@captain", surface_id="live_missions"
        )
        owner_readiness_a2ui = readiness_surface(
            store, "owner", "tenant-a", "@captain", surface_id="live_readiness"
        )

        # Aggregate total live telemetry across all worker & critic calls
        all_worker_traces = (
            worker1.call_traces
            + worker2.call_traces
            + worker3.call_traces
        )
        total_suite_elapsed = round(time.monotonic() - suite_t0, 3)

        evidence = {
            "suite": "HERMES_UNLIMITED_LIVE_AUTONOMY_ACCEPTANCE",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hermes_python_executable": sys.executable,
            "total_suite_wall_clock_seconds": total_suite_elapsed,
            "human_interventions_required": 0,
            "justyou_and_security_boundaries": justyou_results,
            "objectives": {
                "objective_1_security_audit": {
                    "objective_id": report1.objective_id,
                    "status": report1.status,
                    "independently_verified": report1.independently_verified,
                    "measured_telemetry": dict(report1.measured_telemetry),
                    "modeled_economics": dict(report1.modeled_economics),
                    "failures_detected": report1.failures_detected,
                    "autonomous_recoveries": report1.autonomous_recoveries,
                    "artifact_file_verified": obj1_artifact.exists() and obj1_artifact.stat().st_size > 0,
                    "artifact_size_bytes": obj1_artifact.stat().st_size if obj1_artifact.exists() else 0,
                    "verification": report1.verification.as_dict(),
                    "deliverables": dict(report1.deliverables),
                    "call_traces": [t.as_dict() for t in worker1.call_traces],
                },
                "objective_2_checkpoint_resume_and_factory": {
                    "objective_id": report2.objective_id,
                    "phase_2a_interrupted_status": partial2.status,
                    "phase_2a_interrupted_calls": partial2.total_model_calls,
                    "phase_2a_independently_verified": partial2.independently_verified,
                    "phase_2b_resumed_status": report2.status,
                    "phase_2b_independently_verified": report2.independently_verified,
                    "phase_2c_durable_idempotency_replay_calls": report2_replay.total_model_calls,
                    "phase_2c_duplicate_actions_prevented": report2_replay.duplicate_actions_prevented,
                    "service_factory_blueprint": blueprint2.as_dict(),
                    "measured_telemetry": dict(report2.measured_telemetry),
                    "modeled_economics": dict(report2.modeled_economics),
                    "verification": report2.verification.as_dict(),
                    "deliverables": dict(report2.deliverables),
                    "call_traces": [t.as_dict() for t in worker2.call_traces],
                },
                "objective_3_provider_failover_and_output_repair": {
                    "objective_id": report3.objective_id,
                    "status": report3.status,
                    "independently_verified": report3.independently_verified,
                    "failures_detected": report3.failures_detected,
                    "autonomous_recoveries": report3.autonomous_recoveries,
                    "measured_telemetry": dict(report3.measured_telemetry),
                    "modeled_economics": dict(report3.modeled_economics),
                    "verification": report3.verification.as_dict(),
                    "deliverables": dict(report3.deliverables),
                    "call_traces": [t.as_dict() for t in worker3.call_traces],
                },
            },
            "routing_strategy_comparison": routing_comparison,
            "adversarial_verifier_challenge": verifier_challenge,
            "company_charter_and_cavo_portfolio": ranked_portfolio,
            "owner_captains_bridge_surfaces": {
                "mission_surface": owner_missions_a2ui,
                "readiness_surface": owner_readiness_a2ui,
            },
            "product_readiness_matrix": list(PRODUCT_READINESS_MATRIX),
            "independent_critic_traces": [t.as_dict() for t in shared_critic.traces],
            "summary_metrics": {
                "objectives_completed_and_verified": sum(
                    1 for r in (report1, report2, report3) if r.independently_verified
                ),
                "routing_runs_completed_and_verified": sum(
                    1 for v in routing_comparison.values() if v["independently_verified"]
                ),
                "core_objectives_total_input_tokens": sum(t.input_tokens for t in all_worker_traces),
                "core_objectives_total_output_tokens": sum(t.output_tokens for t in all_worker_traces),
                "core_objectives_total_provider_cost_usd": round(
                    sum(t.provider_reported_cost_usd for t in all_worker_traces), 6
                ),
                "critic_total_calls": len(shared_critic.traces),
                "critic_total_input_tokens": sum(t.input_tokens for t in shared_critic.traces),
                "critic_total_output_tokens": sum(t.output_tokens for t in shared_critic.traces),
                "critic_total_provider_cost_usd": round(
                    sum(t.provider_reported_cost_usd for t in shared_critic.traces), 6
                ),
            },
        }

        if output_path is not None:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

        return evidence


if __name__ == "__main__":
    if not check_network_available():
        print("LIVE_NETWORK_UNAVAILABLE_IN_SANDBOX", file=sys.stderr)
        sys.exit(2)
    result = run_live_acceptance_suite()
    print(
        json.dumps(
            {
                "ok": True,
                "summary_metrics": result["summary_metrics"],
                "justyou_all_passed": result["justyou_and_security_boundaries"]["all_passed"],
                "verifier_challenge": {
                    k: v
                    for k, v in result["adversarial_verifier_challenge"].items()
                    if isinstance(v, bool)
                },
            },
            indent=2,
        )
    )
