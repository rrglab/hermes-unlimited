"""Hermes Unlimited — AI-Native Company Operating System (Company OS).

Unifies the six governing questions of an autonomous company into a single,
JustYou-enforced operating loop:
1. Is this the right task to execute? (Goal Fidelity & Charter Alignment)
2. Is there a better business opportunity? (Portfolio Opportunity Allocation)
3. Is the next krone worth spending? (CAVO — Cost per Autonomous Verified Outcome & Marginal EV)
4. Should the work be executed, delegated, modified, or terminated? (Action Disposition)
5. Is the outcome actually delivered and independently verified? (Independent Verifier Authority)
6. What should the company learn, improve, or sell next? (Company Memory & Service Factory)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from .adapter_gate import AdapterDenied, TenantAdapterRegistry
from .autonomy import (
    AutonomousMissionEngine,
    BusinessObjective,
    CompletionSemanticsReport,
    IndependentOutcomeVerifier,
    MissionExecutionReport,
    ObjectiveDecomposer,
    StepWorkerCallable,
    WORD_TOKEN_PATTERN,
    default_deterministic_worker,
)
from .economics import (
    EconomicIntelligenceEngine,
    EconomicPolicy,
    ModelRouter,
    RoutingStrategy,
)
from .memory_factory import CompanyMemoryStore, ServiceBlueprint, ServiceFactory
from .runtime import IDENT, ProviderStore, UnverifiedIdentity

CharterVerdict = Literal[
    "ALIGNED",
    "REJECT_FORBIDDEN_BY_CHARTER",
    "REJECT_OFF_STRATEGY",
    "ESCALATE_OWNER_AUTHORITY",
]

ActionDisposition = Literal[
    "EXECUTE_AND_DELEGATE",
    "DEFER_FOR_HIGHER_EV_OPPORTUNITY",
    "MODIFY_SCOPE_OR_ESCALATE_OWNER",
    "TERMINATE_NEGATIVE_EV",
    "TERMINATE_CHARTER_VIOLATION",
]


@dataclass(frozen=True)
class CompanyCharter:
    """Owner-defined direction, economic boundaries, and decision authority for a company."""

    company_id: str
    display_name: str
    mission_statement: str
    strategic_domains: tuple[str, ...] = (
        "security",
        "audit",
        "revenue",
        "pricing",
        "operations",
        "automation",
        "sla",
        "incident",
        "support",
        "analytics",
        "compliance",
        "expansion",
    )
    forbidden_domains: tuple[str, ...] = (
        "unauthorized_financial_trading",
        "credential_harvesting",
        "unlicensed_legal_representation",
        "speculative_crypto_gambling",
        "bypass_security_controls",
    )
    min_roi_hurdle_ratio: float = 0.50
    max_autonomous_budget_minor: int = 10_000
    owner_approval_threshold_minor: int = 8_000
    currency: str = "NOK"

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, str) or not IDENT.fullmatch(self.company_id):
            raise ValueError("CHARTER_COMPANY_ID_INVALID")
        if not self.mission_statement or not self.mission_statement.strip():
            raise ValueError("CHARTER_MISSION_REQUIRED")
        if self.owner_approval_threshold_minor < 0 or self.max_autonomous_budget_minor <= 0:
            raise ValueError("CHARTER_BUDGET_LIMITS_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalFidelityAssessment:
    """Result of evaluating a candidate objective against the owner's CompanyCharter."""

    objective_id: str
    company_id: str
    aligned: bool
    verdict: CharterVerdict
    alignment_score: float
    matched_domains: tuple[str, ...]
    forbidden_hits: tuple[str, ...]
    requires_owner_approval: bool
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SixQuestionAssessment:
    """Structured answer to the 6 governing questions of Hermes Unlimited."""

    objective_id: str
    title: str
    # 1. Er dette riktig oppgave å utføre?
    q1_right_task_aligned: bool
    q1_charter_verdict: CharterVerdict
    q1_rationale: str
    # 2. Finnes det en bedre forretningsmulighet?
    q2_better_opportunity_exists: bool
    q2_portfolio_rank: int
    q2_better_opportunity_id: str | None
    q2_expected_net_value_minor: float
    q2_top_alternative_net_value_minor: float
    # 3. Er neste krone verdt å bruke? (CAVO & Marginal EV)
    q3_next_krone_justified: bool
    q3_expected_cavo_minor: float
    q3_expected_verified_value_minor: float
    q3_expected_roi_ratio: float
    # 4. Bør arbeidet utføres, delegeres, endres eller avsluttes?
    q4_recommended_disposition: ActionDisposition
    q4_assigned_crew_roles: tuple[str, ...]
    # 5. Er resultatet faktisk levert og verifisert?
    q5_outcome_delivered_and_verified: bool
    q5_verification_evidence_digest: str | None
    q5_verifier_seal: str | None
    # 6. Hva bør virksomheten lære, forbedre eller selge videre?
    q6_memory_entry_id: str | None
    q6_service_blueprint_id: str | None
    q6_published_service_id: str | None
    q6_recommended_price_minor: int | None
    q6_next_improvement_recommendation: str
    q6_customer_delivery_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CustomerDeliveryReceipt:
    """Signed transactional customer communication and service delivery receipt."""

    delivery_id: str
    provider_id: str
    tenant_id: str
    company_id: str
    objective_id: str
    service_id: str
    customer_id: str
    channel: str
    authorized_by_identity: str
    external_effect_authorized: bool
    deliverable_digest: str
    verifier_seal: str
    message_subject: str
    message_body: str
    receipt_digest: str
    created_at: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuthorizedCustomerDeliveryChannel:
    """Transactional customer communication and service delivery channel with strict authorization.

    Enforces:
    1. Mandatory JustYou identity & tenant boundary verification.
    2. `TenantAdapterRegistry` capability check (`customer-delivery-outbox` -> `customer.communicate`).
    3. Explicit external-effect authorization (`authorize_external_effect=True`).
    4. Cryptographic `IndependentOutcomeVerifier` seal verification + anti-replay check.
    5. Durable SQLite transactional outbox idempotency (prevents duplicate customer dispatches).
    Outbox creation is NOT proof of external dispatch, delivery, or settlement.
    No real external email, payment, or customer receipt is performed here.
    """

    def __init__(
        self,
        database: str | Path,
        verify_identity: Callable[[str, str, str], bool],
        *,
        verifier: IndependentOutcomeVerifier,
        adapter_registry: TenantAdapterRegistry | None = None,
    ) -> None:
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou identity verifier required")
        self.database = str(database)
        self.verify_identity = verify_identity
        self.verifier = verifier
        self.adapter_registry = adapter_registry or TenantAdapterRegistry()
        self._init_db()

    def _init_db(self) -> None:
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_delivery_outbox (
                    delivery_key TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    objective_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                )
                """
            )

    def deliver_verified_service(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        company_id: str,
        identity: str,
        customer_id: str,
        service_id: str,
        report: MissionExecutionReport,
        authorize_external_effect: bool,
        channel: str = "transactional_outbox",
    ) -> CustomerDeliveryReceipt:
        if not provider_id or not tenant_id or not company_id or not identity or not customer_id:
            raise UnverifiedIdentity("CUSTOMER_DELIVERY_SCOPE_REQUIRED")
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")
        if authorize_external_effect is not True:
            raise PermissionError("EXTERNAL_CUSTOMER_EFFECT_NOT_AUTHORIZED")
        if channel not in ("transactional_outbox", "captains_bridge_portal"):
            raise AdapterDenied(f"UNAPPROVED_EXTERNAL_CHANNEL:{channel}")

        # Verify Jacket maturity & per-tenant capability scopes
        self.adapter_registry.authorize_tenant_capability(
            tenant_id=tenant_id,
            adapter_id="justyou",
            capability="identity.verify",
        )
        self.adapter_registry.authorize_tenant_capability(
            tenant_id=tenant_id,
            adapter_id="customer-delivery-outbox",
            capability="customer.communicate",
        )
        self.adapter_registry.authorize_tenant_capability(
            tenant_id=tenant_id,
            adapter_id="customer-delivery-outbox",
            capability="delivery.receipt.issue",
        )

        if report.tenant_id != tenant_id or report.company_id != company_id:
            raise PermissionError("REPORT_SCOPE_MISMATCH")
        if not report.independently_verified:
            raise PermissionError("UNVERIFIED_OUTCOME_CANNOT_BE_DELIVERED_TO_CUSTOMER")

        # Idempotency check before consuming anti-replay seal
        delivery_key = f"{provider_id}:{tenant_id}:{company_id}:{report.objective_id}:{customer_id}"
        with sqlite3.connect(self.database, timeout=10) as db:
            existing = db.execute(
                "SELECT receipt_json FROM customer_delivery_outbox WHERE delivery_key=?",
                (delivery_key,),
            ).fetchone()
        if existing:
            return CustomerDeliveryReceipt(**json.loads(existing[0]))

        if not self.verifier.verify_receipt_authenticity(
            report.verification,
            deliverables=report.deliverables,
            expected_tenant_id=tenant_id,
            expected_company_id=company_id,
            expected_objective_id=report.objective_id,
            reject_replay=True,
            consumer_scope=f"customer_delivery:{tenant_id}:{company_id}:{customer_id}",
        ):
            raise PermissionError("FORGED_OR_REPLAYED_VERIFICATION_RECEIPT")

        exec_summary = str(
            report.deliverables.get("executive_summary")
            or next(iter(report.deliverables.values()), "Verified service package")
        )
        subject = f"[{company_id}] Verified Service Delivery: {service_id} ({report.objective_id})"
        body = (
            f"Customer: {customer_id}\n"
            f"Service: {service_id}\n"
            f"Objective: {report.objective_id}\n"
            f"Verification Seal: {report.verification.verifier_seal}\n"
            f"Summary: {exec_summary}"
        )
        created_at = round(time.time(), 3)
        delivery_id = "dlv-" + hashlib.sha256(delivery_key.encode("utf-8")).hexdigest()[:16]
        digest_payload = {
            "delivery_id": delivery_id,
            "provider_id": provider_id,
            "tenant_id": tenant_id,
            "company_id": company_id,
            "objective_id": report.objective_id,
            "service_id": service_id,
            "customer_id": customer_id,
            "channel": channel,
            "authorized_by_identity": identity,
            "deliverable_digest": report.verification.deliverable_digest,
            "verifier_seal": report.verification.verifier_seal,
        }
        receipt_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        receipt = CustomerDeliveryReceipt(
            delivery_id=delivery_id,
            provider_id=provider_id,
            tenant_id=tenant_id,
            company_id=company_id,
            objective_id=report.objective_id,
            service_id=service_id,
            customer_id=customer_id,
            channel=channel,
            authorized_by_identity=identity,
            external_effect_authorized=True,
            deliverable_digest=report.verification.deliverable_digest,
            verifier_seal=report.verification.verifier_seal,
            message_subject=subject,
            message_body=body,
            receipt_digest=receipt_digest,
            created_at=created_at,
        )
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute(
                """
                INSERT INTO customer_delivery_outbox(
                    delivery_key, delivery_id, provider_id, tenant_id, company_id,
                    objective_id, customer_id, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_key,
                    delivery_id,
                    provider_id,
                    tenant_id,
                    company_id,
                    report.objective_id,
                    customer_id,
                    json.dumps(receipt.as_dict(), sort_keys=True),
                ),
            )
        return receipt

    def dispatch_with_customer_connection(
        self, *, provider_id: str, tenant_id: str, company_id: str,
        identity: str, delivery_id: str, recipient: str, connection_id: str,
        connection_registry, secret_resolver,
        approve_effect: Callable[[str, str, str], bool],
        authorize_external_effect: bool = False, smtp_factory=None,
    ):
        """Resolve tenant-owned SMTP credentials only after scoped approval."""
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")
        if authorize_external_effect is not True or approve_effect(tenant_id, identity, delivery_id) is not True:
            raise PermissionError("EXTERNAL_CUSTOMER_EFFECT_NOT_AUTHORIZED")
        connection = connection_registry.get(
            tenant_id=tenant_id, identity=identity, connection_id=connection_id)
        if connection.provider != "smtp":
            raise PermissionError("EMAIL_REQUIRES_SMTP_CUSTOMER_CONNECTION")
        adapter = connection_registry.resolve_adapter(
            tenant_id=tenant_id, identity=identity, connection_id=connection_id,
            secret_resolver=secret_resolver, smtp_factory=smtp_factory)
        return self.dispatch_queued_email(
            provider_id=provider_id, tenant_id=tenant_id, company_id=company_id,
            identity=identity, delivery_id=delivery_id, recipient=recipient,
            email_adapter=adapter, approve_effect=approve_effect,
            authorize_external_effect=authorize_external_effect)

    def dispatch_queued_email(
        self, *, provider_id: str, tenant_id: str, company_id: str,
        identity: str, delivery_id: str, recipient: str, email_adapter,
        approve_effect: Callable[[str, str, str], bool],
        authorize_external_effect: bool = False,
    ):
        """Dispatch one approved outbox record; persist provider acceptance separately.

        An uncertain transport result is not retried automatically, to avoid
        duplicate customer messages. SMTP acceptance is never delivery proof.
        """
        from .external_effects import ExternalEffectReceipt
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")
        if authorize_external_effect is not True:
            raise PermissionError("EXTERNAL_CUSTOMER_EFFECT_NOT_AUTHORIZED")
        if approve_effect(tenant_id, identity, delivery_id) is not True:
            raise PermissionError("EXTERNAL_EFFECT_APPROVAL_REQUIRED")
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS customer_external_dispatch (
                delivery_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                receipt_json TEXT
            )""")
            row = db.execute("""SELECT receipt_json FROM customer_delivery_outbox
                WHERE delivery_id=? AND provider_id=? AND tenant_id=? AND company_id=?""",
                (delivery_id, provider_id, tenant_id, company_id)).fetchone()
            if not row:
                raise PermissionError("OUTBOX_DELIVERY_NOT_FOUND_IN_SCOPE")
            queued = CustomerDeliveryReceipt(**json.loads(row[0]))
            existing = db.execute("SELECT state, receipt_json FROM customer_external_dispatch WHERE delivery_id=?",
                                  (delivery_id,)).fetchone()
            if existing:
                if existing[0] == "provider_accepted" and existing[1]:
                    return ExternalEffectReceipt(**json.loads(existing[1]))
                raise RuntimeError("DISPATCH_ALREADY_CLAIMED_MANUAL_RECONCILIATION_REQUIRED")
            # Claim before network IO: timeout/crash cannot silently double-send.
            db.execute("INSERT INTO customer_external_dispatch(delivery_id,state) VALUES (?,?)",
                       (delivery_id, "uncertain"))
        receipt = email_adapter.send(
            tenant_id=tenant_id, identity=identity, effect_id=delivery_id,
            recipient=recipient, subject=queued.message_subject, body=queued.message_body,
            verify_identity=lambda tenant, actor: self.verify_identity(provider_id, tenant, actor),
            approve_effect=approve_effect, authorized=authorize_external_effect,
        )
        if receipt.kind != "email" or receipt.effect_id != delivery_id or receipt.tenant_id != tenant_id:
            raise RuntimeError("EXTERNAL_RECEIPT_SCOPE_MISMATCH")
        if receipt.state != "provider_accepted":
            raise RuntimeError("EXTERNAL_PROVIDER_DID_NOT_ACCEPT")
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("UPDATE customer_external_dispatch SET state=?, receipt_json=? WHERE delivery_id=?",
                       (receipt.state, json.dumps(receipt.as_dict(), sort_keys=True), delivery_id))
        return receipt

    def list_deliveries(
        self,
        provider_id: str,
        tenant_id: str,
        company_id: str,
        identity: str,
    ) -> list[CustomerDeliveryReceipt]:
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")
        with sqlite3.connect(self.database, timeout=10) as db:
            rows = db.execute(
                """
                SELECT receipt_json FROM customer_delivery_outbox
                WHERE provider_id=? AND tenant_id=? AND company_id=?
                ORDER BY rowid ASC
                """,
                (provider_id, tenant_id, company_id),
            ).fetchall()
        return [CustomerDeliveryReceipt(**json.loads(r[0])) for r in rows]


@dataclass(frozen=True)
class CompanyOperatingCycleReport:
    """End-to-end report of an autonomous company operating cycle."""

    provider_id: str
    tenant_id: str
    company_id: str
    identity: str
    charter: CompanyCharter
    candidates_evaluated: int
    objectives_executed: int
    objectives_verified: int
    objectives_terminated_or_deferred: int
    total_measured_cost_minor: float
    total_verified_value_minor: int
    total_net_economic_value_minor: float
    portfolio_cavo_minor: float
    human_interventions_required: int
    six_question_assessments: tuple[SixQuestionAssessment, ...]
    mission_reports: tuple[MissionExecutionReport, ...]
    harvested_memory_ids: tuple[str, ...]
    minted_blueprints: tuple[ServiceBlueprint, ...]
    cycle_digest: str
    customer_deliveries: tuple[CustomerDeliveryReceipt, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoalFidelityEvaluator:
    """Evaluates whether a candidate objective aligns with the owner's CompanyCharter."""

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {m.group(0).lower() for m in WORD_TOKEN_PATTERN.finditer(text)}

    @classmethod
    def evaluate(
        cls,
        charter: CompanyCharter,
        objective: BusinessObjective,
    ) -> GoalFidelityAssessment:
        if objective.company_id != charter.company_id:
            raise PermissionError("OBJECTIVE_COMPANY_MISMATCH")

        combined_raw = f"{objective.objective_id} {objective.title} {objective.description}".lower()
        combined_tokens = cls._tokens(combined_raw)

        # 1. Check forbidden domains / actions
        forbidden_hits: list[str] = []
        for f_dom in charter.forbidden_domains:
            f_clean = f_dom.lower().replace("_", " ")
            f_parts = [p for p in f_clean.split() if len(p) >= 4]
            if f_dom.lower() in combined_raw or f_clean in combined_raw:
                forbidden_hits.append(f_dom)
            elif len(f_parts) >= 2 and all(p in combined_raw for p in f_parts):
                forbidden_hits.append(f_dom)

        if forbidden_hits:
            return GoalFidelityAssessment(
                objective_id=objective.objective_id,
                company_id=objective.company_id,
                aligned=False,
                verdict="REJECT_FORBIDDEN_BY_CHARTER",
                alignment_score=0.0,
                matched_domains=(),
                forbidden_hits=tuple(forbidden_hits),
                requires_owner_approval=False,
                rationale=(
                    f"Objective '{objective.objective_id}' violates forbidden charter boundary: "
                    f"{', '.join(forbidden_hits)}."
                ),
            )

        # 2. Check alignment with strategic domains and mission statement
        matched_domains = [
            d for d in charter.strategic_domains if d.lower() in combined_raw or d.lower() in combined_tokens
        ]
        mission_tokens = {
            t for t in cls._tokens(charter.mission_statement) if len(t) >= 4
        }
        mission_overlap = combined_tokens & mission_tokens
        score = min(1.0, round(0.35 * len(matched_domains) + 0.15 * len(mission_overlap), 3))

        if not matched_domains and not mission_overlap:
            return GoalFidelityAssessment(
                objective_id=objective.objective_id,
                company_id=objective.company_id,
                aligned=False,
                verdict="REJECT_OFF_STRATEGY",
                alignment_score=0.0,
                matched_domains=(),
                forbidden_hits=(),
                requires_owner_approval=False,
                rationale=(
                    f"Objective '{objective.objective_id}' has zero overlap with charter strategic domains "
                    f"({', '.join(charter.strategic_domains[:5])})."
                ),
            )

        # 3. Check whether budget or target value exceeds autonomous delegation authority
        if (
            objective.policy.budget_ceiling_minor > charter.owner_approval_threshold_minor
            or objective.policy.budget_ceiling_minor > charter.max_autonomous_budget_minor
        ):
            return GoalFidelityAssessment(
                objective_id=objective.objective_id,
                company_id=objective.company_id,
                aligned=True,
                verdict="ESCALATE_OWNER_AUTHORITY",
                alignment_score=max(0.5, score),
                matched_domains=tuple(matched_domains),
                forbidden_hits=(),
                requires_owner_approval=True,
                rationale=(
                    f"Objective budget ceiling ({objective.policy.budget_ceiling_minor} {objective.currency}) "
                    f"exceeds autonomous owner approval threshold ({charter.owner_approval_threshold_minor} {charter.currency})."
                ),
            )

        return GoalFidelityAssessment(
            objective_id=objective.objective_id,
            company_id=objective.company_id,
            aligned=True,
            verdict="ALIGNED",
            alignment_score=max(0.5, score),
            matched_domains=tuple(matched_domains),
            forbidden_hits=(),
            requires_owner_approval=False,
            rationale=(
                f"Aligned with charter domains ({', '.join(matched_domains or ['mission_core'])}, "
                f"score={max(0.5, score):.2f})."
            ),
        )


