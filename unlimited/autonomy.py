"""Autonomous Mission & Completion Engine for Hermes Unlimited.

Implements the 9-step autonomous loop:
1. Receive a business objective.
2. Decompose into a DAG of executable work steps across AI Crew roles.
3. Select optimal models and role-scoped tools via AI Bridge routing.
4. Execute independently with idempotency (in-memory + durable SQLite) and checkpointing.
5. Detect failures (routing, runtime, invalid output) and recover autonomously.
6. Verify actual outcomes via a multi-layer independent verifier (never trust self-reports
   or bare SHA-256 digests).
7. Calculate total execution costs separating measured telemetry from modeled economics.
8. Evaluate marginal Expected Value (EV) before every model call or retry.
9. Stop when the objective is verified complete or further work has EV <= 0.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json
import os
import re
import signal
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from .economics import (
    CostBreakdown,
    EconomicIntelligenceEngine,
    EconomicPolicy,
    MarginalEVDecision,
    ModelRouter,
    RoutingStrategy,
)

ROLE_TOOLSETS: Mapping[str, tuple[str, ...]] = {
    "director": ("objective_planner", "scope_validator"),
    "researcher": ("company_memory_recall", "evidence_extractor"),
    "builder": ("artifact_synthesizer", "schema_packager"),
    "skeptic": ("adversarial_critic", "invariant_checker"),
    "verifier": ("independent_outcome_verifier",),
    "operator": ("service_dispatcher", "kanban_monitor"),
}

FORBIDDEN_PLACEHOLDERS = (
    "TODO",
    "TBD",
    "PLACEHOLDER",
    "LOREM_IPSUM",
    "FABRICATED",
    "FIXME",
    "INSERT_HERE",
    "MOCK_DATA",
    "[YOUR_",
    "<INSERT",
)

QUANTITATIVE_KEY_MARKERS = (
    "quantified",
    "impact",
    "metric",
    "roi",
    "cost",
    "financial",
    "budget",
    "pricing",
    "saving",
)

QUANTITATIVE_UNIT_PATTERN = re.compile(
    r"(%|nok|usd|eur|kr|øre|minor|bps|ms|sec|s\b|min|hour|hr|day|week|month|year|x\b|delta|"
    r"saving|reduction|increase|margin|revenue|cost|roi|payback|target|baseline|ratio)",
    re.IGNORECASE,
)

WORD_TOKEN_PATTERN = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)

_DEFAULT_VERIFIER_SECRET = b"hermes-unlimited-independent-verifier-v2-key"


@dataclass(frozen=True)
class WorkStep:
    """A single node in the decomposed business objective DAG."""

    step_id: str
    title: str
    role: str
    task_kind: str
    complexity: Literal["low", "medium", "high"]
    depends_on: tuple[str, ...] = ()
    required_output_keys: tuple[str, ...] = ()
    marginal_value_share: float = 0.25
    estimated_input_tokens: int = 800
    estimated_output_tokens: int = 450
    step_deadline_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.step_id or not isinstance(self.step_id, str):
            raise ValueError("STEP_ID_REQUIRED")
        if self.role not in ROLE_TOOLSETS:
            raise ValueError(f"UNKNOWN_CREW_ROLE:{self.role}")
        if self.complexity not in ("low", "medium", "high"):
            raise ValueError("COMPLEXITY_INVALID")
        if not (0.0 < self.marginal_value_share <= 1.0):
            raise ValueError("MARGINAL_VALUE_SHARE_INVALID")
        if self.step_deadline_seconds is not None and self.step_deadline_seconds <= 0:
            raise ValueError("STEP_DEADLINE_INVALID")


@dataclass(frozen=True)
class BusinessObjective:
    """Formal business objective with measurable value and acceptance criteria."""

    objective_id: str
    company_id: str
    title: str
    description: str
    target_value_minor: int
    currency: str = "NOK"
    required_deliverables: tuple[str, ...] = (
        "executive_summary",
        "action_plan",
        "quantified_impact",
        "risk_mitigations",
    )
    acceptance_criteria: Mapping[str, Any] = field(default_factory=dict)
    policy: EconomicPolicy = field(default_factory=EconomicPolicy)
    steps: tuple[WorkStep, ...] = ()

    def __post_init__(self) -> None:
        if not self.objective_id or not self.company_id or not self.title:
            raise ValueError("OBJECTIVE_METADATA_REQUIRED")
        if type(self.target_value_minor) is not int or self.target_value_minor < 0:
            raise ValueError("TARGET_VALUE_INVALID")
        if not self.required_deliverables:
            raise ValueError("REQUIRED_DELIVERABLES_EMPTY")


@dataclass(frozen=True)
class StepAttemptReceipt:
    """Immutable record of one execution attempt for a work step."""

    step_id: str
    attempt: int
    model_id: str
    tools_bound: tuple[str, ...]
    status: Literal[
        "completed",
        "routing_error",
        "runtime_error",
        "invalid_output",
        "aborted_economic",
    ]
    output: Mapping[str, Any] | None
    error_reason: str | None
    cost: CostBreakdown
    ev_decision_digest: str
    receipt_digest: str


@dataclass(frozen=True)
class OutcomeVerificationReceipt:
    """Independent verification verdict — separate from agent self-report.

    Includes a keyed HMAC-SHA256 `verifier_seal` bound to objective_id, tenant_id,
    company_id, policy_digest, deliverable_digest, and evidence_digest so workers
    or external callers cannot forge, tamper with, or replay a receipt across scopes.
    """

    objective_id: str
    independently_verified: bool
    agent_claimed_complete: bool
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    deliverable_digest: str
    evidence_digest: str
    verifier_seal: str = ""
    independent_critic_verdict: Mapping[str, Any] | None = None
    tenant_id: str = ""
    company_id: str = ""
    policy_digest: str = ""
    authority_key_id: str = "verifier-authority-v2"

    def as_dict(self) -> dict:
        return asdict(self)


def compute_objective_policy_digest(objective: BusinessObjective) -> str:
    """Compute a deterministic digest of the objective's economic policy and scope contract."""
    payload = {
        "objective_id": objective.objective_id,
        "company_id": objective.company_id,
        "target_value_minor": objective.target_value_minor,
        "currency": objective.currency,
        "required_deliverables": list(objective.required_deliverables),
        "budget_ceiling_minor": objective.policy.budget_ceiling_minor,
        "sla_seconds": objective.policy.sla_seconds,
        "max_step_attempts": objective.policy.max_step_attempts,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class VerifierSigningAuthority:
    """Isolated signing authority and anti-replay key custody for outcome verification.

    Key material is held exclusively inside the authority instance and is never
    exposed to worker execution contexts or serialized into mission reports.
    """

    def __init__(
        self,
        *,
        secret_key: bytes | str | None = None,
        key_id: str = "verifier-authority-v2",
    ) -> None:
        raw_key = (
            secret_key
            if secret_key is not None
            else os.environ.get("HERMES_UNLIMITED_VERIFIER_SECRET", _DEFAULT_VERIFIER_SECRET)
        )
        self.__signing_key: bytes = (
            raw_key.encode("utf-8") if isinstance(raw_key, str) else bytes(raw_key)
        )
        if len(self.__signing_key) < 16:
            raise ValueError("VERIFIER_SIGNING_KEY_TOO_SHORT")
        self.key_id = key_id
        self._consumed_seals: set[tuple[str, str]] = set()

    def sign(self, canonical_payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(canonical_payload, sort_keys=True).encode("utf-8")
        return hmac.new(self.__signing_key, encoded, hashlib.sha256).hexdigest()

    def verify(self, canonical_payload: Mapping[str, Any], seal: str) -> bool:
        if not isinstance(seal, str) or len(seal) != 64:
            return False
        expected = self.sign(canonical_payload)
        return hmac.compare_digest(expected, seal)

    def check_and_consume(self, seal: str, *, consumer_scope: str = "default") -> bool:
        """Record a seal as consumed in the given scope; return False if replayed."""
        token = (consumer_scope, seal)
        if token in self._consumed_seals:
            return False
        self._consumed_seals.add(token)
        return True


CompletionStage = Literal[
    "none",
    "produced_artifact",
    "verified_artifact",
    "authorized_external_effect",
    "measured_business_result",
]


@dataclass(frozen=True)
class CompletionSemanticsReport:
    """Explicit separation of completion stages so self-reported artifacts are never conflated with verified business results."""

    produced_artifact: bool = False
    verified_artifact: bool = False
    authorized_external_effect: bool = False
    measured_business_result: bool = False
    stage: CompletionStage = "none"
    external_effect_receipt_digest: str | None = None
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissionExecutionReport:
    """End-to-end report for an autonomous business objective execution."""

    objective_id: str
    company_id: str
    tenant_id: str
    identity: str
    routing_strategy: RoutingStrategy
    status: Literal[
        "VERIFIED_COMPLETE",
        "STOPPED_NEGATIVE_EV",
        "STOPPED_BUDGET_EXCEEDED",
        "STOPPED_SLA_EXCEEDED",
        "STOPPED_UNVERIFIED_OUTCOME",
        "INTERRUPTED_CHECKPOINTED",
    ]
    independently_verified: bool
    target_value_minor: int
    verified_value_minor: int
    direct_cost_minor: float
    total_economic_cost_minor: float
    recovery_spend_minor: float
    net_economic_value_minor: float
    roi_ratio: float
    elapsed_seconds: float
    total_model_calls: int
    total_input_tokens: int
    total_output_tokens: int
    failures_detected: int
    autonomous_recoveries: int
    duplicate_actions_prevented: int
    human_interventions_required: int
    stop_reason: str
    deliverables: Mapping[str, Any]
    verification: OutcomeVerificationReceipt
    step_receipts: tuple[StepAttemptReceipt, ...]
    ev_decisions: tuple[dict, ...]
    checkpoint_state: dict
    report_digest: str
    measured_telemetry: Mapping[str, Any] = field(default_factory=dict)
    modeled_economics: Mapping[str, Any] = field(default_factory=dict)
    completion_semantics: CompletionSemanticsReport = field(
        default_factory=CompletionSemanticsReport
    )

    def as_dict(self) -> dict:
        data = asdict(self)
        return data


class ObjectiveDecomposer:
    """Decomposes a high-level BusinessObjective into an executable crew DAG."""

    @staticmethod
    def decompose(objective: BusinessObjective) -> tuple[WorkStep, ...]:
        if objective.steps:
            ObjectiveDecomposer._validate_dag(objective.steps)
            return objective.steps

        deliverables = tuple(objective.required_deliverables)
        combined_text = f"{objective.objective_id} {objective.title} {objective.description}".lower()
        is_complex_synthesis = any(
            kw in combined_text for kw in ("complex", "audit", "synthesis", "architecture")
        )
        build_kind = "synthesis" if is_complex_synthesis else "implementation"
        base_deadline = float(getattr(objective.policy, "step_deadline_seconds", 35.0) or 35.0)
        steps = (
            WorkStep(
                step_id="step-1-triage",
                title=f"Scope & decompose objective: {objective.title}",
                role="director",
                task_kind="triage",
                complexity="low",
                depends_on=(),
                required_output_keys=("scope_confirmed", "target_deliverables", "constraints"),
                marginal_value_share=0.15,
                estimated_input_tokens=600,
                estimated_output_tokens=300,
                step_deadline_seconds=min(base_deadline, 25.0),
            ),
            WorkStep(
                step_id="step-2-research",
                title=f"Gather domain evidence & baseline economics for {objective.company_id}",
                role="researcher",
                task_kind="research",
                complexity="medium",
                depends_on=("step-1-triage",),
                required_output_keys=("evidence_items", "baseline_metrics"),
                marginal_value_share=0.25,
                estimated_input_tokens=950,
                estimated_output_tokens=500,
                step_deadline_seconds=min(base_deadline, 30.0),
            ),
            WorkStep(
                step_id="step-3-build",
                title=f"Produce concrete deliverables for {objective.title}",
                role="builder",
                task_kind=build_kind,
                complexity="medium",
                depends_on=("step-2-research",),
                required_output_keys=deliverables,
                marginal_value_share=0.40,
                estimated_input_tokens=1200,
                estimated_output_tokens=750,
                step_deadline_seconds=base_deadline,
            ),
            WorkStep(
                step_id="step-4-critique",
                title="Adversarial Skeptic & Reality Checker audit of deliverables",
                role="skeptic",
                task_kind="verification",
                complexity="low",
                depends_on=("step-3-build",),
                required_output_keys=("audit_passed", "challenged_assumptions", "verified_keys"),
                marginal_value_share=0.20,
                estimated_input_tokens=900,
                estimated_output_tokens=350,
                step_deadline_seconds=min(base_deadline, 25.0),
            ),
        )
        ObjectiveDecomposer._validate_dag(steps)
        return steps

    @staticmethod
    def _validate_dag(steps: tuple[WorkStep, ...]) -> None:
        if not steps:
            raise ValueError("DAG_EMPTY")
        seen: set[str] = set()
        for step in steps:
            if step.step_id in seen:
                raise ValueError(f"DUPLICATE_STEP_ID:{step.step_id}")
            for dep in step.depends_on:
                if dep not in seen:
                    raise ValueError(f"INVALID_OR_CYCLIC_DEPENDENCY:{step.step_id}->{dep}")
            seen.add(step.step_id)


IndependentCriticCallable = Callable[
    [BusinessObjective, Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]


class IndependentOutcomeVerifier:
    """Multi-layer independent outcome verifier with cryptographic seal.

    Never equates an agent claiming 'status: done' or a bare SHA-256 digest with
    a verified business outcome. Enforces:
    1. Identity & tenant scope presence.
    2. Complete DAG step execution provenance.
    3. Substantive deliverable content & expanded anti-placeholder checks.
    4. Deliverable distinctness (blocks copy-pasted or repetitive boilerplate across keys).
    5. Quantitative rigor on financial/metric deliverables (requires numbers + units).
    6. Cross-step context grounding (deliverables must reference company/objective/research).
    7. Skeptic critique gate integrity (audit_passed=True and all deliverable keys verified).
    8. Custom domain terms, validators, and on-disk artifact file checks.
    9. Optional external/cross-model `independent_critic` audit.
    10. Keyed HMAC-SHA256 `verifier_seal` for tamper and forgery detection.
    """

    def __init__(
        self,
        *,
        independent_critic: IndependentCriticCallable | None = None,
        secret_key: bytes | str = _DEFAULT_VERIFIER_SECRET,
        authority: VerifierSigningAuthority | None = None,
    ) -> None:
        self.independent_critic = independent_critic
        self.authority = authority or VerifierSigningAuthority(secret_key=secret_key)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {m.group(0).lower() for m in WORD_TOKEN_PATTERN.finditer(text)}

    def _compute_seal(
        self,
        *,
        objective_id: str,
        independently_verified: bool,
        deliverable_digest: str,
        evidence_digest: str,
        checks_passed: tuple[str, ...],
        checks_failed: tuple[str, ...],
        tenant_id: str = "",
        company_id: str = "",
        policy_digest: str = "",
        authority_key_id: str = "verifier-authority-v2",
    ) -> str:
        canonical = {
            "objective_id": objective_id,
            "tenant_id": tenant_id,
            "company_id": company_id,
            "policy_digest": policy_digest,
            "authority_key_id": authority_key_id,
            "independently_verified": independently_verified,
            "deliverable_digest": deliverable_digest,
            "evidence_digest": evidence_digest,
            "checks_passed": list(checks_passed),
            "checks_failed": list(checks_failed),
        }
        return self.authority.sign(canonical)

    def verify_receipt_authenticity(
        self,
        receipt: OutcomeVerificationReceipt,
        *,
        deliverables: Mapping[str, Any] | None = None,
        expected_tenant_id: str | None = None,
        expected_company_id: str | None = None,
        expected_objective_id: str | None = None,
        expected_policy_digest: str | None = None,
        reject_replay: bool = False,
        consumer_scope: str = "default",
    ) -> bool:
        """Verify that a receipt was genuinely sealed by IndependentOutcomeVerifier and not forged or replayed."""
        if not isinstance(receipt, OutcomeVerificationReceipt):
            return False
        if not receipt.verifier_seal or len(receipt.verifier_seal) != 64:
            return False
        if expected_objective_id is not None and receipt.objective_id != expected_objective_id:
            return False
        if expected_tenant_id is not None and receipt.tenant_id and receipt.tenant_id != expected_tenant_id:
            return False
        if expected_company_id is not None and receipt.company_id and receipt.company_id != expected_company_id:
            return False
        if expected_policy_digest is not None and receipt.policy_digest and receipt.policy_digest != expected_policy_digest:
            return False
        if deliverables is not None:
            actual_deliv_digest = hashlib.sha256(
                json.dumps(deliverables, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(actual_deliv_digest, receipt.deliverable_digest):
                return False
        expected_seal = self._compute_seal(
            objective_id=receipt.objective_id,
            independently_verified=receipt.independently_verified,
            deliverable_digest=receipt.deliverable_digest,
            evidence_digest=receipt.evidence_digest,
            checks_passed=tuple(receipt.checks_passed),
            checks_failed=tuple(receipt.checks_failed),
            tenant_id=receipt.tenant_id,
            company_id=receipt.company_id,
            policy_digest=receipt.policy_digest,
            authority_key_id=receipt.authority_key_id,
        )
        if not hmac.compare_digest(expected_seal, receipt.verifier_seal):
            return False
        if reject_replay and not self.authority.check_and_consume(
            receipt.verifier_seal, consumer_scope=consumer_scope
        ):
            return False
        return True

    def verify(
        self,
        objective: BusinessObjective,
        deliverables: Mapping[str, Any],
        step_receipts: tuple[StepAttemptReceipt, ...],
        *,
        tenant_id: str,
        identity: str,
    ) -> OutcomeVerificationReceipt:
        passed: list[str] = []
        failed: list[str] = []

        if not tenant_id or not identity:
            failed.append("identity_and_tenant_scope_present")
        else:
            passed.append("identity_and_tenant_scope_present")

        completed_steps = {
            r.step_id: r for r in step_receipts if r.status == "completed" and r.output is not None
        }
        expected_steps = ObjectiveDecomposer.decompose(objective)
        if all(s.step_id in completed_steps for s in expected_steps):
            passed.append("all_dag_steps_completed")
        else:
            missing_steps = [s.step_id for s in expected_steps if s.step_id not in completed_steps]
            failed.append(f"missing_dag_steps:{','.join(missing_steps)}")

        # Check every required deliverable key
        min_len = int(objective.acceptance_criteria.get("min_deliverable_chars", 12))
        serialized_by_key: dict[str, str] = {}
        for key in objective.required_deliverables:
            val = deliverables.get(key)
            if val is None:
                failed.append(f"deliverable_present:{key}")
                continue
            serialized = json.dumps(val, sort_keys=True) if not isinstance(val, str) else val.strip()
            if len(serialized) < min_len:
                failed.append(f"deliverable_substantive:{key}")
                continue
            upper = serialized.upper()
            if any(tok in upper for tok in FORBIDDEN_PLACEHOLDERS):
                failed.append(f"deliverable_no_placeholders:{key}")
                continue
            serialized_by_key[key] = serialized
            passed.append(f"deliverable_verified:{key}")

            # Quantitative rigor check for impact/metric/cost/ROI deliverables
            if any(marker in key.lower() for marker in QUANTITATIVE_KEY_MARKERS):
                has_digit = any(ch.isdigit() for ch in serialized)
                has_unit = bool(QUANTITATIVE_UNIT_PATTERN.search(serialized))
                if has_digit and has_unit:
                    passed.append(f"quantified_deliverable_rigor:{key}")
                else:
                    failed.append(f"missing_quantitative_metrics:{key}")

        # Check distinctness across deliverables (defeat copy-paste / identical boilerplate)
        verified_keys_list = list(serialized_by_key.keys())
        if len(verified_keys_list) >= 2:
            duplicate_pair: tuple[str, str] | None = None
            for idx, k1 in enumerate(verified_keys_list):
                s1 = " ".join(serialized_by_key[k1].lower().split())
                t1 = self._tokenize(s1)
                for k2 in verified_keys_list[idx + 1:]:
                    s2 = " ".join(serialized_by_key[k2].lower().split())
                    if s1 == s2:
                        duplicate_pair = (k1, k2)
                        break
                    t2 = self._tokenize(s2)
                    if len(t1) >= 6 and len(t2) >= 6:
                        union = len(t1 | t2)
                        jaccard = (len(t1 & t2) / union) if union else 1.0
                        if jaccard >= 0.90:
                            duplicate_pair = (k1, k2)
                            break
                if duplicate_pair is not None:
                    break
            if duplicate_pair is not None:
                failed.append(f"duplicate_or_repetitive_deliverables:{duplicate_pair[0]}:{duplicate_pair[1]}")
            else:
                passed.append("deliverables_distinct_and_non_repetitive")

        # Cross-step & company context grounding check
        if serialized_by_key:
            combined_lower = " ".join(serialized_by_key.values()).lower()
            context_tokens = {objective.company_id.lower()}
            context_tokens.update(
                tok for tok in self._tokenize(f"{objective.title} {objective.description}")
                if len(tok) >= 4 and tok not in {"deliver", "verified", "with", "from", "that", "this", "plan"}
            )
            research_rec = completed_steps.get("step-2-research")
            if research_rec and research_rec.output:
                context_tokens.update(
                    tok for tok in self._tokenize(json.dumps(research_rec.output))
                    if len(tok) >= 5
                )
            if any(tok in combined_lower for tok in context_tokens):
                passed.append("deliverables_grounded_in_context")
            else:
                failed.append("ungrounded_in_company_or_research_context")

        # Check skeptic audit gate if present in DAG
        skeptic_receipt = completed_steps.get("step-4-critique")
        if skeptic_receipt is not None and skeptic_receipt.output is not None:
            skeptic_verified = set(skeptic_receipt.output.get("verified_keys") or ())
            if (
                skeptic_receipt.output.get("audit_passed") is True
                and set(objective.required_deliverables).issubset(skeptic_verified)
            ):
                passed.append("skeptic_critique_gate_passed")
            else:
                failed.append("skeptic_critique_gate_failed")

        # Check custom numerical or structural invariants in acceptance_criteria
        required_substrings = objective.acceptance_criteria.get("required_terms", ())
        full_text = json.dumps(deliverables, sort_keys=True).lower()
        for term in required_substrings:
            if str(term).lower() in full_text:
                passed.append(f"required_term:{term}")
            else:
                failed.append(f"missing_required_term:{term}")

        # Check required on-disk artifact files if specified in acceptance_criteria
        required_files = objective.acceptance_criteria.get("required_files", ())
        for file_path in required_files:
            p = Path(str(file_path))
            if p.is_file() and p.stat().st_size > 0:
                passed.append(f"artifact_file_verified:{p.name}")
            else:
                failed.append(f"missing_or_empty_artifact_file:{p.name}")

        custom_validator = objective.acceptance_criteria.get("validator")
        if callable(custom_validator):
            try:
                if custom_validator(deliverables) is True:
                    passed.append("custom_validator_passed")
                else:
                    failed.append("custom_validator_rejected")
            except Exception as exc:
                failed.append(f"custom_validator_error:{type(exc).__name__}")

        # Run external / cross-model independent critic if configured
        critic_fn = objective.acceptance_criteria.get("independent_critic") or self.independent_critic
        critic_verdict: Mapping[str, Any] | None = None
        if callable(critic_fn) and len(failed) == 0:
            try:
                critic_verdict = critic_fn(
                    objective,
                    deliverables,
                    {
                        "tenant_id": tenant_id,
                        "identity": identity,
                        "step_receipts": step_receipts,
                    },
                )
                if isinstance(critic_verdict, Mapping) and critic_verdict.get("verified") is True:
                    passed.append("independent_critic_verified")
                else:
                    reason = (
                        str(critic_verdict.get("reason", "rejected"))
                        if isinstance(critic_verdict, Mapping)
                        else "invalid_critic_response"
                    )
                    failed.append(f"independent_critic_rejected:{reason}")
            except Exception as exc:
                failed.append(f"independent_critic_error:{type(exc).__name__}")

        agent_claimed = bool(deliverables) and len(completed_steps) == len(expected_steps)
        independently_verified = len(failed) == 0 and len(passed) > 0

        deliv_digest = hashlib.sha256(
            json.dumps(deliverables, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        pol_digest = compute_objective_policy_digest(objective)
        evidence_payload = {
            "objective_id": objective.objective_id,
            "company_id": objective.company_id,
            "tenant_id": tenant_id,
            "identity": identity,
            "policy_digest": pol_digest,
            "independently_verified": independently_verified,
            "checks_passed": passed,
            "checks_failed": failed,
            "deliverable_digest": deliv_digest,
            "step_digests": [r.receipt_digest for r in step_receipts if r.status == "completed"],
        }
        evidence_digest = hashlib.sha256(
            json.dumps(evidence_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        seal = self._compute_seal(
            objective_id=objective.objective_id,
            independently_verified=independently_verified,
            deliverable_digest=deliv_digest,
            evidence_digest=evidence_digest,
            checks_passed=tuple(passed),
            checks_failed=tuple(failed),
            tenant_id=tenant_id,
            company_id=objective.company_id,
            policy_digest=pol_digest,
            authority_key_id=self.authority.key_id,
        )

        return OutcomeVerificationReceipt(
            objective_id=objective.objective_id,
            independently_verified=independently_verified,
            agent_claimed_complete=agent_claimed,
            checks_passed=tuple(passed),
            checks_failed=tuple(failed),
            deliverable_digest=deliv_digest,
            evidence_digest=evidence_digest,
            verifier_seal=seal,
            independent_critic_verdict=critic_verdict,
            tenant_id=tenant_id,
            company_id=objective.company_id,
            policy_digest=pol_digest,
            authority_key_id=self.authority.key_id,
        )


@dataclass
class StepWorkerResult:
    """Result returned by an injected, live Hermes, or default step worker."""

    status: Literal["ok", "routing_error", "runtime_error"] = "ok"
    output: Mapping[str, Any] | None = None
    input_tokens: int = 800
    output_tokens: int = 450
    latency_sec: float = 3.0
    error_message: str | None = None
    provider_reported_cost_usd: float | None = None
    cost_source: str = "modeled_rate_card"
    telemetry_mode: Literal[
        "measured_live", "estimated_prior", "deterministic_simulation"
    ] = "deterministic_simulation"
    provider_id: str | None = None
    resolved_model_id: str | None = None
    tool_calls: tuple[str, ...] = ()
    api_calls: int = 1


StepWorkerCallable = Callable[
    [WorkStep, str, int, Mapping[str, Any], tuple[str, ...]],
    StepWorkerResult,
]


def default_deterministic_worker(
    step: WorkStep,
    model_id: str,
    attempt: int,
    context: Mapping[str, Any],
    repair_hints: tuple[str, ...],
) -> StepWorkerResult:
    """Deterministic local worker for reproducible offline execution and testing."""
    objective_title = str(context.get("objective_title", "Business Objective"))
    company_id = str(context.get("company_id", "company"))
    required_deliverables = tuple(context.get("required_deliverables", ()))
    memory_lessons = tuple(context.get("memory_lessons", ()))

    latency_map = {
        "gemini-4-hydrogen": 2.2,
        "gemini-4-argon": 5.5,
        "gemini-4-carbon": 12.5,
    }
    latency = latency_map.get(model_id, 4.0)

    if step.task_kind == "triage":
        out = {
            "scope_confirmed": True,
            "target_deliverables": list(required_deliverables),
            "constraints": {
                "company_id": company_id,
                "zero_human_supervision_target": True,
                "applied_memory_lessons": len(memory_lessons),
            },
        }
    elif step.task_kind == "research":
        out = {
            "evidence_items": [
                f"Verified tenant scope for {company_id}",
                f"Analyzed objective: {objective_title}",
                *(f"Recalled lesson: {lesson}" for lesson in memory_lessons[:3]),
            ],
            "baseline_metrics": {
                "target_autonomy_rate": 1.0,
                "model_tier_selected": model_id,
            },
        }
    elif step.task_kind in ("implementation", "synthesis"):
        out = {}
        repaired_note = (
            f" (repaired after {len(repair_hints)} diagnostic feedback item(s))"
            if repair_hints
            else ""
        )
        templates = {
            "executive_summary": (
                f"Executive board brief for {company_id} on '{objective_title}': "
                f"autonomous workflow synthesized via {model_id} on attempt {attempt}{repaired_note}."
            ),
            "action_plan": (
                f"Phased execution roadmap for {company_id}: Phase 1 intake triage, "
                f"Phase 2 automated implementation, Phase 3 independent audit for '{objective_title}' "
                f"(driver={model_id}, attempt={attempt}){repaired_note}."
            ),
            "quantified_impact": (
                f"Quantified financial impact for {company_id} ('{objective_title}'): "
                f"projected 24.5% cost reduction and 1,850 NOK minor net margin gain within 30 days "
                f"at 2.8x ROI (modeled by {model_id}, attempt {attempt}){repaired_note}."
            ),
            "risk_mitigations": (
                f"Operational risk register for {company_id}: strict JustYou tenant isolation, "
                f"SLA budget circuit-breakers, and automatic provider failover for '{objective_title}' "
                f"(verified by {model_id}, attempt {attempt}){repaired_note}."
            ),
        }
        for idx, key in enumerate(step.required_output_keys):
            if key in templates:
                out[key] = templates[key]
            else:
                out[key] = (
                    f"Deliverable #{idx + 1} [{key}] for {company_id} ('{objective_title}'): "
                    f"measurable target 15.{idx + 1}% improvement / {400 * (idx + 1)} NOK minor impact "
                    f"synthesized by {model_id} on attempt {attempt}{repaired_note}."
                )
    elif step.task_kind == "verification":
        prior_build = context.get("completed_outputs", {}).get("step-3-build", {})
        verified_keys = [
            k for k in required_deliverables
            if isinstance(prior_build.get(k), str) and len(prior_build.get(k, "")) >= 12
        ]
        out = {
            "audit_passed": len(verified_keys) == len(required_deliverables),
            "challenged_assumptions": [
                "Checked that completion is backed by distinct artifacts, not status flags",
                "Verified cost remains below budget ceiling and quantitative metrics are present",
            ],
            "verified_keys": verified_keys,
        }
    else:
        out = {
            k: f"Completed {k} for {company_id} with 100% pass rate via {model_id}"
            for k in step.required_output_keys
        }

    return StepWorkerResult(
        status="ok",
        output=out,
        input_tokens=step.estimated_input_tokens + (attempt - 1) * 120,
        output_tokens=step.estimated_output_tokens,
        latency_sec=latency,
        telemetry_mode="deterministic_simulation",
        cost_source="modeled_rate_card",
        provider_id="deterministic",
        resolved_model_id=model_id,
    )


class AutonomousMissionEngine:
    """Executes business objectives end-to-end with economic intelligence and verification."""

    def __init__(
        self,
        *,
        verify_identity: Callable[[str, str, str], bool],
        economic_engine: EconomicIntelligenceEngine | None = None,
        routing_strategy: RoutingStrategy = "outcome_driven",
        worker: StepWorkerCallable = default_deterministic_worker,
        verifier: IndependentOutcomeVerifier | None = None,
        ledger_db_path: str | Path | None = None,
    ) -> None:
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou identity verifier callable required")
        self.verify_identity = verify_identity
        self.economic_engine = economic_engine or EconomicIntelligenceEngine()
        self.routing_strategy: RoutingStrategy = routing_strategy
        self.worker = worker
        self.verifier = verifier or IndependentOutcomeVerifier()
        self.ledger_db_path = str(ledger_db_path) if ledger_db_path else None
        self._idempotency_ledger: dict[str, StepAttemptReceipt] = {}
        if self.ledger_db_path:
            self._init_durable_ledger()

    def _init_durable_ledger(self) -> None:
        assert self.ledger_db_path is not None
        Path(self.ledger_db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.ledger_db_path, timeout=10) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS step_idempotency_ledger (
                    idem_key TEXT PRIMARY KEY,
                    receipt_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS mission_checkpoints (
                    checkpoint_key TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    objective_id TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _checkpoint_key(provider_id: str, tenant_id: str, company_id: str, objective_id: str) -> str:
        return f"{provider_id}:{tenant_id}:{company_id}:{objective_id}"

    def save_durable_checkpoint(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        company_id: str,
        objective_id: str,
        checkpoint_state: Mapping[str, Any],
    ) -> None:
        if not self.ledger_db_path:
            return
        serializable = dict(checkpoint_state)
        raw_receipts = serializable.get("step_receipts", ())
        serializable["step_receipts"] = [
            asdict(r) if isinstance(r, StepAttemptReceipt) else r for r in raw_receipts
        ]
        payload_json = json.dumps(serializable, sort_keys=True, default=str)
        ck_key = self._checkpoint_key(provider_id, tenant_id, company_id, objective_id)
        with sqlite3.connect(self.ledger_db_path, timeout=10) as db:
            db.execute(
                """
                INSERT OR REPLACE INTO mission_checkpoints(
                    checkpoint_key, tenant_id, company_id, objective_id, checkpoint_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ck_key, tenant_id, company_id, objective_id, payload_json, time.time()),
            )

    def load_durable_checkpoint(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        company_id: str,
        objective_id: str,
    ) -> dict[str, Any] | None:
        if not self.ledger_db_path:
            return None
        ck_key = self._checkpoint_key(provider_id, tenant_id, company_id, objective_id)
        with sqlite3.connect(self.ledger_db_path, timeout=10) as db:
            row = db.execute(
                "SELECT checkpoint_json FROM mission_checkpoints WHERE checkpoint_key=?",
                (ck_key,),
            ).fetchone()
        if not row:
            return None
        loaded = json.loads(row[0])
        if not isinstance(loaded, dict):
            return None
        reconstructed_receipts: list[StepAttemptReceipt] = []
        for raw_rec in loaded.get("step_receipts", ()):
            rec_obj = self._reconstruct_receipt(raw_rec)
            if rec_obj is not None:
                reconstructed_receipts.append(rec_obj)
        loaded["step_receipts"] = reconstructed_receipts
        return loaded

    def _load_durable_receipt(self, idem_key: str) -> StepAttemptReceipt | None:
        if idem_key in self._idempotency_ledger:
            return self._idempotency_ledger[idem_key]
        if not self.ledger_db_path:
            return None
        with sqlite3.connect(self.ledger_db_path, timeout=10) as db:
            row = db.execute(
                "SELECT receipt_json FROM step_idempotency_ledger WHERE idem_key=?",
                (idem_key,),
            ).fetchone()
        if not row:
            return None
        reconstructed = self._reconstruct_receipt(json.loads(row[0]))
        if reconstructed is not None:
            self._idempotency_ledger[idem_key] = reconstructed
        return reconstructed

    def _save_durable_receipt(self, idem_key: str, receipt: StepAttemptReceipt) -> None:
        self._idempotency_ledger[idem_key] = receipt
        if not self.ledger_db_path:
            return
        serialized = json.dumps(asdict(receipt), sort_keys=True, default=str)
        with sqlite3.connect(self.ledger_db_path, timeout=10) as db:
            db.execute(
                "INSERT OR REPLACE INTO step_idempotency_ledger(idem_key, receipt_json) VALUES (?, ?)",
                (idem_key, serialized),
            )

    @staticmethod
    def _reconstruct_receipt(raw_rec: Any) -> StepAttemptReceipt | None:
        if isinstance(raw_rec, StepAttemptReceipt):
            return raw_rec
        if not isinstance(raw_rec, Mapping):
            return None
        raw_cost = raw_rec.get("cost", {})
        cost_obj = (
            raw_cost
            if isinstance(raw_cost, CostBreakdown)
            else CostBreakdown(
                token_api_cost_minor=float(raw_cost.get("token_api_cost_minor", 0.0)),
                compute_infra_cost_minor=float(raw_cost.get("compute_infra_cost_minor", 0.0)),
                time_cost_minor=float(raw_cost.get("time_cost_minor", 0.0)),
                opportunity_cost_minor=float(raw_cost.get("opportunity_cost_minor", 0.0)),
                human_supervision_cost_minor=float(raw_cost.get("human_supervision_cost_minor", 0.0)),
                recovery_cost_minor=float(raw_cost.get("recovery_cost_minor", 0.0)),
                elapsed_seconds=float(raw_cost.get("elapsed_seconds", 0.0)),
                input_tokens=int(raw_cost.get("input_tokens", 0)),
                output_tokens=int(raw_cost.get("output_tokens", 0)),
                model_calls=int(raw_cost.get("model_calls", 1)),
                human_interventions=int(raw_cost.get("human_interventions", 0)),
                provider_reported_cost_usd=raw_cost.get("provider_reported_cost_usd"),
                cost_source=str(raw_cost.get("cost_source", "modeled_rate_card")),
                telemetry_mode=raw_cost.get("telemetry_mode", "estimated_prior"),
                tool_calls_count=int(raw_cost.get("tool_calls_count", 0)),
                provider_id=raw_cost.get("provider_id"),
                resolved_model_id=raw_cost.get("resolved_model_id"),
            )
        )
        return StepAttemptReceipt(
            step_id=str(raw_rec["step_id"]),
            attempt=int(raw_rec["attempt"]),
            model_id=str(raw_rec["model_id"]),
            tools_bound=tuple(raw_rec.get("tools_bound", ())),
            status=raw_rec["status"],
            output=raw_rec.get("output"),
            error_reason=raw_rec.get("error_reason"),
            cost=cost_obj,
            ev_decision_digest=str(raw_rec.get("ev_decision_digest", "")),
            receipt_digest=str(raw_rec.get("receipt_digest", "")),
        )

    def _build_attempt_cost(
        self,
        *,
        selected_model: str,
        worker_res: StepWorkerResult,
        policy: EconomicPolicy,
    ) -> CostBreakdown:
        profile = self.economic_engine.models[selected_model]
        actual_in = max(0, int(worker_res.input_tokens))
        actual_out = max(0, int(worker_res.output_tokens))
        actual_lat = max(0.001, float(worker_res.latency_sec))

        if worker_res.status == "routing_error" and actual_in == 0 and actual_out == 0:
            tok_cost = 0.0
        elif (
            worker_res.provider_reported_cost_usd is not None
            and worker_res.provider_reported_cost_usd > 0
        ):
            tok_cost = float(worker_res.provider_reported_cost_usd) * policy.usd_to_minor_rate
        else:
            tok_cost = (
                (actual_in / 1000.0) * profile.input_cost_per_1k_minor
                + (actual_out / 1000.0) * profile.output_cost_per_1k_minor
            )
        comp_cost = actual_lat * profile.compute_cost_per_sec_minor
        mins = actual_lat / 60.0
        t_cost = mins * policy.time_cost_per_min_minor
        opp_cost = mins * policy.opportunity_cost_per_min_minor
        return CostBreakdown(
            token_api_cost_minor=round(tok_cost, 4),
            compute_infra_cost_minor=round(comp_cost, 4),
            time_cost_minor=round(t_cost, 4),
            opportunity_cost_minor=round(opp_cost, 4),
            human_supervision_cost_minor=0.0,
            recovery_cost_minor=0.0,
            elapsed_seconds=round(actual_lat, 3),
            input_tokens=actual_in,
            output_tokens=actual_out,
            model_calls=max(1, int(worker_res.api_calls)),
            human_interventions=0,
            provider_reported_cost_usd=worker_res.provider_reported_cost_usd,
            cost_source=worker_res.cost_source,
            telemetry_mode=worker_res.telemetry_mode,
            tool_calls_count=len(worker_res.tool_calls),
            provider_id=worker_res.provider_id or profile.provider_id,
            resolved_model_id=worker_res.resolved_model_id or profile.runtime_model_id or selected_model,
        )

    def _invoke_worker_with_deadline(
        self,
        *,
        step: WorkStep,
        selected_model: str,
        attempt: int,
        worker_ctx: dict[str, Any],
        repair_hints: tuple[str, ...],
        effective_deadline_sec: float,
    ) -> tuple[StepWorkerResult, bool]:
        """Invoke step worker under a strict per-step deadline.

        Returns `(worker_result, deadline_exceeded)`. Never allows a single step
        or hanging provider call to consume the full mission SLA.
        """
        deadline = max(0.02, float(effective_deadline_sec))
        worker_ctx["step_deadline_seconds"] = deadline
        t0 = time.monotonic()
        profile = self.economic_engine.models.get(selected_model)

        if threading.current_thread() is threading.main_thread() and hasattr(signal, "setitimer"):
            def _step_sigalrm(_signum: int, _frame: Any) -> None:
                raise TimeoutError(
                    f"STEP_DEADLINE_EXCEEDED:{step.step_id}:{selected_model}>{deadline:.2f}s"
                )

            prev_handler = signal.getsignal(signal.SIGALRM)
            prev_timer = signal.getitimer(signal.ITIMER_REAL)
            signal.signal(signal.SIGALRM, _step_sigalrm)
            signal.setitimer(signal.ITIMER_REAL, deadline + 0.5)
            try:
                worker_res = self.worker(
                    step,
                    selected_model,
                    attempt,
                    worker_ctx,
                    repair_hints,
                )
            except TimeoutError as exc:
                return (
                    StepWorkerResult(
                        status="runtime_error",
                        output=None,
                        input_tokens=0,
                        output_tokens=0,
                        latency_sec=round(deadline, 3),
                        error_message=str(exc),
                        cost_source="timeout_circuit_breaker",
                        telemetry_mode="measured_live",
                        provider_id=profile.provider_id if profile else None,
                        resolved_model_id=profile.runtime_model_id if profile else selected_model,
                        api_calls=1,
                    ),
                    True,
                )
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, prev_handler)
                if prev_timer[0] > 0:
                    rem = max(0.001, prev_timer[0] - (time.monotonic() - t0))
                    signal.setitimer(signal.ITIMER_REAL, rem, prev_timer[1])
        else:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(
                self.worker,
                step,
                selected_model,
                attempt,
                worker_ctx,
                repair_hints,
            )
            try:
                worker_res = future.result(timeout=deadline + 0.5)
            except concurrent.futures.TimeoutError:
                pool.shutdown(wait=False, cancel_futures=True)
                return (
                    StepWorkerResult(
                        status="runtime_error",
                        output=None,
                        input_tokens=0,
                        output_tokens=0,
                        latency_sec=round(deadline, 3),
                        error_message=f"STEP_DEADLINE_EXCEEDED:{step.step_id}:{selected_model}>{deadline:.2f}s",
                        cost_source="timeout_circuit_breaker",
                        telemetry_mode="measured_live",
                        provider_id=profile.provider_id if profile else None,
                        resolved_model_id=profile.runtime_model_id if profile else selected_model,
                        api_calls=1,
                    ),
                    True,
                )
            finally:
                pool.shutdown(wait=False)

        wall_elapsed = time.monotonic() - t0
        err_msg = str(worker_res.error_message or "")
        if (
            "STEP_DEADLINE_EXCEEDED" in err_msg
            or "HERMES_WALL_CLOCK_TIMEOUT" in err_msg
            or float(worker_res.latency_sec) > deadline
            or wall_elapsed > deadline + 0.5
        ):
            capped_latency = round(min(float(worker_res.latency_sec), deadline), 3)
            return (
                StepWorkerResult(
                    status="runtime_error",
                    output=None,
                    input_tokens=worker_res.input_tokens,
                    output_tokens=worker_res.output_tokens,
                    latency_sec=capped_latency,
                    error_message=(
                        err_msg
                        if "STEP_DEADLINE_EXCEEDED" in err_msg
                        else f"STEP_DEADLINE_EXCEEDED:{step.step_id}:{selected_model}:{worker_res.latency_sec:.2f}s>{deadline:.2f}s"
                    ),
                    provider_reported_cost_usd=worker_res.provider_reported_cost_usd,
                    cost_source=worker_res.cost_source,
                    telemetry_mode=worker_res.telemetry_mode,
                    provider_id=worker_res.provider_id,
                    resolved_model_id=worker_res.resolved_model_id,
                    tool_calls=worker_res.tool_calls,
                    api_calls=worker_res.api_calls,
                ),
                True,
            )
        return worker_res, False

    def execute_objective(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        identity: str,
        objective: BusinessObjective,
        memory_lessons: tuple[str, ...] = (),
        checkpoint: Mapping[str, Any] | None = None,
        resume_from_ledger: bool = False,
        interrupt_after_steps: int | None = None,
    ) -> MissionExecutionReport:
        """Run or resume an autonomous mission under strict JustYou & EV governance."""
        if not provider_id or not tenant_id or not identity:
            raise PermissionError("JUSTYOU_SCOPE_REQUIRED")
        if self.verify_identity(provider_id, tenant_id, identity) is not True:
            raise PermissionError("JUSTYOU_IDENTITY_NOT_VERIFIED")

        # Align engine policy with the objective's economic policy
        self.economic_engine.policy = objective.policy
        router = ModelRouter(self.economic_engine, strategy=self.routing_strategy)
        steps = ObjectiveDecomposer.decompose(objective)

        if checkpoint is None and resume_from_ledger and self.ledger_db_path:
            checkpoint = self.load_durable_checkpoint(
                provider_id=provider_id,
                tenant_id=tenant_id,
                company_id=objective.company_id,
                objective_id=objective.objective_id,
            )

        # Restore from checkpoint if resuming an interrupted execution
        completed_outputs: dict[str, Mapping[str, Any]] = {}
        step_receipts: list[StepAttemptReceipt] = []
        ev_decisions: list[dict] = []
        spent_direct = 0.0
        spent_total_economic = 0.0
        recovery_spend = 0.0
        elapsed_sec = 0.0
        total_calls = 0
        total_in_tokens = 0
        total_out_tokens = 0
        failures_detected = 0
        autonomous_recoveries = 0
        duplicates_prevented = 0
        human_interventions = 0
        unavailable_models: list[str] = []

        if checkpoint is not None:
            if (
                checkpoint.get("tenant_id") != tenant_id
                or checkpoint.get("company_id") != objective.company_id
                or checkpoint.get("objective_id") != objective.objective_id
            ):
                raise PermissionError("CHECKPOINT_SCOPE_MISMATCH")
            completed_outputs = dict(checkpoint.get("completed_outputs", {}))
            spent_direct = float(checkpoint.get("spent_direct", 0.0))
            spent_total_economic = float(checkpoint.get("spent_total_economic", 0.0))
            recovery_spend = float(checkpoint.get("recovery_spend", 0.0))
            elapsed_sec = float(checkpoint.get("elapsed_sec", 0.0))
            total_calls = int(checkpoint.get("total_calls", 0))
            total_in_tokens = int(checkpoint.get("total_in_tokens", 0))
            total_out_tokens = int(checkpoint.get("total_out_tokens", 0))
            failures_detected = int(checkpoint.get("failures_detected", 0))
            autonomous_recoveries = int(checkpoint.get("autonomous_recoveries", 0))
            duplicates_prevented = int(checkpoint.get("duplicates_prevented", 0))
            unavailable_models = list(checkpoint.get("unavailable_models", ()))
            for raw_rec in checkpoint.get("step_receipts", ()):
                rec_obj = self._reconstruct_receipt(raw_rec)
                if rec_obj is not None:
                    step_receipts.append(rec_obj)

        def _snapshot_checkpoint() -> dict[str, Any]:
            state = {
                "tenant_id": tenant_id,
                "company_id": objective.company_id,
                "objective_id": objective.objective_id,
                "completed_outputs": dict(completed_outputs),
                "step_receipts": list(step_receipts),
                "spent_direct": spent_direct,
                "spent_total_economic": spent_total_economic,
                "recovery_spend": recovery_spend,
                "elapsed_sec": elapsed_sec,
                "total_calls": total_calls,
                "total_in_tokens": total_in_tokens,
                "total_out_tokens": total_out_tokens,
                "failures_detected": failures_detected,
                "autonomous_recoveries": autonomous_recoveries,
                "duplicates_prevented": duplicates_prevented,
                "unavailable_models": list(unavailable_models),
            }
            self.save_durable_checkpoint(
                provider_id=provider_id,
                tenant_id=tenant_id,
                company_id=objective.company_id,
                objective_id=objective.objective_id,
                checkpoint_state=state,
            )
            return state

        stop_status: Literal[
            "VERIFIED_COMPLETE",
            "STOPPED_NEGATIVE_EV",
            "STOPPED_BUDGET_EXCEEDED",
            "STOPPED_SLA_EXCEEDED",
            "STOPPED_UNVERIFIED_OUTCOME",
            "INTERRUPTED_CHECKPOINTED",
        ] | None = None
        stop_reason = ""
        steps_executed_this_run = 0

        for step in steps:
            if step.step_id in completed_outputs:
                continue

            # Check idempotency ledger (in-memory + durable SQLite) for already-completed step in this scope
            idem_key = f"{provider_id}:{tenant_id}:{objective.company_id}:{objective.objective_id}:{step.step_id}"
            cached = self._load_durable_receipt(idem_key)
            if cached is not None and cached.status == "completed" and cached.output is not None:
                duplicates_prevented += 1
                completed_outputs[step.step_id] = cached.output
                step_receipts.append(cached)
                _snapshot_checkpoint()
                continue

            attempt = 1
            failed_models: list[str] = []
            repair_hints: list[str] = []
            step_succeeded = False

            while attempt <= objective.policy.max_step_attempts:
                # Marginal value at stake for this step is proportional to step weight on attempt 1,
                # and escalates on recovery attempts while capped by remaining net target value.
                if attempt == 1:
                    marginal_value = float(objective.target_value_minor) * step.marginal_value_share
                else:
                    share = max(step.marginal_value_share, 0.65)
                    remaining_value = max(0.0, float(objective.target_value_minor) - spent_direct)
                    marginal_value = min(float(objective.target_value_minor) * share, remaining_value)

                selected_model, decision = router.select_model(
                    task_kind=step.task_kind,
                    marginal_value_minor=marginal_value,
                    spent_cost_minor=spent_direct,
                    elapsed_seconds=elapsed_sec,
                    attempt=attempt,
                    complexity=step.complexity,
                    estimated_input_tokens=step.estimated_input_tokens,
                    estimated_output_tokens=step.estimated_output_tokens,
                    failed_models=tuple(failed_models),
                    unavailable_models=tuple(unavailable_models),
                )
                ev_decisions.append({
                    "step_id": step.step_id,
                    "attempt": attempt,
                    **decision.as_dict(),
                })

                if not decision.economically_justified or selected_model is None:
                    if decision.verdict == "STOP_BUDGET_EXCEEDED":
                        stop_status = "STOPPED_BUDGET_EXCEEDED"
                    elif decision.verdict == "STOP_SLA_EXCEEDED":
                        stop_status = "STOPPED_SLA_EXCEEDED"
                    else:
                        stop_status = "STOPPED_NEGATIVE_EV"
                    stop_reason = decision.rationale
                    break

                # Compute per-step wall-clock deadline bounded by remaining mission SLA
                remaining_sla = max(0.1, float(objective.policy.sla_seconds) - elapsed_sec)
                policy_step_deadline = float(
                    getattr(objective.policy, "step_deadline_seconds", 35.0) or 35.0
                )
                step_deadline = float(step.step_deadline_seconds or policy_step_deadline)
                effective_deadline = min(step_deadline, remaining_sla)

                # Execute the step with the chosen model and role-scoped tools
                tools_bound = ROLE_TOOLSETS[step.role]
                worker_ctx = {
                    "provider_id": provider_id,
                    "tenant_id": tenant_id,
                    "company_id": objective.company_id,
                    "objective_id": objective.objective_id,
                    "objective_title": objective.title,
                    "objective_description": objective.description,
                    "target_value_minor": objective.target_value_minor,
                    "currency": objective.currency,
                    "acceptance_criteria": objective.acceptance_criteria,
                    "required_deliverables": objective.required_deliverables,
                    "completed_outputs": completed_outputs,
                    "memory_lessons": memory_lessons,
                    "remaining_sla_seconds": remaining_sla,
                    "step_deadline_seconds": effective_deadline,
                }
                worker_res, deadline_exceeded = self._invoke_worker_with_deadline(
                    step=step,
                    selected_model=selected_model,
                    attempt=attempt,
                    worker_ctx=worker_ctx,
                    repair_hints=tuple(repair_hints),
                    effective_deadline_sec=effective_deadline,
                )

                attempt_cost = self._build_attempt_cost(
                    selected_model=selected_model,
                    worker_res=worker_res,
                    policy=objective.policy,
                )

                spent_direct = round(spent_direct + attempt_cost.direct_cost_minor, 4)
                spent_total_economic = round(spent_total_economic + attempt_cost.total_economic_cost_minor, 4)
                if attempt > 1:
                    recovery_spend = round(recovery_spend + attempt_cost.total_economic_cost_minor, 4)
                elapsed_sec = round(elapsed_sec + attempt_cost.elapsed_seconds, 3)
                total_calls += attempt_cost.model_calls
                total_in_tokens += attempt_cost.input_tokens
                total_out_tokens += attempt_cost.output_tokens

                # Validate step output before accepting
                validation_error = self._validate_step_output(step, worker_res, objective)
                if validation_error is None and not deadline_exceeded:
                    receipt = self._make_step_receipt(
                        step_id=step.step_id,
                        attempt=attempt,
                        model_id=selected_model,
                        tools_bound=tools_bound,
                        status="completed",
                        output=worker_res.output,
                        error_reason=None,
                        cost=attempt_cost,
                        ev_digest=decision.digest,
                    )
                    step_receipts.append(receipt)
                    assert worker_res.output is not None
                    completed_outputs[step.step_id] = worker_res.output
                    self._save_durable_receipt(idem_key, receipt)
                    _snapshot_checkpoint()
                    self.economic_engine.record_observation(
                        model_id=selected_model,
                        task_kind=step.task_kind,
                        independently_verified_success=True,
                        input_tokens=attempt_cost.input_tokens,
                        output_tokens=attempt_cost.output_tokens,
                        latency_sec=attempt_cost.elapsed_seconds,
                    )
                    if attempt > 1:
                        autonomous_recoveries += 1
                    step_succeeded = True
                    break

                # Failure detected! Record failure, persist checkpoint, and prepare autonomous recovery
                failures_detected += 1
                failure_kind: Literal["routing_error", "runtime_error", "invalid_output"]
                if worker_res.status == "routing_error":
                    failure_kind = "routing_error"
                    if selected_model not in unavailable_models:
                        unavailable_models.append(selected_model)
                elif deadline_exceeded:
                    failure_kind = "runtime_error"
                    if selected_model not in unavailable_models:
                        unavailable_models.append(selected_model)
                    failed_models.append(selected_model)
                elif worker_res.status == "runtime_error":
                    failure_kind = "runtime_error"
                    failed_models.append(selected_model)
                else:
                    failure_kind = "invalid_output"
                    failed_models.append(selected_model)
                    self.economic_engine.record_observation(
                        model_id=selected_model,
                        task_kind=step.task_kind,
                        independently_verified_success=False,
                        input_tokens=attempt_cost.input_tokens,
                        output_tokens=attempt_cost.output_tokens,
                        latency_sec=attempt_cost.elapsed_seconds,
                    )

                repair_hints.append(f"attempt-{attempt}-{selected_model}:{validation_error}")
                receipt = self._make_step_receipt(
                    step_id=step.step_id,
                    attempt=attempt,
                    model_id=selected_model,
                    tools_bound=tools_bound,
                    status=failure_kind,
                    output=worker_res.output,
                    error_reason=validation_error,
                    cost=attempt_cost,
                    ev_digest=decision.digest,
                )
                step_receipts.append(receipt)
                _snapshot_checkpoint()
                attempt += 1

            if not step_succeeded:
                if stop_status is None:
                    stop_status = "STOPPED_NEGATIVE_EV"
                    stop_reason = (
                        f"Step {step.step_id} exhausted recovery attempts ({objective.policy.max_step_attempts}) "
                        f"without a verified output; halting fail-closed."
                    )
                break

            steps_executed_this_run += 1
            if interrupt_after_steps is not None and steps_executed_this_run >= interrupt_after_steps:
                if len(completed_outputs) < len(steps):
                    stop_status = "INTERRUPTED_CHECKPOINTED"
                    stop_reason = f"Execution interrupted after {steps_executed_this_run} step(s); checkpoint saved."
                    break

        # Extract final deliverables from build step (or merged outputs)
        deliverables: dict[str, Any] = {}
        if "step-3-build" in completed_outputs:
            deliverables.update(completed_outputs["step-3-build"])
        else:
            for out_map in completed_outputs.values():
                for k in objective.required_deliverables:
                    if k in out_map:
                        deliverables[k] = out_map[k]

        # Run independent outcome verification
        verification = self.verifier.verify(
            objective,
            deliverables,
            tuple(step_receipts),
            tenant_id=tenant_id,
            identity=identity,
        )

        # If all DAG steps ran but independent verification failed, try one targeted repair if EV > 0
        if (
            stop_status is None
            and not verification.independently_verified
            and "step-3-build" in completed_outputs
        ):
            failures_detected += 1
            build_step = next((s for s in steps if s.step_id == "step-3-build"), steps[-1])
            prior_build_rec = next(
                (r for r in reversed(step_receipts) if r.step_id == "step-3-build"),
                step_receipts[-1] if step_receipts else None,
            )
            remaining_val = max(0.0, float(objective.target_value_minor) - spent_direct)
            repair_model, repair_decision = router.select_model(
                task_kind="implementation",
                marginal_value_minor=remaining_val,
                spent_cost_minor=spent_direct,
                elapsed_seconds=elapsed_sec,
                attempt=2,
                complexity="high",
                estimated_input_tokens=build_step.estimated_input_tokens,
                estimated_output_tokens=build_step.estimated_output_tokens,
                failed_models=(prior_build_rec.model_id,) if prior_build_rec else (),
                unavailable_models=tuple(unavailable_models),
            )
            ev_decisions.append({
                "step_id": "independent-verification-repair",
                "attempt": 2,
                **repair_decision.as_dict(),
            })
            if repair_decision.economically_justified and repair_model is not None:
                worker_ctx = {
                    "provider_id": provider_id,
                    "tenant_id": tenant_id,
                    "company_id": objective.company_id,
                    "objective_id": objective.objective_id,
                    "objective_title": objective.title,
                    "objective_description": objective.description,
                    "target_value_minor": objective.target_value_minor,
                    "currency": objective.currency,
                    "acceptance_criteria": objective.acceptance_criteria,
                    "required_deliverables": objective.required_deliverables,
                    "completed_outputs": completed_outputs,
                    "memory_lessons": memory_lessons,
                }
                repair_res = self.worker(
                    build_step,
                    repair_model,
                    2,
                    worker_ctx,
                    verification.checks_failed,
                )
                r_cost = self._build_attempt_cost(
                    selected_model=repair_model,
                    worker_res=repair_res,
                    policy=objective.policy,
                )
                spent_direct = round(spent_direct + r_cost.direct_cost_minor, 4)
                spent_total_economic = round(spent_total_economic + r_cost.total_economic_cost_minor, 4)
                recovery_spend = round(recovery_spend + r_cost.total_economic_cost_minor, 4)
                elapsed_sec = round(elapsed_sec + r_cost.elapsed_seconds, 3)
                total_calls += r_cost.model_calls
                total_in_tokens += r_cost.input_tokens
                total_out_tokens += r_cost.output_tokens
                if self._validate_step_output(build_step, repair_res, objective) is None and repair_res.output:
                    completed_outputs["step-3-build"] = repair_res.output
                    deliverables.update(repair_res.output)
                    receipt = self._make_step_receipt(
                        step_id="step-3-build",
                        attempt=2,
                        model_id=repair_model,
                        tools_bound=ROLE_TOOLSETS[build_step.role],
                        status="completed",
                        output=repair_res.output,
                        error_reason=None,
                        cost=r_cost,
                        ev_digest=repair_decision.digest,
                    )
                    step_receipts.append(receipt)
                    critique_step = next((s for s in steps if s.step_id == "step-4-critique"), None)
                    if critique_step is not None and "step-4-critique" in completed_outputs:
                        critique_res = self.worker(
                            critique_step,
                            repair_model,
                            2,
                            worker_ctx,
                            (),
                        )
                        c_cost = self._build_attempt_cost(
                            selected_model=repair_model,
                            worker_res=critique_res,
                            policy=objective.policy,
                        )
                        spent_direct = round(spent_direct + c_cost.direct_cost_minor, 4)
                        spent_total_economic = round(spent_total_economic + c_cost.total_economic_cost_minor, 4)
                        recovery_spend = round(recovery_spend + c_cost.total_economic_cost_minor, 4)
                        elapsed_sec = round(elapsed_sec + c_cost.elapsed_seconds, 3)
                        total_calls += c_cost.model_calls
                        total_in_tokens += c_cost.input_tokens
                        total_out_tokens += c_cost.output_tokens
                        if self._validate_step_output(critique_step, critique_res, objective) is None and critique_res.output:
                            completed_outputs["step-4-critique"] = critique_res.output
                            step_receipts.append(
                                self._make_step_receipt(
                                    step_id="step-4-critique",
                                    attempt=2,
                                    model_id=repair_model,
                                    tools_bound=ROLE_TOOLSETS["skeptic"],
                                    status="completed",
                                    output=critique_res.output,
                                    error_reason=None,
                                    cost=c_cost,
                                    ev_digest=repair_decision.digest,
                                )
                            )
                    verification = self.verifier.verify(
                        objective,
                        deliverables,
                        tuple(step_receipts),
                        tenant_id=tenant_id,
                        identity=identity,
                    )
                    if verification.independently_verified:
                        autonomous_recoveries += 1

        if stop_status is None:
            if verification.independently_verified:
                stop_status = "VERIFIED_COMPLETE"
                first_catalog_model = next(iter(self.economic_engine.models.keys()))
                post_check = self.economic_engine.evaluate_next_action(
                    task_kind="verification",
                    candidate_model_id=first_catalog_model,
                    marginal_value_minor=0.0,
                    spent_cost_minor=spent_direct,
                    elapsed_seconds=elapsed_sec,
                    objective_already_verified=True,
                )
                ev_decisions.append({
                    "step_id": "post-completion-gate",
                    "attempt": 1,
                    **post_check.as_dict(),
                })
                stop_reason = post_check.rationale
            else:
                stop_status = "STOPPED_UNVERIFIED_OUTCOME"
                stop_reason = (
                    "Execution finished but independent outcome verification failed: "
                    + ", ".join(verification.checks_failed)
                )

        verified_value = objective.target_value_minor if verification.independently_verified else 0
        net_value = round(float(verified_value) - spent_total_economic, 4)
        roi = round((net_value / spent_total_economic) if spent_total_economic > 0 else 0.0, 4)

        # Aggregate measured vs modeled breakdown across all step receipts
        measured_usd_list = [
            r.cost.provider_reported_cost_usd
            for r in step_receipts
            if r.cost.provider_reported_cost_usd is not None
        ]
        providers_used = sorted({r.cost.provider_id for r in step_receipts if r.cost.provider_id})
        models_used = sorted({r.cost.resolved_model_id or r.model_id for r in step_receipts})
        telemetry_modes = sorted({r.cost.telemetry_mode for r in step_receipts})
        total_tool_calls = sum(r.cost.tool_calls_count for r in step_receipts)

        measured_telemetry = {
            "telemetry_modes": telemetry_modes,
            "is_live_measured": "measured_live" in telemetry_modes,
            "total_input_tokens": total_in_tokens,
            "total_output_tokens": total_out_tokens,
            "total_tokens": total_in_tokens + total_out_tokens,
            "total_model_calls": total_calls,
            "total_tool_calls": total_tool_calls,
            "measured_elapsed_seconds": elapsed_sec,
            "provider_reported_cost_usd_total": round(sum(measured_usd_list), 6) if measured_usd_list else None,
            "providers_used": providers_used,
            "models_used": models_used,
            "failures_detected": failures_detected,
            "autonomous_recoveries": autonomous_recoveries,
            "duplicate_actions_prevented": duplicates_prevented,
            "human_interventions_required": human_interventions,
        }
        modeled_economics = {
            "currency": objective.currency,
            "usd_to_minor_rate": objective.policy.usd_to_minor_rate,
            "token_api_cost_minor": round(sum(r.cost.token_api_cost_minor for r in step_receipts), 4),
            "compute_infra_cost_minor": round(sum(r.cost.compute_infra_cost_minor for r in step_receipts), 4),
            "time_cost_minor": round(sum(r.cost.time_cost_minor for r in step_receipts), 4),
            "opportunity_cost_minor": round(sum(r.cost.opportunity_cost_minor for r in step_receipts), 4),
            "direct_cost_minor": spent_direct,
            "total_economic_cost_minor": spent_total_economic,
            "recovery_spend_minor": recovery_spend,
            "target_value_minor": objective.target_value_minor,
            "verified_value_minor": verified_value,
            "net_economic_value_minor": net_value,
            "roi_ratio": roi,
        }

        checkpoint_state = _snapshot_checkpoint()

        produced_artifact = bool(deliverables) and all(
            deliverables.get(k) not in (None, "", [], {})
            for k in objective.required_deliverables
        )
        verified_artifact = bool(
            produced_artifact
            and verification.independently_verified
            and self.verifier.verify_receipt_authenticity(
                verification,
                deliverables=deliverables,
                expected_tenant_id=tenant_id,
                expected_company_id=objective.company_id,
                expected_objective_id=objective.objective_id,
            )
        )
        measured_business_result = bool(
            verified_artifact
            and stop_status == "VERIFIED_COMPLETE"
            and verified_value > 0
            and net_value > 0
        )
        if measured_business_result:
            comp_stage: CompletionStage = "measured_business_result"
            comp_summary = (
                f"Independently verified deliverables with positive net economic value ({net_value} {objective.currency} minor); "
                "external customer effects remain gated on explicit channel authorization."
            )
        elif verified_artifact:
            comp_stage = "verified_artifact"
            comp_summary = "Independently verified artifact; net economic outcome is non-positive."
        elif produced_artifact:
            comp_stage = "produced_artifact"
            comp_summary = (
                "Worker produced candidate deliverables, but independent verification did NOT pass; "
                "self-reported output is never treated as completion."
            )
        else:
            comp_stage = "none"
            comp_summary = "No complete deliverable artifact produced."

        completion_semantics = CompletionSemanticsReport(
            produced_artifact=produced_artifact,
            verified_artifact=verified_artifact,
            authorized_external_effect=False,
            measured_business_result=measured_business_result,
            stage=comp_stage,
            external_effect_receipt_digest=None,
            summary=comp_summary,
        )

        summary_payload = {
            "objective_id": objective.objective_id,
            "company_id": objective.company_id,
            "tenant_id": tenant_id,
            "identity": identity,
            "status": stop_status,
            "independently_verified": verification.independently_verified,
            "verified_value_minor": verified_value,
            "total_economic_cost_minor": spent_total_economic,
            "net_economic_value_minor": net_value,
            "verification_digest": verification.evidence_digest,
            "verifier_seal": verification.verifier_seal,
        }
        report_digest = hashlib.sha256(
            json.dumps(summary_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return MissionExecutionReport(
            objective_id=objective.objective_id,
            company_id=objective.company_id,
            tenant_id=tenant_id,
            identity=identity,
            routing_strategy=self.routing_strategy,
            status=stop_status,
            independently_verified=verification.independently_verified,
            target_value_minor=objective.target_value_minor,
            verified_value_minor=verified_value,
            direct_cost_minor=spent_direct,
            total_economic_cost_minor=spent_total_economic,
            recovery_spend_minor=recovery_spend,
            net_economic_value_minor=net_value,
            roi_ratio=roi,
            elapsed_seconds=elapsed_sec,
            total_model_calls=total_calls,
            total_input_tokens=total_in_tokens,
            total_output_tokens=total_out_tokens,
            failures_detected=failures_detected,
            autonomous_recoveries=autonomous_recoveries,
            duplicate_actions_prevented=duplicates_prevented,
            human_interventions_required=human_interventions,
            stop_reason=stop_reason,
            deliverables=deliverables,
            verification=verification,
            step_receipts=tuple(step_receipts),
            ev_decisions=tuple(ev_decisions),
            checkpoint_state=checkpoint_state,
            report_digest=report_digest,
            measured_telemetry=measured_telemetry,
            modeled_economics=modeled_economics,
            completion_semantics=completion_semantics,
        )

    @staticmethod
    def _validate_step_output(
        step: WorkStep,
        res: StepWorkerResult,
        objective: BusinessObjective | None = None,
    ) -> str | None:
        if res.status == "routing_error":
            return res.error_message or "MODEL_ROUTE_UNAVAILABLE"
        if res.status == "runtime_error":
            return res.error_message or "WORKER_RUNTIME_ERROR"
        if not isinstance(res.output, Mapping) or not res.output:
            return res.error_message or "OUTPUT_NOT_A_NONEMPTY_OBJECT"
        min_len = (
            int(objective.acceptance_criteria.get("min_deliverable_chars", 12))
            if objective is not None and step.step_id == "step-3-build"
            else 1
        )
        serialized_by_key: dict[str, str] = {}
        for key in step.required_output_keys:
            if key not in res.output or res.output[key] in (None, "", [], {}):
                return f"MISSING_REQUIRED_OUTPUT_KEY:{key}"
            raw_val = res.output[key]
            serialized = json.dumps(raw_val, sort_keys=True) if not isinstance(raw_val, str) else raw_val.strip()
            val_upper = serialized.upper()
            if any(tok in val_upper for tok in FORBIDDEN_PLACEHOLDERS):
                return f"FORBIDDEN_PLACEHOLDER_IN_KEY:{key}"
            if step.step_id == "step-3-build":
                if len(serialized) < min_len:
                    return f"DELIVERABLE_TOO_SHORT:{key}:{len(serialized)}<{min_len}"
                if any(marker in key.lower() for marker in QUANTITATIVE_KEY_MARKERS):
                    has_digit = any(ch.isdigit() for ch in serialized)
                    has_unit = bool(QUANTITATIVE_UNIT_PATTERN.search(serialized))
                    if not (has_digit and has_unit):
                        return f"MISSING_QUANTITATIVE_METRICS:{key}"
                serialized_by_key[key] = serialized
        if step.step_id == "step-3-build" and len(serialized_by_key) >= 2:
            keys_list = list(serialized_by_key.keys())
            for idx, k1 in enumerate(keys_list):
                s1 = " ".join(serialized_by_key[k1].lower().split())
                t1 = IndependentOutcomeVerifier._tokenize(s1)
                for k2 in keys_list[idx + 1:]:
                    s2 = " ".join(serialized_by_key[k2].lower().split())
                    if s1 == s2:
                        return f"DUPLICATE_DELIVERABLES:{k1}:{k2}"
                    t2 = IndependentOutcomeVerifier._tokenize(s2)
                    if len(t1) >= 6 and len(t2) >= 6:
                        union = len(t1 | t2)
                        if union and (len(t1 & t2) / union) >= 0.90:
                            return f"REPETITIVE_DELIVERABLES:{k1}:{k2}"
        if step.step_id == "step-4-critique" and objective is not None:
            verified_keys = set(res.output.get("verified_keys") or ())
            if (
                res.output.get("audit_passed") is not True
                or not set(objective.required_deliverables).issubset(verified_keys)
            ):
                return "CRITIQUE_GATE_NOT_PASSED"
        return None

    @staticmethod
    def _make_step_receipt(
        *,
        step_id: str,
        attempt: int,
        model_id: str,
        tools_bound: tuple[str, ...],
        status: Literal[
            "completed",
            "routing_error",
            "runtime_error",
            "invalid_output",
            "aborted_economic",
        ],
        output: Mapping[str, Any] | None,
        error_reason: str | None,
        cost: CostBreakdown,
        ev_digest: str,
    ) -> StepAttemptReceipt:
        payload = {
            "step_id": step_id,
            "attempt": attempt,
            "model_id": model_id,
            "tools_bound": tools_bound,
            "status": status,
            "output": output,
            "error_reason": error_reason,
            "cost": cost.as_dict(),
            "ev_digest": ev_digest,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return StepAttemptReceipt(
            step_id=step_id,
            attempt=attempt,
            model_id=model_id,
            tools_bound=tools_bound,
            status=status,
            output=output,
            error_reason=error_reason,
            cost=cost,
            ev_decision_digest=ev_digest,
            receipt_digest=digest,
        )
