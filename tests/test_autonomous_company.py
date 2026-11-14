"""Comprehensive tests for Autonomous Mission Engine, Economic Intelligence,
Company Memory, Service Factory, Blocked Dispatch Recovery, and Security Boundaries.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unlimited.a2ui_adapter import mission_surface
from unlimited.autonomy import (
    AutonomousMissionEngine,
    BusinessObjective,
    IndependentOutcomeVerifier,
    StepWorkerResult,
    WorkStep,
    default_deterministic_worker,
)
from unlimited.benchmark import run_routing_comparison
from unlimited.economics import (
    EconomicIntelligenceEngine,
    EconomicPolicy,
    ModelRouter,
)
from unlimited.memory_factory import CompanyMemoryStore, ServiceFactory
from unlimited.runtime import ProviderStore, UnverifiedIdentity

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AutonomousCompanyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp.name) / "unlimited.sqlite"
        self.verify = (
            lambda provider, tenant, identity: (provider, tenant, identity)
            == ("owner", "tenant-a", "@captain")
        )
        self.store = ProviderStore(self.db_path, self.verify)
        self.store.create_company("owner", "tenant-a", "valocorp", "Valo Corp", "@captain")
        self.memory = CompanyMemoryStore(self.db_path, self.verify)
        self.factory = ServiceFactory(self.db_path, self.verify)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _objective(self, **overrides) -> BusinessObjective:
        defaults = dict(
            objective_id="obj-alpha",
            company_id="valocorp",
            title="Autonomous Revenue Operations Audit",
            description="Deliver verified revenue leakage analysis and remediation plan.",
            target_value_minor=4_000,
            currency="NOK",
            required_deliverables=(
                "executive_summary",
                "action_plan",
                "quantified_impact",
                "risk_mitigations",
            ),
            policy=EconomicPolicy(
                currency="NOK",
                budget_ceiling_minor=5_000,
                sla_seconds=240.0,
                max_step_attempts=3,
            ),
        )
        defaults.update(overrides)
        return BusinessObjective(**defaults)

    def test_1_normal_autonomous_operation_and_stop_when_complete(self) -> None:
        engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            routing_strategy="outcome_driven",
        )
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(),
        )
        self.assertEqual(report.status, "VERIFIED_COMPLETE")
        self.assertTrue(report.independently_verified)
        self.assertEqual(report.verified_value_minor, 4_000)
        self.assertGreater(report.net_economic_value_minor, 0.0)
        self.assertEqual(report.human_interventions_required, 0)
        self.assertEqual(report.failures_detected, 0)
        self.assertEqual(report.total_model_calls, 4)
        # Verify post-completion stopping gate fired
        self.assertEqual(report.ev_decisions[-1]["verdict"], "STOP_OBJECTIVE_COMPLETE")
        self.assertFalse(report.ev_decisions[-1]["economically_justified"])

    def test_2_failure_detection_and_autonomous_recovery(self) -> None:
        calls = []

        def flaky_worker(step, model_id, attempt, ctx, hints):
            calls.append((step.step_id, model_id, attempt, hints))
            if step.step_id == "step-2-research" and attempt == 1:
                return StepWorkerResult(
                    status="runtime_error",
                    output=None,
                    input_tokens=300,
                    output_tokens=0,
                    latency_sec=1.5,
                    error_message="SANDBOX_WORKER_CRASH",
                )
            return default_deterministic_worker(step, model_id, attempt, ctx, hints)

        engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            routing_strategy="outcome_driven",
            worker=flaky_worker,
        )
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(),
        )
        self.assertEqual(report.status, "VERIFIED_COMPLETE")
        self.assertTrue(report.independently_verified)
        self.assertEqual(report.failures_detected, 1)
        self.assertEqual(report.autonomous_recoveries, 1)
        self.assertGreater(report.recovery_spend_minor, 0.0)
        self.assertEqual(report.human_interventions_required, 0)

    def test_3_interrupted_execution_and_checkpoint_resume(self) -> None:
        engine = AutonomousMissionEngine(verify_identity=self.verify)
        obj = self._objective(objective_id="obj-resume")
        partial = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            interrupt_after_steps=2,
        )
        self.assertEqual(partial.status, "INTERRUPTED_CHECKPOINTED")
        self.assertFalse(partial.independently_verified)
        self.assertEqual(partial.verified_value_minor, 0)
        self.assertEqual(partial.total_model_calls, 2)

        # Resume from checkpoint: steps 1 and 2 must NOT be re-executed
        resumed = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            checkpoint=partial.checkpoint_state,
        )
        self.assertEqual(resumed.status, "VERIFIED_COMPLETE")
        self.assertTrue(resumed.independently_verified)
        self.assertEqual(resumed.total_model_calls, 4)
        self.assertEqual(resumed.verified_value_minor, 4_000)

        # Cross-tenant checkpoint resume must fail closed
        with self.assertRaises(PermissionError):
            engine.execute_objective(
                provider_id="owner",
                tenant_id="tenant-b",
                identity="@captain",
                objective=obj,
                checkpoint=partial.checkpoint_state,
            )

    def test_4_incorrect_model_output_rejected_and_repaired(self) -> None:
        def bad_first_build_worker(step, model_id, attempt, ctx, hints):
            if step.step_id == "step-3-build" and attempt == 1:
                # Emit placeholder output that claims success but violates quality gate
                return StepWorkerResult(
                    status="ok",
                    output={
                        "executive_summary": "TODO: fill in later",
                        "action_plan": "Valid plan here",
                        "quantified_impact": "Valid impact here",
                        "risk_mitigations": "Valid mitigations here",
                    },
                    input_tokens=900,
                    output_tokens=200,
                    latency_sec=2.0,
                )
            return default_deterministic_worker(step, model_id, attempt, ctx, hints)

        engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            worker=bad_first_build_worker,
        )
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-bad-output"),
        )
        self.assertEqual(report.status, "VERIFIED_COMPLETE")
        self.assertTrue(report.independently_verified)
        self.assertEqual(report.failures_detected, 1)
        self.assertEqual(report.autonomous_recoveries, 1)
        self.assertIn("repaired after 1 diagnostic feedback", report.deliverables["executive_summary"])

    def test_5_routing_failure_and_automatic_model_reroute(self) -> None:
        models_tried = []

        def outage_worker(step, model_id, attempt, ctx, hints):
            models_tried.append((step.step_id, model_id, attempt))
            if step.step_id == "step-1-triage" and attempt == 1:
                return StepWorkerResult(
                    status="routing_error",
                    output=None,
                    input_tokens=0,
                    output_tokens=0,
                    latency_sec=0.2,
                    error_message="PROVIDER_ROUTE_503",
                )
            return default_deterministic_worker(step, model_id, attempt, ctx, hints)

        engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            routing_strategy="outcome_driven",
            worker=outage_worker,
        )
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-route-fail"),
        )
        self.assertEqual(report.status, "VERIFIED_COMPLETE")
        self.assertEqual(report.failures_detected, 1)
        self.assertEqual(report.autonomous_recoveries, 1)
        # First attempt and second attempt on step-1-triage used different models
        step1_models = [m for s, m, _ in models_tried if s == "step-1-triage"]
        self.assertEqual(len(step1_models), 2)
        self.assertNotEqual(step1_models[0], step1_models[1])

    def test_6_duplicate_actions_prevented_by_idempotency_and_service_factory(self) -> None:
        engine = AutonomousMissionEngine(verify_identity=self.verify)
        obj = self._objective(objective_id="obj-idem")
        first = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
        )
        self.assertEqual(first.total_model_calls, 4)
        self.assertEqual(first.duplicate_actions_prevented, 0)

        # Re-running the same objective scope uses idempotency ledger with 0 model calls
        second = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
        )
        self.assertEqual(second.status, "VERIFIED_COMPLETE")
        self.assertEqual(second.total_model_calls, 0)
        self.assertEqual(second.duplicate_actions_prevented, 4)
        self.assertEqual(second.direct_cost_minor, 0.0)

        # Service Factory rejects duplicate minting from the same execution evidence digest
        bp = self.factory.synthesize_from_mission(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            service_id="rev-audit",
            title="Revenue Audit Service",
            report=first,
            provider_store=self.store,
        )
        self.assertTrue(bp.published_to_catalog)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EXECUTION_EVENT"):
            self.factory.synthesize_from_mission(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                service_id="rev-audit-2",
                title="Duplicate Service",
                report=first,
            )

    def test_7_cost_escalation_budget_sla_and_negative_ev_stopping(self) -> None:
        engine = AutonomousMissionEngine(verify_identity=self.verify)

        # Case A: Negative EV objective (target_value_minor=3 < step execution cost)
        neg_ev_obj = self._objective(objective_id="obj-neg-ev", target_value_minor=3)
        neg_report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=neg_ev_obj,
        )
        self.assertEqual(neg_report.status, "STOPPED_NEGATIVE_EV")
        self.assertFalse(neg_report.independently_verified)
        self.assertEqual(neg_report.total_model_calls, 0)
        self.assertEqual(neg_report.direct_cost_minor, 0.0)

        # Case B: Tight budget ceiling (budget_ceiling_minor=2) halts before overspending
        tight_budget_obj = self._objective(
            objective_id="obj-tight-budget",
            target_value_minor=5_000,
            policy=EconomicPolicy(budget_ceiling_minor=2, sla_seconds=240.0),
        )
        budget_report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=tight_budget_obj,
        )
        self.assertEqual(budget_report.status, "STOPPED_BUDGET_EXCEEDED")
        self.assertEqual(budget_report.total_model_calls, 0)

        # Case C: Tight SLA ceiling (sla_seconds=1.0) halts before violating SLA
        tight_sla_obj = self._objective(
            objective_id="obj-tight-sla",
            target_value_minor=5_000,
            policy=EconomicPolicy(budget_ceiling_minor=5_000, sla_seconds=1.0),
        )
        sla_report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=tight_sla_obj,
        )
        self.assertEqual(sla_report.status, "STOPPED_SLA_EXCEEDED")

        # Case D: Human intervention unjustified when human supervision cost > marginal value
        econ = EconomicIntelligenceEngine(
            policy=EconomicPolicy(human_intervention_cost_minor=2_500, budget_ceiling_minor=10_000)
        )
        human_dec = econ.evaluate_next_action(
            task_kind="implementation",
            candidate_model_id="gemini-4-argon",
            marginal_value_minor=1_200,
            require_human_supervision=True,
        )
        self.assertEqual(human_dec.verdict, "STOP_HUMAN_INTERVENTION_UNJUSTIFIED")
        self.assertFalse(human_dec.economically_justified)

    def test_8_incomplete_business_outcomes_rejected_by_independent_verifier(self) -> None:
        # Objective requires a custom domain invariant that the worker fails to satisfy
        obj = self._objective(
            objective_id="obj-strict-invariant",
            acceptance_criteria={
                "required_terms": ("iso-27001-annex-a",),
            },
        )
        engine = AutonomousMissionEngine(verify_identity=self.verify)
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
        )
        # Even though all 4 agent steps returned status="ok", the independent outcome
        # verifier detects the missing required domain evidence and refuses verification!
        self.assertEqual(report.status, "STOPPED_UNVERIFIED_OUTCOME")
        self.assertFalse(report.independently_verified)
        self.assertTrue(report.verification.agent_claimed_complete)
        self.assertEqual(report.verified_value_minor, 0)
        self.assertLess(report.net_economic_value_minor, 0.0)
        self.assertIn("missing_required_term:iso-27001-annex-a", report.verification.checks_failed)

        # Service Factory must refuse to synthesize a service from an unverified mission
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_VERIFICATION_REQUIRED"):
            self.factory.synthesize_from_mission(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                service_id="bad-svc",
                title="Unverified Service",
                report=report,
            )

    def test_9_company_memory_epistemic_separation_and_tenant_isolation(self) -> None:
        # Unverified self-report is stored as RECORDED_UNVERIFIED
        unv = self.memory.record_unverified(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            task_kind="triage",
            source_id="task-101",
            lesson="Self-reported agent note without independent proof.",
        )
        self.assertFalse(unv["independently_verified"])
        self.assertEqual(unv["classification"], "RECORDED_UNVERIFIED")
        # Duplicate harvest is recognized
        dup = self.memory.record_unverified(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            task_kind="triage",
            source_id="task-101",
            lesson="Self-reported agent note without independent proof.",
        )
        self.assertTrue(dup["duplicate"])

        # verified_only=True excludes RECORDED_UNVERIFIED entries
        self.assertEqual(
            self.memory.recall(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                verified_only=True,
            ),
            [],
        )

        # Cross-tenant recall fails closed
        with self.assertRaises(UnverifiedIdentity):
            self.memory.recall(
                provider="owner",
                tenant="tenant-b",
                company="valocorp",
                identity="@captain",
            )

    def test_10_native_tools_and_blocked_dispatch_recovery(self) -> None:
        settings = {
            "HERMES_UNLIMITED_PROVIDER_ID": "owner",
            "HERMES_UNLIMITED_TENANT_ID": "tenant-a",
            "HERMES_UNLIMITED_JUSTYOU_IDENTITY": "@owner",
            "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": "session",
            "HERMES_UNLIMITED_REGISTRY_DB": str(pathlib.Path(self.temp.name) / "tools.sqlite"),
        }
        agent = types.ModuleType("agent")
        agent.__path__ = []
        scope = types.ModuleType("agent.secret_scope")
        scope.get_secret = lambda name, default="": settings.get(name, default)

        class SessionStore:
            def validate(self, token, audience, required_scope):
                return SimpleNamespace(
                    valid=True, authority=False, address="@owner",
                    audience=audience, scopes=("read-profile",),
                )

        class Binding:
            identity, carrier, endpoint, version = "@owner", "hermes-profile", "hermes-profile:role-a", 1
            def digest(self):
                return "digest"

        class Resolver:
            def resolve(self, identity, **_kwargs):
                return Binding(), SimpleNamespace(
                    identity=identity, binding_digest="digest",
                    resolved_version=1, status="RESOLVED",
                )

        ctx = SimpleNamespace(
            profile_name="role-a",
            justyou_session_store=SessionStore(),
            justyou_resolver=Resolver(),
            handlers={},
        )
        ctx.get_config = lambda name, default="": settings.get(name, default)
        ctx.register_tool = lambda name, toolset, schema, handler: ctx.handlers.__setitem__(name, handler)
        # Explicit fixture-only host authorization and deterministic test worker.
        # Production runtime must never receive this synthetic worker by default.
        from unlimited.autonomy import IndependentOutcomeVerifier, default_deterministic_worker
        ctx.mission_verifier = IndependentOutcomeVerifier(
            independent_critic=lambda _obj, _deliverables, _context: {
                "verified": True, "score": 100, "reason": "test fixture only"
            }
        )
        ctx.authorize_mission = lambda tenant, identity, company, objective: (
            tenant == "tenant-a" and identity == "@owner" and company == "acme"
        )
        ctx.mission_worker = default_deterministic_worker

        submissions = []
        task_state = {"status": "blocked"}

        class FakeKanban:
            def __init__(self, **_kwargs):
                pass
            def enqueue(self, **kwargs):
                submissions.append(kwargs)
                return {"task_id": f"task-{len(submissions)}"}
            def result(self, **_kwargs):
                return {
                    "found": True,
                    "completed": task_state["status"] == "done",
                    "status": task_state["status"],
                    "independently_verified": False,
                }

        with patch.dict(sys.modules, {"agent": agent, "agent.secret_scope": scope}), \
                patch("unlimited.hermes_kanban.HermesKanban", FakeKanban):
            spec = importlib.util.spec_from_file_location("hu_entry", ROOT / "__init__.py")
            plugin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin)
            plugin.register(ctx)

            call = lambda name, args=None: json.loads(ctx.handlers[name](args or {}))

            # 1. Create company, publish service, request service
            self.assertTrue(call("unlimited_company_create", {"company_id": "acme", "display_name": "Acme AI"})["created"])
            self.assertTrue(call("unlimited_service_publish", {
                "company_id": "acme", "service_id": "ops", "title": "Ops",
                "price_minor": 1500, "currency": "NOK",
            })["published"])
            req = call("unlimited_service_request", {
                "company_id": "acme", "service_id": "ops", "request_id": "r1", "payload": {"k": "v"},
            })
            self.assertEqual(req["task_id"], "task-1")

            # 2. Task fails ('blocked') in Kanban -> record result -> recover via service_dispatch!
            res1 = call("unlimited_service_result", {"company_id": "acme", "request_id": "r1"})
            self.assertEqual(res1["status"], "blocked")
            recovered = call("unlimited_service_dispatch", {"company_id": "acme", "request_id": "r1"})
            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["task_id"], "task-2")
            self.assertEqual(recovered["previous_task_id"], "task-1")
            self.assertEqual(recovered["attempts"], 2)

            # 3. Run autonomous mission via native tool
            m_out = call("unlimited_mission_run", {
                "company_id": "acme",
                "objective_id": "mission-q4",
                "title": "Q4 Autonomous Expansion Plan",
                "target_value_minor": 3500,
                "routing_strategy": "outcome_driven",
            })
            self.assertTrue(m_out["ok"])
            self.assertEqual(m_out["status"], "VERIFIED_COMPLETE")
            self.assertTrue(m_out["independently_verified"])

            # 4. Recall verified memory lesson harvested from the mission
            mem_out = call("unlimited_memory_recall", {
                "company_id": "acme", "verified_only": True,
            })
            self.assertTrue(mem_out["ok"])
            self.assertEqual(len(mem_out["entries"]), 1)
            self.assertEqual(mem_out["entries"][0]["classification"], "VERIFIED_OUTCOME")

            # 5. Promote verified mission to Service Factory blueprint and published service
            sf_out = call("unlimited_service_factory", {
                "company_id": "acme",
                "objective_id": "mission-q4",
                "service_id": "q4-expansion-pkg",
                "title": "Q4 Expansion Package",
            })
            self.assertTrue(sf_out["ok"])
            self.assertTrue(sf_out["published_to_catalog"])

            # 6. Render A2UI 1.0 Captain's Bridge mission surface
            surf = call("unlimited_a2ui_surface", {
                "view": "missions", "company_id": "acme", "surface_id": "missions_1",
            })
            self.assertEqual(surf["version"], "1.0")
            self.assertIn("mission-q4", json.dumps(surf))
            self.assertIn("VERIFIED", json.dumps(surf))

            # 7. Run Socratic Council native tool
            from unlimited.socratic_council import QUESTIONS
            council_out = call("unlimited_socratic_council", {
                "question": "Should Acme expand into autonomous tier-1 support?",
                "answers": {k: f"Verified answer for {k}" for k, _ in QUESTIONS},
            })
            self.assertTrue(council_out["ok"])
            self.assertFalse(council_out["execution_authority"])
            self.assertEqual(len(council_out["digest"]), 64)

    def test_11_routing_comparison_benchmark_evidence(self) -> None:
        comparison = run_routing_comparison()
        routes = comparison["after_autonomous_engine"]["routing_comparison"]
        static_res = routes["static"]
        dynamic_res = routes["dynamic"]
        outcome_res = routes["outcome_driven"]

        # All 3 strategies verify the 4 positive-EV objectives and auto-stop the 1 negative-EV trap
        for res in (static_res, dynamic_res, outcome_res):
            self.assertEqual(res["positive_ev_objectives_verified"], 4)
            self.assertEqual(res["negative_ev_objectives_auto_stopped"], 1)
            self.assertEqual(res["human_interventions_required"], 0)

        # Outcome-driven routing achieves lower cost per verified outcome and higher net EV than static frontier routing
        self.assertLess(
            outcome_res["cost_per_verified_outcome_minor"],
            static_res["cost_per_verified_outcome_minor"],
        )
        self.assertGreater(
            outcome_res["total_net_economic_value_minor"],
            static_res["total_net_economic_value_minor"],
        )
        # Outcome-driven avoids the fast-model complex-build failure that hits naive dynamic routing
        self.assertLess(
            outcome_res["total_model_calls"],
            dynamic_res["total_model_calls"],
        )
        self.assertGreater(
            outcome_res["total_net_economic_value_minor"],
            dynamic_res["total_net_economic_value_minor"],
        )

    def test_12_verifier_audit_regressions_json_checkpoint_sla_reroute_and_factory_atomicity(self) -> None:
        # 1. JSON-roundtripped checkpoint_state preserves step_receipts and verifies on resume
        engine = AutonomousMissionEngine(verify_identity=self.verify)
        obj = self._objective(objective_id="obj-json-ckpt")
        partial = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            interrupt_after_steps=2,
        )
        json_roundtripped_ckpt = json.loads(json.dumps(partial.as_dict()["checkpoint_state"]))
        resumed = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            checkpoint=json_roundtripped_ckpt,
        )
        self.assertEqual(resumed.status, "VERIFIED_COMPLETE")
        self.assertTrue(resumed.independently_verified)

        # 2. SLA violation on slow frontier model triggers REROUTE_MODEL to faster model when allow_reroute=True
        econ = EconomicIntelligenceEngine(
            policy=EconomicPolicy(budget_ceiling_minor=10_000, sla_seconds=10.0)
        )
        sla_reroute = econ.evaluate_next_action(
            task_kind="triage",
            candidate_model_id="gemini-4-carbon",  # 14.0s mean latency > 10.0s SLA
            marginal_value_minor=1_500,
            allow_reroute=True,
        )
        self.assertEqual(sla_reroute.verdict, "REROUTE_MODEL")
        self.assertTrue(sla_reroute.economically_justified)
        self.assertIn(sla_reroute.recommended_model_id, ("gemini-4-hydrogen", "gemini-4-argon"))

        # 3. Duplicate ServiceFactory synthesis with same service_id raises DUPLICATE_EXECUTION_EVENT
        # before touching ProviderStore.publish_service
        self.factory.synthesize_from_mission(
            provider="owner",
            tenant="tenant-a",
            company="valocorp",
            identity="@captain",
            service_id="ckpt-svc",
            title="Checkpoint Service",
            report=resumed,
            provider_store=self.store,
        )
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EXECUTION_EVENT"):
            self.factory.synthesize_from_mission(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                service_id="ckpt-svc",
                title="Checkpoint Service",
                report=resumed,
                provider_store=self.store,
            )

    def test_13_adversarial_verifier_forgery_distinctness_quantification_and_durable_ledger(self) -> None:
        from dataclasses import replace
        from unlimited.autonomy import OutcomeVerificationReceipt

        # 1. Forged SHA-256 receipt without valid HMAC verifier_seal is rejected by Memory & Service Factory
        forged_receipt = OutcomeVerificationReceipt(
            objective_id="obj-forged",
            independently_verified=True,
            agent_claimed_complete=True,
            checks_passed=("all_dag_steps_completed",),
            checks_failed=(),
            deliverable_digest="a" * 64,
            evidence_digest="b" * 64,
            verifier_seal="c" * 64,
        )
        self.assertFalse(IndependentOutcomeVerifier().verify_receipt_authenticity(forged_receipt))
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_VERIFICATION_RECEIPT_REQUIRED"):
            self.memory.record_verified_outcome(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                task_kind="implementation",
                lesson="Attempted memory poisoning with forged SHA-256 receipt.",
                verification=forged_receipt,
            )

        # 2. Tampered deliverables after verification are rejected by ServiceFactory
        engine = AutonomousMissionEngine(verify_identity=self.verify, ledger_db_path=self.db_path)
        valid_report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-tamper-check"),
        )
        self.assertTrue(valid_report.independently_verified)
        tampered_report = replace(
            valid_report,
            deliverables={**valid_report.deliverables, "executive_summary": "Tampered post-verification text"},
        )
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_VERIFICATION_REQUIRED"):
            self.factory.synthesize_from_mission(
                provider="owner",
                tenant="tenant-a",
                company="valocorp",
                identity="@captain",
                service_id="tampered-svc",
                title="Tampered Service",
                report=tampered_report,
            )

        # 3. Durable SQLite idempotency ledger prevents re-execution across separate engine instances
        second_engine_instance = AutonomousMissionEngine(
            verify_identity=self.verify,
            ledger_db_path=self.db_path,
        )
        second_run = second_engine_instance.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-tamper-check"),
        )
        self.assertEqual(second_run.status, "VERIFIED_COMPLETE")
        self.assertEqual(second_run.total_model_calls, 0)
        self.assertEqual(second_run.duplicate_actions_prevented, 4)

        # 4. Copy-pasted repetitive deliverables and unquantified impact are rejected by IndependentOutcomeVerifier
        verifier = IndependentOutcomeVerifier()
        identical_text = (
            "Valo Corp revenue operations audit completed with 15% efficiency gain and 4000 NOK impact."
        )
        dup_ver = verifier.verify(
            self._objective(objective_id="obj-dup-deliv"),
            {
                "executive_summary": identical_text,
                "action_plan": identical_text,
                "quantified_impact": " saves 4000 NOK per month (15%)",
                "risk_mitigations": "Enforce JustYou tenant boundaries for Valo Corp.",
            },
            valid_report.step_receipts,
            tenant_id="tenant-a",
            identity="@captain",
        )
        self.assertFalse(dup_ver.independently_verified)
        self.assertTrue(
            any(c.startswith("duplicate_or_repetitive_deliverables:") for c in dup_ver.checks_failed)
        )

        # 5. Missing quantitative metrics in quantified_impact is rejected
        unquant_ver = verifier.verify(
            self._objective(objective_id="obj-unquant"),
            {
                "executive_summary": "Valo Corp revenue audit executive summary covering billing pipelines.",
                "action_plan": "Deploy automated reconciliation hooks across Valo Corp billing stages.",
                "quantified_impact": "Substantial financial improvement and much better operational efficiency.",
                "risk_mitigations": "Enforce strict rollback gates and JustYou identity checks.",
            },
            valid_report.step_receipts,
            tenant_id="tenant-a",
            identity="@captain",
        )
        self.assertFalse(unquant_ver.independently_verified)
        self.assertIn("missing_quantitative_metrics:quantified_impact", unquant_ver.checks_failed)

        # 6. External independent_critic rejection overrides self-reported step-4-critique pass
        rejecting_verifier = IndependentOutcomeVerifier(
            independent_critic=lambda _obj, _deliv, _ctx: {
                "verified": False,
                "reason": "cross_model_critic_found_flaw",
            }
        )
        critic_ver = rejecting_verifier.verify(
            self._objective(objective_id="obj-critic-reject"),
            valid_report.deliverables,
            valid_report.step_receipts,
            tenant_id="tenant-a",
            identity="@captain",
        )
        self.assertFalse(critic_ver.independently_verified)
        self.assertIn("independent_critic_rejected:cross_model_critic_found_flaw", critic_ver.checks_failed)

    def test_14_live_worker_adapter_normalization_and_step_level_quality_gates(self) -> None:
        from unlimited.economics import LIVE_HERMES_MODEL_CATALOG
        from unlimited.hermes_live_worker import (
            _flatten_to_prose,
            _sanitize_incidental_placeholder_words,
            normalize_catalog,
            resolve_provider_and_model,
        )

        # 1. normalize_catalog supports both tuple[ModelProfile, ...] and Mapping[str, ModelProfile]
        cat_from_tuple = normalize_catalog(LIVE_HERMES_MODEL_CATALOG)
        cat_from_dict = normalize_catalog(cat_from_tuple)
        self.assertEqual(set(cat_from_tuple.keys()), set(cat_from_dict.keys()))
        prov, mod = resolve_provider_and_model("alibaba/qwen3.8-max", LIVE_HERMES_MODEL_CATALOG)
        self.assertEqual((prov, mod), ("alibaba", "qwen3.8-max"))

        # 2. _flatten_to_prose and _sanitize_incidental_placeholder_words handle nested lists/dicts
        nested = ["Phase 1: Replace placeholder pricing with 1500 NOK floor", {"sla_ms": 250}]
        flat = _sanitize_incidental_placeholder_words(_flatten_to_prose(nested))
        self.assertIn("static default pricing", flat)
        self.assertNotIn("placeholder", flat.lower())

        # 3. Step-level _validate_step_output catches short or unquantified deliverables during build retries
        calls = []

        def unquantified_first_build_worker(step, model_id, attempt, ctx, hints):
            calls.append((step.step_id, attempt, hints))
            if step.step_id == "step-3-build" and attempt == 1:
                return StepWorkerResult(
                    status="ok",
                    output={
                        "executive_summary": "Valo Corp revenue operations audit summary with detailed scope and findings.",
                        "action_plan": "Deploy automated reconciliation across all Valo Corp billing pipelines.",
                        "quantified_impact": "Substantial financial improvement without any digits or units.",
                        "risk_mitigations": "Enforce strict JustYou identity and tenant isolation checks.",
                    },
                    input_tokens=800,
                    output_tokens=200,
                    latency_sec=2.0,
                )
            return default_deterministic_worker(step, model_id, attempt, ctx, hints)

        engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            worker=unquantified_first_build_worker,
        )
        report = engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-unquant-retry"),
        )
        self.assertEqual(report.status, "VERIFIED_COMPLETE")
        self.assertTrue(report.independently_verified)
        self.assertEqual(report.failures_detected, 1)
        self.assertEqual(report.autonomous_recoveries, 1)


    def test_15_live_critic_resolves_model_when_runtime_omits_model_key(self) -> None:
        """Hermes resolver may omit model; critic must use the requested model safely."""
        from unlimited import hermes_live_worker as live

        observed = {}
        class FakeAgent:
            def __init__(self, **kwargs):
                observed.update(kwargs)
            def run_conversation(self, *, user_message):
                return {
                    "completed": True,
                    "final_response": json.dumps({
                        "verified": True, "score": 91,
                        "reason": "Specific deliverables validated",
                        "findings": ["Scope and quantitative details reviewed"],
                    }),
                    "input_tokens": 40, "output_tokens": 25,
                    "estimated_cost_usd": 0.0004,
                }

        provider = types.ModuleType("hermes_cli.runtime_provider")
        provider.resolve_runtime_with_fallback = lambda *a, **kw: ({
            "provider": "alibaba",
            "api_key": "test-key",
            "base_url": "https://example.invalid",
            "api_mode": "chat_completions",
        }, None)
        config = types.ModuleType("hermes_cli.config")
        config.load_config = lambda: {}
        session = types.ModuleType("gateway.session_context")
        session.declare_stateless_channel = lambda: None
        runtime_agent = types.ModuleType("run_agent")
        runtime_agent.AIAgent = FakeAgent
        fake_modules = {
            "hermes_cli.runtime_provider": provider,
            "hermes_cli.config": config,
            "gateway.session_context": session,
            "run_agent": runtime_agent,
        }
        with patch.object(live, "ensure_hermes_runtime_loaded", return_value=ROOT), \
             patch.dict(sys.modules, fake_modules):
            critic = live.HermesLiveIndependentCritic()
            critic.CRITIC_PREFERENCE_ORDER = (("alibaba", "qwen3.8-max"),)
            verdict = critic(
                self._objective(),
                {"executive_summary": "Valo Corp security and revenue controls reviewed",
                 "action_plan": "Configure JustYou checks on the 3 customer workflows",
                 "quantified_impact": "Save 1500 NOK per month",
                 "risk_mitigations": "Preserve tenant boundaries"},
                {"step_receipts": [
                    SimpleNamespace(step_id="step-3-build", status="completed",
                                    cost=SimpleNamespace(provider_id="nous")),
                ]},
            )
        self.assertTrue(verdict["verified"])
        self.assertEqual(observed["model"], "qwen3.8-max")
        self.assertEqual(verdict["critic_provider_id"], "alibaba")

    def test_15_catalog_normalization_edge_cases_and_malformed_profiles(self) -> None:
        from unlimited.economics import LIVE_HERMES_MODEL_CATALOG, normalize_model_catalog
        from unlimited.hermes_live_worker import normalize_catalog

        # 1. Both tuple and mapping normalize identically
        t_norm = normalize_model_catalog(LIVE_HERMES_MODEL_CATALOG)
        m_norm = normalize_model_catalog(t_norm)
        self.assertEqual(set(t_norm), set(m_norm))

        # 2. Empty sequence or mapping raises ValueError
        for fn in (normalize_model_catalog, normalize_catalog):
            with self.assertRaisesRegex(ValueError, "MODEL_CATALOG_EMPTY|catalog must not be empty"):
                fn(())
            with self.assertRaisesRegex(ValueError, "MODEL_CATALOG_EMPTY|catalog must not be empty"):
                fn({})

        # 3. Duplicate model_id in sequence raises ValueError
        first_profile = LIVE_HERMES_MODEL_CATALOG[0]
        for fn in (normalize_model_catalog, normalize_catalog):
            with self.assertRaisesRegex(ValueError, "DUPLICATE_MODEL_ID|duplicate model_id"):
                fn((first_profile, first_profile))

        # 4. Mapping key mismatch raises ValueError
        for fn in (normalize_model_catalog, normalize_catalog):
            with self.assertRaisesRegex(ValueError, "CATALOG_KEY_MISMATCH|catalog key mismatch"):
                fn({"wrong-key": first_profile})

        # 5. Malformed non-ModelProfile entry raises TypeError
        for fn in (normalize_model_catalog, normalize_catalog):
            with self.assertRaisesRegex(
                TypeError,
                "MODEL_CATALOG_ENTRY_NOT_MODEL_PROFILE|catalog entries must be ModelProfile",
            ):
                fn([{"model_id": "bad-dict"}])  # type: ignore[arg-type]

    def test_16_verifier_signing_authority_key_custody_scope_binding_and_replay_rejection(self) -> None:
        from unlimited.autonomy import VerifierSigningAuthority, compute_objective_policy_digest

        authority_a = VerifierSigningAuthority(secret_key=b"key-custody-authority-A", key_id="auth-a")
        authority_b = VerifierSigningAuthority(secret_key=b"key-custody-authority-B", key_id="auth-b")
        verifier_a = IndependentOutcomeVerifier(authority=authority_a)
        verifier_b = IndependentOutcomeVerifier(authority=authority_b)

        obj = self._objective(objective_id="obj-authority-scope")
        engine_a = AutonomousMissionEngine(verify_identity=self.verify, verifier=verifier_a)
        report = engine_a.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
        )
        receipt = report.verification
        self.assertTrue(receipt.independently_verified)
        self.assertEqual(receipt.tenant_id, "tenant-a")
        self.assertEqual(receipt.company_id, "valocorp")
        self.assertEqual(receipt.authority_key_id, "auth-a")
        self.assertEqual(receipt.policy_digest, compute_objective_policy_digest(obj))

        # 1. Receipt signed by Authority A is rejected by Verifier with Authority B (separate key custody)
        self.assertFalse(
            verifier_b.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_tenant_id="tenant-a",
                expected_company_id="valocorp",
                expected_objective_id=obj.objective_id,
            )
        )

        # 2. Scope binding: cross-tenant, cross-company, cross-objective, or policy digest mismatch rejected
        self.assertFalse(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_tenant_id="tenant-b",
            )
        )
        self.assertFalse(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_company_id="other-corp",
            )
        )
        self.assertFalse(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_objective_id="other-objective-id",
            )
        )
        self.assertFalse(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_policy_digest="0" * 64,
            )
        )

        # 3. Replay protection: check_and_consume / reject_replay=True accepts first consumption and rejects replay
        self.assertTrue(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_tenant_id="tenant-a",
                expected_company_id="valocorp",
                expected_objective_id=obj.objective_id,
                reject_replay=True,
            )
        )
        self.assertFalse(
            verifier_a.verify_receipt_authenticity(
                receipt,
                deliverables=report.deliverables,
                expected_tenant_id="tenant-a",
                expected_company_id="valocorp",
                expected_objective_id=obj.objective_id,
                reject_replay=True,
            )
        )

    def test_17_autonomous_company_operating_system_six_governing_questions_and_readiness_matrix(self) -> None:
        from unlimited.company_os import (
            PRODUCT_READINESS_MATRIX,
            AutonomousCompanyOperatingSystem,
            CompanyCharter,
        )

        # Verify 15-area product readiness matrix completeness and honest statuses
        self.assertEqual(len(PRODUCT_READINESS_MATRIX), 15)
        area_names = {item["area"] for item in PRODUCT_READINESS_MATRIX}
        self.assertIn("Captain's Bridge", area_names)
        self.assertIn("Company Engine", area_names)
        self.assertIn("JustYou", area_names)
        self.assertIn("Verification / Governance", area_names)

        charter = CompanyCharter(
            company_id="valocorp",
            display_name="Valo Corp Autonomous Ops",
            mission_statement="Autonomous FinOps, Revenue Operations, and SLA Governance for Nordic B2B SaaS",
            strategic_domains=("finops", "revenue", "billing", "sla", "churn"),
            forbidden_domains=("cryptocurrency_trading", "unlicensed_legal"),
            max_autonomous_budget_minor=6_000,
            owner_approval_threshold_minor=5_000,
            min_roi_hurdle_ratio=0.30,
        )

        # Candidate 1: Violates forbidden domain in charter -> TERMINATE_CHARTER_VIOLATION
        cand_forbidden = self._objective(
            objective_id="cand-forbidden-crypto",
            title="Valo Corp Speculative Cryptocurrency_Trading Arbitrage",
            target_value_minor=9_500,
            policy=EconomicPolicy(budget_ceiling_minor=4_000),
        )
        # Candidate 2: Negative EV trap (5 NOK value) -> TERMINATE_NEGATIVE_EV
        cand_negative_ev = self._objective(
            objective_id="cand-neg-ev",
            title="Valo Corp Billing Footer Formatting Tweak",
            target_value_minor=5,
            policy=EconomicPolicy(budget_ceiling_minor=1_000),
        )
        # Candidate 3: Exceeds owner budget authority (budget 7500 > 5000 threshold) -> MODIFY_SCOPE_OR_ESCALATE_OWNER
        cand_over_budget = self._objective(
            objective_id="cand-over-budget",
            title="Valo Corp Enterprise Revenue & Billing Platform Rebuild",
            target_value_minor=12_000,
            policy=EconomicPolicy(budget_ceiling_minor=7_500),
        )
        # Candidate 4: Aligned, within autonomous budget authority, highest positive EV -> EXECUTE_AND_DELEGATE
        cand_optimal = self._objective(
            objective_id="cand-optimal-finops",
            title="Valo Corp Autonomous Revenue & Billing Leakage Recovery",
            target_value_minor=4_800,
            policy=EconomicPolicy(budget_ceiling_minor=4_500),
        )

        company_os = AutonomousCompanyOperatingSystem(
            database=self.db_path,
            verify_identity=self.verify,
        )
        cycle = company_os.run_operating_cycle(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            charter=charter,
            candidate_objectives=(cand_forbidden, cand_negative_ev, cand_over_budget, cand_optimal),
            auto_productize_services=True,
        )

        self.assertEqual(cycle.candidates_evaluated, 4)
        self.assertEqual(cycle.objectives_executed, 1)
        self.assertEqual(cycle.objectives_verified, 1)
        self.assertEqual(cycle.objectives_terminated_or_deferred, 3)
        self.assertEqual(len(cycle.mission_reports), 1)
        self.assertEqual(cycle.mission_reports[0].objective_id, "cand-optimal-finops")
        self.assertEqual(cycle.mission_reports[0].status, "VERIFIED_COMPLETE")
        self.assertTrue(cycle.mission_reports[0].independently_verified)
        self.assertEqual(cycle.human_interventions_required, 0)

        # Verify all 6 governing questions are explicitly answered across the portfolio
        by_id = {a.objective_id: a for a in cycle.six_question_assessments}
        self.assertFalse(by_id["cand-forbidden-crypto"].q1_right_task_aligned)
        self.assertEqual(
            by_id["cand-forbidden-crypto"].q4_recommended_disposition,
            "TERMINATE_CHARTER_VIOLATION",
        )
        self.assertFalse(by_id["cand-neg-ev"].q3_next_krone_justified)
        self.assertEqual(
            by_id["cand-neg-ev"].q4_recommended_disposition,
            "TERMINATE_NEGATIVE_EV",
        )
        self.assertEqual(
            by_id["cand-over-budget"].q4_recommended_disposition,
            "MODIFY_SCOPE_OR_ESCALATE_OWNER",
        )
        selected_q = by_id["cand-optimal-finops"]
        self.assertTrue(selected_q.q1_right_task_aligned)
        self.assertFalse(selected_q.q2_better_opportunity_exists)
        self.assertTrue(selected_q.q3_next_krone_justified)
        self.assertEqual(selected_q.q4_recommended_disposition, "EXECUTE_AND_DELEGATE")
        self.assertTrue(selected_q.q5_outcome_delivered_and_verified)
        self.assertIsNotNone(selected_q.q6_published_service_id)
        self.assertEqual(len(cycle.cycle_digest), 64)



    def test_18_live_wall_clock_budget_is_enforced(self) -> None:
        from unlimited.hermes_live_worker import _bounded_hermes_call
        import time
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "HERMES_WALL_CLOCK_TIMEOUT"):
            with _bounded_hermes_call(0.04):
                time.sleep(0.5)
        self.assertLess(time.monotonic() - started, 0.35)

    def test_19_live_wall_clock_rejects_unbounded_worker_thread(self) -> None:
        from unlimited.hermes_live_worker import _bounded_hermes_call
        from concurrent.futures import ThreadPoolExecutor
        def worker():
            with _bounded_hermes_call(0.1):
                return True
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaisesRegex(RuntimeError, "HERMES_WALL_CLOCK_BOUND_REQUIRES_MAIN_THREAD"):
                executor.submit(worker).result()

    def test_20_per_step_deadline_timeout_triggers_model_failover_and_durable_checkpoint_resume(self) -> None:
        import time

        attempted_models: list[tuple[str, int, str]] = []

        def slow_on_first_research_worker(step, model_id, attempt, ctx, hints):
            attempted_models.append((step.step_id, attempt, model_id))
            if step.step_id == "step-2-research" and attempt == 1:
                time.sleep(0.18)
                return StepWorkerResult(
                    status="ok",
                    output={"evidence_items": ["too slow"], "baseline_metrics": {"v": 1}},
                    latency_sec=25.0,
                )
            res = default_deterministic_worker(step, model_id, attempt, ctx, hints)
            res.latency_sec = 0.02
            return res

        obj = self._objective(
            objective_id="obj-deadline-failover",
            policy=EconomicPolicy(
                budget_ceiling_minor=5_000,
                sla_seconds=60.0,
                step_deadline_seconds=0.06,
                max_step_attempts=3,
            ),
        )

        # Phase A: Run first 2 steps (step-2-research times out on attempt 1, fails over to a different model on attempt 2),
        # then interrupt after 2 completed steps and persist durable checkpoint in SQLite.
        engine_part1 = AutonomousMissionEngine(
            verify_identity=self.verify,
            worker=slow_on_first_research_worker,
            ledger_db_path=self.db_path,
        )
        partial = engine_part1.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            interrupt_after_steps=2,
        )
        self.assertEqual(partial.status, "INTERRUPTED_CHECKPOINTED")
        self.assertEqual(partial.failures_detected, 1)
        self.assertEqual(partial.autonomous_recoveries, 1)
        research_receipts = [r for r in partial.step_receipts if r.step_id == "step-2-research"]
        self.assertEqual(len(research_receipts), 2)
        self.assertEqual(research_receipts[0].status, "runtime_error")
        self.assertIn("STEP_DEADLINE_EXCEEDED", research_receipts[0].error_reason or "")
        self.assertEqual(research_receipts[1].status, "completed")
        self.assertNotEqual(research_receipts[0].model_id, research_receipts[1].model_id)

        # Phase B: Simulate process restart by creating a new engine instance and resuming purely from SQLite ledger
        engine_restarted = AutonomousMissionEngine(
            verify_identity=self.verify,
            worker=slow_on_first_research_worker,
            ledger_db_path=self.db_path,
        )
        resumed = engine_restarted.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=obj,
            resume_from_ledger=True,
        )
        self.assertEqual(resumed.status, "VERIFIED_COMPLETE")
        self.assertTrue(resumed.independently_verified)
        self.assertEqual(resumed.autonomous_recoveries, 1)

    def test_21_adapter_maturity_tiers_and_per_tenant_jacket_capability_scopes(self) -> None:
        from unlimited.adapter_gate import AdapterDenied, TenantAdapterRegistry

        registry = TenantAdapterRegistry()
        summary = registry.summary()
        self.assertIn("justyou", summary["mandatory_adapters"])
        self.assertIn("justyou", summary["by_tier"]["CORE"])
        self.assertIn("customer-delivery-outbox", summary["by_tier"]["VERIFIED"])
        self.assertIn("live-email-connector", summary["by_tier"]["EXPERIMENTAL"])

        # 1. Mandatory JustYou is always active and release-eligible
        jy_auth = registry.authorize_tenant_capability(
            tenant_id="tenant-a",
            adapter_id="justyou",
            capability="identity.verify",
        )
        self.assertEqual(jy_auth["tier"], "CORE")
        self.assertTrue(jy_auth["mandatory_for_all_tenants"])
        self.assertTrue(jy_auth["release_eligible"])

        # 2. EXPERIMENTAL adapters cannot be enabled or invoked in release mode
        with self.assertRaisesRegex(AdapterDenied, "ADAPTER_NOT_RELEASE_ELIGIBLE:live-email-connector:EXPERIMENTAL"):
            registry.configure_tenant_jackets(
                "tenant-a",
                optional_grants={"live-email-connector": ("email.send.external",)},
            )
        with self.assertRaisesRegex(AdapterDenied, "ADAPTER_NOT_RELEASE_ELIGIBLE:live-payment-settlement:EXPERIMENTAL"):
            registry.authorize_tenant_capability(
                tenant_id="tenant-a",
                adapter_id="live-payment-settlement",
                capability="payment.charge",
            )

        # 3. Per-tenant capability scope isolation
        registry.configure_tenant_jackets(
            "tenant-a",
            optional_grants={"company-memory": ("memory.read",)},
        )
        self.assertEqual(
            registry.authorize_tenant_capability(
                tenant_id="tenant-a",
                adapter_id="company-memory",
                capability="memory.read",
            )["capability"],
            "memory.read",
        )
        with self.assertRaisesRegex(AdapterDenied, "TENANT_CAPABILITY_SCOPE_DENIED:tenant-a:company-memory:memory.write"):
            registry.authorize_tenant_capability(
                tenant_id="tenant-a",
                adapter_id="company-memory",
                capability="memory.write",
            )
        with self.assertRaisesRegex(AdapterDenied, "JACKET_NOT_ENABLED_FOR_TENANT:tenant-a:service-factory"):
            registry.authorize_tenant_capability(
                tenant_id="tenant-a",
                adapter_id="service-factory",
                capability="blueprint.register",
            )

    def test_22_explicit_completion_semantics_separate_self_report_from_verified_business_result(self) -> None:
        # 1. Self-reported artifact that fails independent verification is stage="produced_artifact", NOT verified
        rejecting_verifier = IndependentOutcomeVerifier(
            independent_critic=lambda _o, _d, _c: {"verified": False, "reason": "unverified_claims"}
        )
        unverified_engine = AutonomousMissionEngine(
            verify_identity=self.verify,
            verifier=rejecting_verifier,
        )
        unverified_rep = unverified_engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-semantics-unverified"),
        )
        self.assertEqual(unverified_rep.status, "STOPPED_UNVERIFIED_OUTCOME")
        self.assertTrue(unverified_rep.completion_semantics.produced_artifact)
        self.assertFalse(unverified_rep.completion_semantics.verified_artifact)
        self.assertFalse(unverified_rep.completion_semantics.authorized_external_effect)
        self.assertFalse(unverified_rep.completion_semantics.measured_business_result)
        self.assertEqual(unverified_rep.completion_semantics.stage, "produced_artifact")

        # 2. Independently verified positive-EV mission reaches measured_business_result while keeping external effect False until authorized
        verified_engine = AutonomousMissionEngine(verify_identity=self.verify)
        verified_rep = verified_engine.execute_objective(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            objective=self._objective(objective_id="obj-semantics-verified"),
        )
        self.assertEqual(verified_rep.status, "VERIFIED_COMPLETE")
        self.assertTrue(verified_rep.completion_semantics.produced_artifact)
        self.assertTrue(verified_rep.completion_semantics.verified_artifact)
        self.assertFalse(verified_rep.completion_semantics.authorized_external_effect)
        self.assertTrue(verified_rep.completion_semantics.measured_business_result)
        self.assertEqual(verified_rep.completion_semantics.stage, "measured_business_result")

    def test_23_authorized_customer_delivery_channel_and_complete_vertical_slice(self) -> None:
        from unlimited.adapter_gate import AdapterDenied
        from unlimited.a2ui_adapter import mission_surface, readiness_surface
        from unlimited.company_os import (
            AuthorizedCustomerDeliveryChannel,
            AutonomousCompanyOperatingSystem,
            CompanyCharter,
        )

        charter = CompanyCharter(
            company_id="valocorp",
            display_name="Valo Corp Autonomous Ops",
            mission_statement="Autonomous FinOps, Revenue Operations, and SLA Governance for Nordic B2B SaaS",
            strategic_domains=("finops", "revenue", "billing", "sla", "security"),
            forbidden_domains=("cryptocurrency_trading", "unlicensed_legal"),
            max_autonomous_budget_minor=6_000,
            owner_approval_threshold_minor=5_000,
            min_roi_hurdle_ratio=0.30,
        )
        cand_optimal = self._objective(
            objective_id="cand-vertical-slice",
            title="Valo Corp Autonomous Revenue & SLA Assurance Delivery",
            target_value_minor=4_800,
            policy=EconomicPolicy(budget_ceiling_minor=4_500),
        )

        company_os = AutonomousCompanyOperatingSystem(
            database=self.db_path,
            verify_identity=self.verify,
        )
        cycle = company_os.run_operating_cycle(
            provider_id="owner",
            tenant_id="tenant-a",
            identity="@captain",
            charter=charter,
            candidate_objectives=(cand_optimal,),
            auto_productize_services=True,
            deliver_to_customer_id="cust-nordic-bank-01",
            authorize_external_delivery=True,
        )

        # Verify full vertical slice: Charter -> Triage -> Crew -> Verification -> CAVO -> Memory -> Blueprint -> Customer Delivery -> Captain's Bridge
        self.assertEqual(cycle.objectives_verified, 1)
        self.assertEqual(len(cycle.harvested_memory_ids), 1)
        self.assertEqual(len(cycle.minted_blueprints), 1)
        self.assertEqual(len(cycle.customer_deliveries), 1)
        dlv = cycle.customer_deliveries[0]
        self.assertEqual(dlv.customer_id, "cust-nordic-bank-01")
        self.assertTrue(dlv.external_effect_authorized)
        self.assertEqual(dlv.verifier_seal, cycle.mission_reports[0].verification.verifier_seal)

        rep = cycle.mission_reports[0]
        self.assertTrue(rep.completion_semantics.produced_artifact)
        self.assertTrue(rep.completion_semantics.verified_artifact)
        self.assertFalse(rep.completion_semantics.authorized_external_effect)
        self.assertTrue(rep.completion_semantics.measured_business_result)
        self.assertIsNone(rep.completion_semantics.external_effect_receipt_digest)
        self.assertIn("external delivery not confirmed", rep.completion_semantics.summary)

        # Idempotent replay to the same customer returns identical delivery receipt without error
        dlv_replay = company_os.delivery_channel.deliver_verified_service(
            provider_id="owner",
            tenant_id="tenant-a",
            company_id="valocorp",
            identity="@captain",
            customer_id="cust-nordic-bank-01",
            service_id=dlv.service_id,
            report=rep,
            authorize_external_effect=True,
        )
        self.assertEqual(dlv_replay.delivery_id, dlv.delivery_id)
        self.assertEqual(
            len(company_os.delivery_channel.list_deliveries("owner", "tenant-a", "valocorp", "@captain")),
            1,
        )

        # Negative tests: unauthorized external effect or unapproved channel is blocked fail-closed
        with self.assertRaisesRegex(PermissionError, "EXTERNAL_CUSTOMER_EFFECT_NOT_AUTHORIZED"):
            company_os.delivery_channel.deliver_verified_service(
                provider_id="owner",
                tenant_id="tenant-a",
                company_id="valocorp",
                identity="@captain",
                customer_id="cust-2",
                service_id=dlv.service_id,
                report=rep,
                authorize_external_effect=False,
            )
        with self.assertRaisesRegex(AdapterDenied, "UNAPPROVED_EXTERNAL_CHANNEL:smtp_raw"):
            company_os.delivery_channel.deliver_verified_service(
                provider_id="owner",
                tenant_id="tenant-a",
                company_id="valocorp",
                identity="@captain",
                customer_id="cust-2",
                service_id=dlv.service_id,
                report=rep,
                authorize_external_effect=True,
                channel="smtp_raw",
            )

        # Captain's Bridge A2UI surfaces reflect the verified mission and readiness state
        m_surf = mission_surface(
            company_os.store, "owner", "tenant-a", "valocorp", "@captain", surface_id="vertical_missions"
        )
        r_surf = readiness_surface(
            company_os.store, "owner", "tenant-a", "@captain", surface_id="vertical_readiness"
        )
        self.assertIn("cand-vertical-slice", json.dumps(m_surf))
        self.assertIn("VERIFIED_CORE", json.dumps(r_surf))


if __name__ == "__main__":
    unittest.main()