class CAVOOpportunityAllocator:
    """Evaluates and ranks candidate business objectives by CAVO and expected net value."""

    def __init__(
        self,
        economic_engine: EconomicIntelligenceEngine,
        routing_strategy: RoutingStrategy = "outcome_driven",
    ) -> None:
        self.economic_engine = economic_engine
        self.routing_strategy: RoutingStrategy = routing_strategy

    def estimate_objective_cavo(self, objective: BusinessObjective) -> dict[str, Any]:
        """Estimate full DAG CAVO (Cost per Autonomous Verified Outcome) and expected net value."""
        self.economic_engine.policy = objective.policy
        router = ModelRouter(self.economic_engine, strategy=self.routing_strategy)
        steps = ObjectiveDecomposer.decompose(objective)

        cumulative_direct = 0.0
        cumulative_total_cost = 0.0
        cumulative_elapsed = 0.0
        joint_success_prob = 1.0
        step_plans: list[dict[str, Any]] = []
        crew_roles: list[str] = []
        all_steps_justified = True

        for step in steps:
            if step.role not in crew_roles:
                crew_roles.append(step.role)
            marginal_val = float(objective.target_value_minor) * step.marginal_value_share
            model_id, dec = router.select_model(
                task_kind=step.task_kind,
                marginal_value_minor=marginal_val,
                spent_cost_minor=cumulative_direct,
                elapsed_seconds=cumulative_elapsed,
                attempt=1,
                complexity=step.complexity,
                estimated_input_tokens=step.estimated_input_tokens,
                estimated_output_tokens=step.estimated_output_tokens,
            )
            if not dec.economically_justified or model_id is None:
                all_steps_justified = False
            cumulative_direct += dec.cost_breakdown.direct_cost_minor
            cumulative_total_cost += dec.cost_breakdown.total_economic_cost_minor
            cumulative_elapsed += dec.cost_breakdown.elapsed_seconds
            joint_success_prob *= dec.success_probability
            step_plans.append(
                {
                    "step_id": step.step_id,
                    "role": step.role,
                    "selected_model_id": model_id,
                    "step_cost_minor": dec.cost_breakdown.total_economic_cost_minor,
                    "success_probability": dec.success_probability,
                    "economically_justified": dec.economically_justified,
                }
            )

        expected_verified_value = round(joint_success_prob * float(objective.target_value_minor), 4)
        # CAVO is the expected total economic cost per verified outcome (cost / P(verified_outcome))
        expected_cavo = round(
            cumulative_total_cost / max(0.05, joint_success_prob),
            4,
        )
        expected_net_value = round(expected_verified_value - cumulative_total_cost, 4)
        expected_roi = round(
            (expected_net_value / cumulative_total_cost) if cumulative_total_cost > 0 else 0.0,
            4,
        )
        return {
            "objective_id": objective.objective_id,
            "all_steps_justified": all_steps_justified and expected_net_value > 0,
            "joint_success_probability": round(joint_success_prob, 4),
            "expected_total_cost_minor": round(cumulative_total_cost, 4),
            "expected_cavo_minor": expected_cavo,
            "expected_verified_value_minor": expected_verified_value,
            "expected_net_value_minor": expected_net_value,
            "expected_roi_ratio": expected_roi,
            "crew_roles": tuple(crew_roles),
            "step_plans": step_plans,
        }


class AutonomousCompanyOperatingSystem:
    """Runs the full AI-Native Company operating loop under JustYou governance."""

    def __init__(
        self,
        *,
        database: str | Path,
        verify_identity: Callable[[str, str, str], bool],
        economic_engine: EconomicIntelligenceEngine | None = None,
        routing_strategy: RoutingStrategy = "outcome_driven",
        worker: StepWorkerCallable = default_deterministic_worker,
        verifier: IndependentOutcomeVerifier | None = None,
        adapter_registry: TenantAdapterRegistry | None = None,
    ) -> None:
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou identity verifier required")
        self.database = str(database)
        self.verify_identity = verify_identity
        self.economic_engine = economic_engine or EconomicIntelligenceEngine()
        self.routing_strategy: RoutingStrategy = routing_strategy
        self.worker = worker
        self.verifier = verifier or IndependentOutcomeVerifier()
        self.adapter_registry = adapter_registry or TenantAdapterRegistry()
        self.store = ProviderStore(self.database, self.verify_identity)
        self.memory = CompanyMemoryStore(self.database, self.verify_identity)
        self.factory = ServiceFactory(self.database, self.verify_identity)
        self.delivery_channel = AuthorizedCustomerDeliveryChannel(
            self.database,
            self.verify_identity,
            verifier=self.verifier,
            adapter_registry=self.adapter_registry,
        )
        self.mission_engine = AutonomousMissionEngine(
            verify_identity=self.verify_identity,
            economic_engine=self.economic_engine,
            routing_strategy=self.routing_strategy,
            worker=self.worker,
            verifier=self.verifier,
            ledger_db_path=self.database,
        )

    def run_operating_cycle(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        identity: str,
        charter: CompanyCharter,
        candidate_objectives: Sequence[BusinessObjective],
        max_objectives_to_execute: int = 1,
        auto_productize_services: bool = True,
        deliver_to_customer_id: str | None = None,
        authorize_external_delivery: bool = False,
    ) -> CompanyOperatingCycleReport:
        """Evaluate candidate opportunities, execute top positive-EV work, harvest memory, and mint services."""
        if not provider_id or not tenant_id or not identity:
            raise UnverifiedIdentity("JUSTYOU_SCOPE_REQUIRED")
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")
        if not candidate_objectives:
            raise ValueError("CANDIDATE_OBJECTIVES_EMPTY")

        # Configure default release-eligible Jackets for this tenant if not already configured
        if tenant_id not in self.adapter_registry._tenant_grants:
            self.adapter_registry.configure_tenant_jackets(
                tenant_id,
                optional_grants={
                    "company-memory": ("memory.read", "memory.write", "memory.recall"),
                    "service-factory": ("blueprint.register", "service.deliver", "sla.verify"),
                    "customer-delivery-outbox": ("customer.communicate", "delivery.receipt.issue"),
                    "a2ui-captains-bridge": ("bridge.read", "bridge.action.propose"),
                },
            )
        self.adapter_registry.authorize_tenant_capability(
            tenant_id=tenant_id,
            adapter_id="justyou",
            capability="identity.verify",
        )

        # Ensure company exists in tenant registry
        existing_companies = {
            c["company"] for c in self.store.list_companies(provider_id, tenant_id, identity)
        }
        if charter.company_id not in existing_companies:
            self.store.create_company(
                provider_id,
                tenant_id,
                charter.company_id,
                charter.display_name,
                identity,
            )

        allocator = CAVOOpportunityAllocator(
            self.economic_engine,
            routing_strategy=self.routing_strategy,
        )

        # Stage 1: Evaluate all candidates on Goal Fidelity + CAVO Economics
        evaluated: list[dict[str, Any]] = []
        for obj in candidate_objectives:
            fidelity = GoalFidelityEvaluator.evaluate(charter, obj)
            cavo_est = allocator.estimate_objective_cavo(obj)
            eligible = (
                fidelity.verdict == "ALIGNED"
                and cavo_est["all_steps_justified"]
                and cavo_est["expected_roi_ratio"] >= charter.min_roi_hurdle_ratio
            )
            evaluated.append(
                {
                    "objective": obj,
                    "fidelity": fidelity,
                    "cavo": cavo_est,
                    "eligible": eligible,
                    "rank_score": (
                        cavo_est["expected_net_value_minor"] if eligible else -1e9
                    ),
                }
            )

        # Rank eligible candidates by expected net value descending
        ranked_order = sorted(
            evaluated,
            key=lambda item: (item["eligible"], item["cavo"]["expected_net_value_minor"]),
            reverse=True,
        )
        rank_by_id = {
            item["objective"].objective_id: idx + 1 for idx, item in enumerate(ranked_order)
        }
        top_eligible = next((item for item in ranked_order if item["eligible"]), None)
        top_net_ev = (
            float(top_eligible["cavo"]["expected_net_value_minor"])
            if top_eligible is not None
            else 0.0
        )

        selected_ids = {
            item["objective"].objective_id
            for item in ranked_order
            if item["eligible"]
        }
        # Keep only top `max_objectives_to_execute` eligible objectives for immediate execution
        executable_ids = {
            item["objective"].objective_id
            for item in ranked_order[: max(1, int(max_objectives_to_execute))]
            if item["eligible"]
        }

        mission_reports: list[MissionExecutionReport] = []
        harvested_memory_ids: list[str] = []
        minted_blueprints: list[ServiceBlueprint] = []
        customer_deliveries: list[CustomerDeliveryReceipt] = []
        assessments: list[SixQuestionAssessment] = []

        for item in evaluated:
            obj: BusinessObjective = item["objective"]
            fidelity: GoalFidelityAssessment = item["fidelity"]
            cavo = item["cavo"]
            rank = rank_by_id[obj.objective_id]
            better_exists = (
                top_eligible is not None
                and top_eligible["objective"].objective_id != obj.objective_id
                and top_net_ev > float(cavo["expected_net_value_minor"])
            )
            better_id = (
                top_eligible["objective"].objective_id
                if better_exists and top_eligible is not None
                else None
            )

            # Determine Q4 Disposition
            if fidelity.verdict in ("REJECT_FORBIDDEN_BY_CHARTER", "REJECT_OFF_STRATEGY"):
                disposition: ActionDisposition = "TERMINATE_CHARTER_VIOLATION"
            elif fidelity.verdict == "ESCALATE_OWNER_AUTHORITY":
                disposition = "MODIFY_SCOPE_OR_ESCALATE_OWNER"
            elif not cavo["all_steps_justified"] or cavo["expected_roi_ratio"] < charter.min_roi_hurdle_ratio:
                disposition = "TERMINATE_NEGATIVE_EV"
            elif obj.objective_id not in executable_ids and obj.objective_id in selected_ids:
                disposition = "DEFER_FOR_HIGHER_EV_OPPORTUNITY"
            else:
                disposition = "EXECUTE_AND_DELEGATE"

            if disposition != "EXECUTE_AND_DELEGATE":
                assessments.append(
                    SixQuestionAssessment(
                        objective_id=obj.objective_id,
                        title=obj.title,
                        q1_right_task_aligned=fidelity.aligned,
                        q1_charter_verdict=fidelity.verdict,
                        q1_rationale=fidelity.rationale,
                        q2_better_opportunity_exists=better_exists,
                        q2_portfolio_rank=rank,
                        q2_better_opportunity_id=better_id,
                        q2_expected_net_value_minor=float(cavo["expected_net_value_minor"]),
                        q2_top_alternative_net_value_minor=top_net_ev,
                        q3_next_krone_justified=bool(cavo["all_steps_justified"]),
                        q3_expected_cavo_minor=float(cavo["expected_cavo_minor"]),
                        q3_expected_verified_value_minor=float(cavo["expected_verified_value_minor"]),
                        q3_expected_roi_ratio=float(cavo["expected_roi_ratio"]),
                        q4_recommended_disposition=disposition,
                        q4_assigned_crew_roles=cavo["crew_roles"],
                        q5_outcome_delivered_and_verified=False,
                        q5_verification_evidence_digest=None,
                        q5_verifier_seal=None,
                        q6_memory_entry_id=None,
                        q6_service_blueprint_id=None,
                        q6_published_service_id=None,
                        q6_recommended_price_minor=None,
                        q6_next_improvement_recommendation=(
                            f"Skipped execution ({disposition}); allocate capital to '{better_id or 'aligned positive-EV backlog'}'."
                        ),
                    )
                )
                continue

            # Execute selected objective with recalled company memory
            recalled = self.memory.recall(
                provider=provider_id,
                tenant=tenant_id,
                company=charter.company_id,
                identity=identity,
                verified_only=True,
                limit=5,
            )
            report = self.mission_engine.execute_objective(
                provider_id=provider_id,
                tenant_id=tenant_id,
                identity=identity,
                objective=obj,
                memory_lessons=tuple(m.lesson for m in recalled),
            )
            mission_reports.append(report)
            self.store.record_mission(
                provider_id,
                tenant_id,
                charter.company_id,
                {**report.as_dict(), "title": obj.title},
                identity,
            )

            mem_entry_id: str | None = None
            bp_id: str | None = None
            svc_id: str | None = None
            rec_price: int | None = None
            delivery_id: str | None = None

            if report.independently_verified:
                mem_res = self.memory.record_verified_outcome(
                    provider=provider_id,
                    tenant=tenant_id,
                    company=charter.company_id,
                    identity=identity,
                    task_kind="implementation",
                    lesson=(
                        f"Verified '{obj.title}' ({obj.objective_id}) with net EV "
                        f"{report.net_economic_value_minor:.2f} {obj.currency} and ROI {report.roi_ratio:.2f}x."
                    ),
                    verification=report.verification,
                    cost_minor=report.total_economic_cost_minor,
                    verified_value_minor=report.verified_value_minor,
                )
                mem_entry_id = str(mem_res["entry_id"])
                harvested_memory_ids.append(mem_entry_id)

                if auto_productize_services and report.net_economic_value_minor > 0:
                    candidate_svc_id = f"svc-{obj.objective_id.lower()[:48]}"
                    if not IDENT.fullmatch(candidate_svc_id):
                        candidate_svc_id = "svc-verified-autonomous"
                    bp = self.factory.synthesize_from_mission(
                        provider=provider_id,
                        tenant=tenant_id,
                        company=charter.company_id,
                        identity=identity,
                        service_id=candidate_svc_id,
                        title=f"Managed {obj.title}",
                        report=report,
                        currency=obj.currency,
                        provider_store=self.store,
                    )
                    minted_blueprints.append(bp)
                    bp_id = bp.blueprint_id
                    svc_id = bp.service_id
                    rec_price = bp.recommended_price_minor

                if deliver_to_customer_id and authorize_external_delivery:
                    dlv_receipt = self.delivery_channel.deliver_verified_service(
                        provider_id=provider_id,
                        tenant_id=tenant_id,
                        company_id=charter.company_id,
                        identity=identity,
                        customer_id=deliver_to_customer_id,
                        service_id=svc_id or f"svc-{obj.objective_id.lower()[:32]}",
                        report=report,
                        authorize_external_effect=authorize_external_delivery,
                    )
                    customer_deliveries.append(dlv_receipt)
                    delivery_id = dlv_receipt.delivery_id
                    # The outbox is a queued artifact, not a completed external effect.
                    upgraded_semantics = CompletionSemanticsReport(
                        produced_artifact=report.completion_semantics.produced_artifact,
                        verified_artifact=report.completion_semantics.verified_artifact,
                        authorized_external_effect=False,
                        measured_business_result=report.completion_semantics.measured_business_result,
                        stage=report.completion_semantics.stage,
                        external_effect_receipt_digest=None,
                        summary=(
                            f"Independently verified artifact queued in authorized outbox "
                            f"({dlv_receipt.delivery_id}); external delivery not confirmed. "
                            f"Modeled net economic value {report.net_economic_value_minor} {obj.currency}."
                        ),
                    )
                    report = MissionExecutionReport(
                        **{
                            **{k: getattr(report, k) for k in report.__dataclass_fields__ if k != "completion_semantics"},
                            "completion_semantics": upgraded_semantics,
                        }
                    )
                    mission_reports[-1] = report

            assessments.append(
                SixQuestionAssessment(
                    objective_id=obj.objective_id,
                    title=obj.title,
                    q1_right_task_aligned=fidelity.aligned,
                    q1_charter_verdict=fidelity.verdict,
                    q1_rationale=fidelity.rationale,
                    q2_better_opportunity_exists=better_exists,
                    q2_portfolio_rank=rank,
                    q2_better_opportunity_id=better_id,
                    q2_expected_net_value_minor=float(cavo["expected_net_value_minor"]),
                    q2_top_alternative_net_value_minor=top_net_ev,
                    q3_next_krone_justified=True,
                    q3_expected_cavo_minor=float(cavo["expected_cavo_minor"]),
                    q3_expected_verified_value_minor=float(cavo["expected_verified_value_minor"]),
                    q3_expected_roi_ratio=float(cavo["expected_roi_ratio"]),
                    q4_recommended_disposition=disposition,
                    q4_assigned_crew_roles=cavo["crew_roles"],
                    q5_outcome_delivered_and_verified=report.independently_verified,
                    q5_verification_evidence_digest=report.verification.evidence_digest,
                    q5_verifier_seal=report.verification.verifier_seal,
                    q6_memory_entry_id=mem_entry_id,
                    q6_service_blueprint_id=bp_id,
                    q6_published_service_id=svc_id,
                    q6_recommended_price_minor=rec_price,
                    q6_next_improvement_recommendation=(
                        f"Promoted to catalog service '{svc_id}' at {rec_price} {obj.currency} and stored verified lesson {mem_entry_id}."
                        if svc_id
                        else "Analyze verification failure and refine step prompts before re-allocating budget."
                    ),
                    q6_customer_delivery_id=delivery_id,
                )
            )

        total_cost = round(sum(r.total_economic_cost_minor for r in mission_reports), 4)
        total_val = sum(r.verified_value_minor for r in mission_reports)
        total_net = round(float(total_val) - total_cost, 4)
        verified_count = sum(1 for r in mission_reports if r.independently_verified)
        portfolio_cavo = round(total_cost / verified_count, 4) if verified_count > 0 else total_cost
        total_humans = sum(r.human_interventions_required for r in mission_reports)

        digest_payload = {
            "provider_id": provider_id,
            "tenant_id": tenant_id,
            "company_id": charter.company_id,
            "candidates_evaluated": len(candidate_objectives),
            "objectives_executed": len(mission_reports),
            "objectives_verified": verified_count,
            "total_cost": total_cost,
            "total_val": total_val,
            "report_digests": [r.report_digest for r in mission_reports],
        }
        cycle_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return CompanyOperatingCycleReport(
            provider_id=provider_id,
            tenant_id=tenant_id,
            company_id=charter.company_id,
            identity=identity,
            charter=charter,
            candidates_evaluated=len(candidate_objectives),
            objectives_executed=len(mission_reports),
            objectives_verified=verified_count,
            objectives_terminated_or_deferred=len(candidate_objectives) - len(mission_reports),
            total_measured_cost_minor=total_cost,
            total_verified_value_minor=total_val,
            total_net_economic_value_minor=total_net,
            portfolio_cavo_minor=portfolio_cavo,
            human_interventions_required=total_humans,
            six_question_assessments=tuple(assessments),
            mission_reports=tuple(mission_reports),
            harvested_memory_ids=tuple(harvested_memory_ids),
            minted_blueprints=tuple(minted_blueprints),
            cycle_digest=cycle_digest,
            customer_deliveries=tuple(customer_deliveries),
        )


# Explicit, honest Product Readiness Matrix across all 15 Hermes Unlimited areas.
# Untested external adapters (e.g. PSTN telephony, live bank invoicing) are never marked approved.
PRODUCT_READINESS_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "area": "Captain's Bridge",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/a2ui_adapter.py", "unlimited/a2ui_bridge.py", "unlimited/company_os.py"),
        "verified_capabilities": "Read-only A2UI 1.0 surfaces for companies, requests, and missions; loopback token bridge; owner CompanyCharter governance.",
        "remaining_limitations": "Interactive write actions from browser UI intentionally disabled by read-only A2UI security contract.",
    },
    {
        "area": "Company Engine",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/runtime.py", "unlimited/company_os.py"),
        "verified_capabilities": "Tenant-isolated SQLite company/service/request/mission registry + AutonomousCompanyOperatingSystem cycle.",
        "remaining_limitations": "Single-node SQLite storage; multi-region distributed consensus not yet enabled.",
    },
    {
        "area": "Crew",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/autonomy.py", "unlimited/socratic_council.py"),
        "verified_capabilities": "Role-specialized DAG execution (director, researcher, builder, skeptic, verifier, operator) + blind 4-lens Socratic Council.",
        "remaining_limitations": "Fixed 4-step standard DAG template unless custom WorkStep DAG is supplied on BusinessObjective.",
    },
    {
        "area": "Mission Control",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/autonomy.py", "unlimited/company_os.py", "unlimited/tools.py"),
        "verified_capabilities": "Goal Fidelity charter screening, CAVO portfolio ranking, DAG delegation, checkpoint/resume, and durable SQLite step idempotency.",
        "remaining_limitations": "Cross-process distributed lock manager for concurrent workers on the same objective ID is local-SQLite scoped.",
    },
    {
        "area": "AI Bridge",
        "priority": "P0",
        "status": "HOST_INTEGRATION_REQUIRED",
        "modules": ("unlimited/economics.py", "unlimited/ports.py"),
        "verified_capabilities": "Deterministic model-cost and routing policy evaluation; model execution delegated to host-provisioned worker.",
        "remaining_limitations": "Live multi-provider routing and failover are owned by the Hermes host and not verified by this plugin.",
    },
    {
        "area": "Toolshed / Jackets",
        "priority": "P1",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/tools.py", "unlimited/integrations.py"),
        "verified_capabilities": "17 native Hermes Unlimited tools with profile-scoped registration and host-authorized mission integration.",
        "remaining_limitations": "External third-party SaaS Jackets remain unapproved until individually sandbox-verified.",
    },
    {
        "area": "Company Memory",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/memory_factory.py",),
        "verified_capabilities": "Epistemic separation of RECORDED_UNVERIFIED self-reports vs VERIFIED_OUTCOME lessons with HMAC-sealed receipt verification and tenant isolation.",
        "remaining_limitations": "Keyword/scope SQLite recall; vector embedding semantic index not yet attached.",
    },
    {
        "area": "Completion Engine",
        "priority": "P1",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/autonomy.py", "unlimited/hermes_kanban.py"),
        "verified_capabilities": "10-layer IndependentOutcomeVerifier, VerifierSigningAuthority key custody, cross-provider LLM critic, and blocked Kanban task recovery.",
        "remaining_limitations": "In-process VerifierSigningAuthority shares host OS user boundary unless deployed on a separate verifier host.",
    },
    {
        "area": "Service Factory",
        "priority": "P1",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/memory_factory.py", "unlimited/company_os.py"),
        "verified_capabilities": "Automatic synthesis of positive-EV verified missions into priced ServiceBlueprints and publication to ProviderStore catalog.",
        "remaining_limitations": "Pricing calibration uses observed cost + verified value heuristics rather than live market demand elasticity.",
    },
    {
        "area": "Business Economics",
        "priority": "P1",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/economics.py", "unlimited/company_os.py"),
        "verified_capabilities": "Continuous marginal EV gating, CAVO portfolio ranking, Bayesian Beta posteriors, and strict separation of measured telemetry vs modeled costs.",
        "remaining_limitations": "Provider USD cost telemetry depends on provider reporting or official rate-card snapshots.",
    },
    {
        "area": "Communications",
        "priority": "P2",
        "status": "PARTIAL_UNAPPROVED_ADAPTERS",
        "modules": ("unlimited/a2ui_adapter.py", "unlimited/socratic_council.py"),
        "verified_capabilities": "Structured agent-to-owner A2UI surfaces and internal Socratic Council deliberation.",
        "remaining_limitations": "External email, PSTN phone, and live meeting adapters are NOT implemented or approved.",
    },
    {
        "area": "Business Operations",
        "priority": "P2",
        "status": "PARTIAL_UNAPPROVED_ADAPTERS",
        "modules": ("unlimited/runtime.py", "unlimited/memory_factory.py"),
        "verified_capabilities": "Service catalog publication, customer service request intake, and autonomous fulfillment tracking.",
        "remaining_limitations": "External payment processing, invoicing, and CRM adapters are NOT approved or enabled.",
    },
    {
        "area": "Operations / Compute",
        "priority": "P1",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/hermes_kanban.py", "unlimited/autonomy.py"),
        "verified_capabilities": "Host-authorized mission workers, JSON checkpoint/resume, durable SQLite idempotency, and Kanban retry.",
        "remaining_limitations": "Multi-machine SSH/cluster worker provisioning is not automated inside this package.",
    },
    {
        "area": "JustYou",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/justyou.py", "unlimited/justyou_host.py", "unlimited/runtime.py"),
        "verified_capabilities": "Mandatory session + signed profile binding verification, zero session authority escalation, and strict tenant/company scoping.",
        "remaining_limitations": "Requires trusted host session_store and resolver injection for live customer sessions.",
    },
    {
        "area": "Verification / Governance",
        "priority": "P0",
        "status": "VERIFIED_CORE",
        "modules": ("unlimited/autonomy.py", "unlimited/socratic_council.py", "unlimited/company_os.py"),
        "verified_capabilities": "VerifierSigningAuthority HMAC seals, anti-replay tokens, cross-provider LLM critic, and zero-authority Socratic Council.",
        "remaining_limitations": "Hardware HSM / remote attestation for VerifierSigningAuthority is optional future hardening.",
    },
)
