"""Economic intelligence, marginal EV decision engine, and multi-model routing.

Continuously evaluates whether the next dollar, minute, model call, or human
intervention is worth its expected contribution to a verified business objective.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Literal, Mapping

RoutingStrategy = Literal["static", "dynamic", "outcome_driven"]
EconomicVerdict = Literal[
    "PROCEED",
    "REROUTE_MODEL",
    "STOP_OBJECTIVE_COMPLETE",
    "STOP_NEGATIVE_EXPECTED_VALUE",
    "STOP_BUDGET_EXCEEDED",
    "STOP_SLA_EXCEEDED",
    "STOP_HUMAN_INTERVENTION_UNJUSTIFIED",
]


@dataclass(frozen=True)
class ModelProfile:
    """Economic and capability specification for a routable AI Bridge model."""

    model_id: str
    family: str
    tier: Literal["fast", "balanced", "frontier"]
    input_cost_per_1k_minor: float
    output_cost_per_1k_minor: float
    compute_cost_per_sec_minor: float
    mean_latency_sec: float
    base_Capabilities: Mapping[str, float] = field(default_factory=dict)
    provider_id: str = "google"
    runtime_model_id: str = ""

    def __post_init__(self) -> None:
        if not self.model_id or not isinstance(self.model_id, str):
            raise ValueError("MODEL_ID_REQUIRED")
        if self.tier not in ("fast", "balanced", "frontier"):
            raise ValueError("MODEL_TIER_INVALID")
        if (
            self.input_cost_per_1k_minor < 0
            or self.output_cost_per_1k_minor < 0
            or self.compute_cost_per_sec_minor < 0
            or self.mean_latency_sec <= 0
        ):
            raise ValueError("MODEL_ECONOMICS_INVALID")

    def prior_success_prob(self, task_kind: str) -> float:
        p = float(self.base_Capabilities.get(task_kind, self.base_Capabilities.get("default", 0.75)))
        return max(0.01, min(0.995, p))


DEFAULT_MODEL_CATALOG: tuple[ModelProfile, ...] = (
    ModelProfile(
        model_id="gemini-4-hydrogen",
        family="gemini-4",
        tier="fast",
        input_cost_per_1k_minor=2.0,
        output_cost_per_1k_minor=6.0,
        compute_cost_per_sec_minor=0.5,
        mean_latency_sec=2.5,
        base_Capabilities={
            "triage": 0.94,
            "extraction": 0.91,
            "verification": 0.89,
            "implementation": 0.78,
            "research": 0.82,
            "architecture": 0.52,
            "synthesis": 0.68,
            "default": 0.78,
        },
        provider_id="nous",
        runtime_model_id="upstage/solar-mini4:free",
    ),
    ModelProfile(
        model_id="gemini-4-argon",
        family="gemini-4",
        tier="balanced",
        input_cost_per_1k_minor=12.0,
        output_cost_per_1k_minor=36.0,
        compute_cost_per_sec_minor=1.5,
        mean_latency_sec=6.0,
        base_Capabilities={
            "triage": 0.97,
            "extraction": 0.96,
            "verification": 0.94,
            "implementation": 0.91,
            "research": 0.92,
            "architecture": 0.83,
            "synthesis": 0.89,
            "default": 0.90,
        },
        provider_id="gemini",
        runtime_model_id="gemini-3-flash-preview",
    ),
    ModelProfile(
        model_id="gemini-4-carbon",
        family="gemini-4",
        tier="frontier",
        input_cost_per_1k_minor=45.0,
        output_cost_per_1k_minor=135.0,
        compute_cost_per_sec_minor=4.0,
        mean_latency_sec=14.0,
        base_Capabilities={
            "triage": 0.985,
            "extraction": 0.98,
            "verification": 0.975,
            "implementation": 0.965,
            "research": 0.97,
            "architecture": 0.96,
            "synthesis": 0.97,
            "default": 0.965,
        },
        provider_id="alibaba",
        runtime_model_id="qwen3.8-max",
    ),
)


LIVE_HERMES_MODEL_CATALOG: tuple[ModelProfile, ...] = (
    ModelProfile(
        model_id="nous/upstage/solar-mini4:free",
        family="solar-mini4",
        tier="fast",
        input_cost_per_1k_minor=0.20,
        output_cost_per_1k_minor=0.60,
        compute_cost_per_sec_minor=0.25,
        mean_latency_sec=4.2,
        base_Capabilities={
            "triage": 0.94,
            "extraction": 0.91,
            "verification": 0.88,
            "implementation": 0.78,
            "research": 0.83,
            "architecture": 0.55,
            "synthesis": 0.70,
            "default": 0.80,
        },
        provider_id="nous",
        runtime_model_id="upstage/solar-mini4:free",
    ),
    ModelProfile(
        model_id="gemini/gemini-3.1-flash-lite-preview",
        family="gemini-3.1",
        tier="fast",
        input_cost_per_1k_minor=0.35,
        output_cost_per_1k_minor=1.40,
        compute_cost_per_sec_minor=0.30,
        mean_latency_sec=5.5,
        base_Capabilities={
            "triage": 0.95,
            "extraction": 0.93,
            "verification": 0.90,
            "implementation": 0.82,
            "research": 0.85,
            "architecture": 0.62,
            "synthesis": 0.75,
            "default": 0.83,
        },
        provider_id="gemini",
        runtime_model_id="gemini-3.1-flash-lite-preview",
    ),
    ModelProfile(
        model_id="nous/openai/gpt-5.4-mini",
        family="gpt-5.4",
        tier="balanced",
        input_cost_per_1k_minor=1.20,
        output_cost_per_1k_minor=4.80,
        compute_cost_per_sec_minor=0.55,
        mean_latency_sec=4.0,
        base_Capabilities={
            "triage": 0.97,
            "extraction": 0.96,
            "verification": 0.94,
            "implementation": 0.92,
            "research": 0.93,
            "architecture": 0.86,
            "synthesis": 0.90,
            "default": 0.91,
        },
        provider_id="nous",
        runtime_model_id="openai/gpt-5.4-mini",
    ),
    ModelProfile(
        model_id="gemini/gemini-3-flash-preview",
        family="gemini-3",
        tier="balanced",
        input_cost_per_1k_minor=1.65,
        output_cost_per_1k_minor=6.60,
        compute_cost_per_sec_minor=0.65,
        mean_latency_sec=5.8,
        base_Capabilities={
            "triage": 0.975,
            "extraction": 0.965,
            "verification": 0.95,
            "implementation": 0.93,
            "research": 0.94,
            "architecture": 0.88,
            "synthesis": 0.91,
            "default": 0.92,
        },
        provider_id="gemini",
        runtime_model_id="gemini-3-flash-preview",
    ),
    ModelProfile(
        model_id="alibaba/qwen3.5-plus",
        family="qwen-3.5",
        tier="balanced",
        input_cost_per_1k_minor=1.40,
        output_cost_per_1k_minor=4.20,
        compute_cost_per_sec_minor=0.60,
        mean_latency_sec=5.2,
        base_Capabilities={
            "triage": 0.975,
            "extraction": 0.97,
            "verification": 0.955,
            "implementation": 0.935,
            "research": 0.945,
            "architecture": 0.90,
            "synthesis": 0.925,
            "default": 0.93,
        },
        provider_id="alibaba",
        runtime_model_id="qwen3.5-plus",
    ),
    ModelProfile(
        model_id="alibaba/qwen3.8-max",
        family="qwen-3.8",
        tier="frontier",
        input_cost_per_1k_minor=6.50,
        output_cost_per_1k_minor=19.50,
        compute_cost_per_sec_minor=1.40,
        mean_latency_sec=8.5,
        base_Capabilities={
            "triage": 0.985,
            "extraction": 0.98,
            "verification": 0.975,
            "implementation": 0.965,
            "research": 0.97,
            "architecture": 0.96,
            "synthesis": 0.97,
            "default": 0.965,
        },
        provider_id="alibaba",
        runtime_model_id="qwen3.8-max",
    ),
)

LIVE_NOUS_ALIBABA_MODEL_CATALOG: tuple[ModelProfile, ...] = tuple(
    p for p in LIVE_HERMES_MODEL_CATALOG if p.provider_id in ("nous", "alibaba")
)


def filter_catalog_by_providers(
    models: tuple[ModelProfile, ...] | list[ModelProfile] | Mapping[str, ModelProfile] | None = None,
    *,
    allowed_providers: tuple[str, ...] | list[str] | set[str] | None = None,
    excluded_providers: tuple[str, ...] | list[str] | set[str] | None = None,
) -> tuple[ModelProfile, ...]:
    """Filter a ModelProfile catalog by allowed and/or excluded provider_ids, failing closed if empty."""
    normalized = normalize_model_catalog(models if models is not None else LIVE_HERMES_MODEL_CATALOG)
    allowed_set = {str(p).strip().lower() for p in allowed_providers if str(p).strip()} if allowed_providers else None
    excluded_set = {str(p).strip().lower() for p in (excluded_providers or ()) if str(p).strip()}
    filtered: list[ModelProfile] = []
    for profile in normalized.values():
        prov = (profile.provider_id or profile.model_id.split("/", 1)[0]).lower()
        if allowed_set is not None and prov not in allowed_set:
            continue
        if prov in excluded_set:
            continue
        filtered.append(profile)
    if not filtered:
        raise ValueError("FILTERED_MODEL_CATALOG_EMPTY")
    return tuple(filtered)


@dataclass(frozen=True)
class EconomicPolicy:
    """Company-scoped economic parameters for autonomous decision-making."""

    currency: str = "NOK"
    budget_ceiling_minor: int = 10_000
    sla_seconds: float = 300.0
    step_deadline_seconds: float = 35.0
    opportunity_cost_per_min_minor: float = 15.0
    time_cost_per_min_minor: float = 10.0
    human_intervention_cost_minor: int = 2_500
    human_intervention_latency_sec: float = 180.0
    min_expected_roi_ratio: float = 0.0
    max_step_attempts: int = 3
    usd_to_minor_rate: float = 1_100.0

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError("CURRENCY_INVALID")
        if self.budget_ceiling_minor < 0:
            raise ValueError("BUDGET_CEILING_INVALID")
        if self.sla_seconds <= 0:
            raise ValueError("SLA_SECONDS_INVALID")
        if self.step_deadline_seconds <= 0:
            raise ValueError("STEP_DEADLINE_SECONDS_INVALID")
        if (
            self.opportunity_cost_per_min_minor < 0
            or self.time_cost_per_min_minor < 0
            or self.human_intervention_cost_minor < 0
            or self.human_intervention_latency_sec < 0
            or self.usd_to_minor_rate <= 0
        ):
            raise ValueError("COST_RATES_INVALID")
        if self.max_step_attempts < 1 or self.max_step_attempts > 10:
            raise ValueError("MAX_STEP_ATTEMPTS_INVALID")


@dataclass(frozen=True)
class CostBreakdown:
    """Exact cost accounting separating measured telemetry from modeled economics."""

    token_api_cost_minor: float
    compute_infra_cost_minor: float
    time_cost_minor: float
    opportunity_cost_minor: float
    human_supervision_cost_minor: float
    recovery_cost_minor: float
    elapsed_seconds: float
    input_tokens: int
    output_tokens: int
    model_calls: int
    human_interventions: int
    provider_reported_cost_usd: float | None = None
    cost_source: str = "modeled_rate_card"
    telemetry_mode: Literal[
        "measured_live", "estimated_prior", "deterministic_simulation"
    ] = "estimated_prior"
    tool_calls_count: int = 0
    provider_id: str | None = None
    resolved_model_id: str | None = None

    @property
    def direct_cost_minor(self) -> float:
        return round(
            self.token_api_cost_minor
            + self.compute_infra_cost_minor
            + self.human_supervision_cost_minor,
            4,
        )

    @property
    def total_economic_cost_minor(self) -> float:
        return round(
            self.token_api_cost_minor
            + self.compute_infra_cost_minor
            + self.time_cost_minor
            + self.opportunity_cost_minor
            + self.human_supervision_cost_minor
            + self.recovery_cost_minor,
            4,
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["direct_cost_minor"] = self.direct_cost_minor
        data["total_economic_cost_minor"] = self.total_economic_cost_minor
        data["measured"] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "model_calls": self.model_calls,
            "tool_calls_count": self.tool_calls_count,
            "provider_reported_cost_usd": self.provider_reported_cost_usd,
            "cost_source": self.cost_source,
            "telemetry_mode": self.telemetry_mode,
            "provider_id": self.provider_id,
            "resolved_model_id": self.resolved_model_id,
        }
        data["estimated_modeled"] = {
            "token_api_cost_minor": self.token_api_cost_minor,
            "compute_infra_cost_minor": self.compute_infra_cost_minor,
            "time_cost_minor": self.time_cost_minor,
            "opportunity_cost_minor": self.opportunity_cost_minor,
            "human_supervision_cost_minor": self.human_supervision_cost_minor,
            "recovery_cost_minor": self.recovery_cost_minor,
            "direct_cost_minor": self.direct_cost_minor,
            "total_economic_cost_minor": self.total_economic_cost_minor,
        }
        return data


@dataclass(frozen=True)
class MarginalEVDecision:
    """Result of asking: Is the next call/minute/dollar/human intervention worth it?"""

    verdict: EconomicVerdict
    economically_justified: bool
    recommended_model_id: str | None
    success_probability: float
    failure_probability: float
    marginal_value_at_stake_minor: float
    expected_marginal_gain_minor: float
    expected_step_cost_minor: float
    expected_net_value_minor: float
    expected_roi_ratio: float
    cost_breakdown: CostBreakdown
    rationale: str
    digest: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["cost_breakdown"] = self.cost_breakdown.as_dict()
        return data


@dataclass
class _PosteriorStats:
    """Bayesian Beta(alpha, beta) pass-rate + EWMA cost/latency tracker."""

    alpha: float
    beta: float
    ewma_latency_sec: float
    ewma_input_tokens: float
    ewma_output_tokens: float
    observations: int = 0

    @property
    def mean_success_prob(self) -> float:
        return max(0.01, min(0.995, self.alpha / (self.alpha + self.beta)))


def normalize_model_catalog(
    models: tuple[ModelProfile, ...] | list[ModelProfile] | Mapping[str, ModelProfile] | None = None,
) -> dict[str, ModelProfile]:
    """Normalize a sequence or mapping of ModelProfile instances into a validated dict."""
    if models is None:
        models = DEFAULT_MODEL_CATALOG
    if isinstance(models, Mapping):
        items = list(models.values())
        for k, v in models.items():
            if isinstance(v, ModelProfile) and k != v.model_id:
                raise ValueError(f"CATALOG_KEY_MISMATCH:{k}!={v.model_id}")
    elif isinstance(models, (tuple, list)):
        items = list(models)
    else:
        raise TypeError("MODEL_CATALOG_INVALID_CONTAINER")
    if not items:
        raise ValueError("MODEL_CATALOG_EMPTY")
    normalized: dict[str, ModelProfile] = {}
    for item in items:
        if not isinstance(item, ModelProfile):
            raise TypeError("MODEL_CATALOG_ENTRY_NOT_MODEL_PROFILE")
        if item.model_id in normalized:
            raise ValueError(f"DUPLICATE_MODEL_ID:{item.model_id}")
        normalized[item.model_id] = item
    return normalized


class EconomicIntelligenceEngine:
    """Evaluates marginal EV of model calls, retries, and human escalations."""

    def __init__(
        self,
        policy: EconomicPolicy | None = None,
        models: tuple[ModelProfile, ...] | list[ModelProfile] | Mapping[str, ModelProfile] = DEFAULT_MODEL_CATALOG,
    ) -> None:
        self.policy = policy or EconomicPolicy()
        self.models: dict[str, ModelProfile] = normalize_model_catalog(models)
        self._posteriors: dict[tuple[str, str], _PosteriorStats] = {}

    def _stats_for(self, model_id: str, task_kind: str) -> _PosteriorStats:
        key = (model_id, task_kind)
        if key not in self._posteriors:
            profile = self.models[model_id]
            prior = profile.prior_success_prob(task_kind)
            # Prior strength = 10 pseudo-observations
            self._posteriors[key] = _PosteriorStats(
                alpha=prior * 10.0,
                beta=(1.0 - prior) * 10.0,
                ewma_latency_sec=profile.mean_latency_sec,
                ewma_input_tokens=900.0,
                ewma_output_tokens=500.0,
            )
        return self._posteriors[key]

    def record_observation(
        self,
        *,
        model_id: str,
        task_kind: str,
        independently_verified_success: bool,
        input_tokens: int,
        output_tokens: int,
        latency_sec: float,
    ) -> dict:
        """Update empirical model posteriors ONLY from actual execution outcomes."""
        if model_id not in self.models:
            raise ValueError("UNKNOWN_MODEL_ID")
        stats = self._stats_for(model_id, task_kind)
        if independently_verified_success:
            stats.alpha += 1.0
        else:
            stats.beta += 1.5  # Penalize unverified/failed outcomes more sharply
        weight = 0.3
        stats.ewma_latency_sec = (1 - weight) * stats.ewma_latency_sec + weight * max(0.05, float(latency_sec))
        stats.ewma_input_tokens = (1 - weight) * stats.ewma_input_tokens + weight * max(1.0, float(input_tokens))
        stats.ewma_output_tokens = (1 - weight) * stats.ewma_output_tokens + weight * max(1.0, float(output_tokens))
        stats.observations += 1
        return {
            "model_id": model_id,
            "task_kind": task_kind,
            "posterior_success_prob": round(stats.mean_success_prob, 4),
            "ewma_latency_sec": round(stats.ewma_latency_sec, 3),
            "observations": stats.observations,
        }

    def estimate_step_cost(
        self,
        *,
        model_id: str,
        task_kind: str,
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        attempt: int = 1,
        require_human_supervision: bool = False,
        failed_models: tuple[str, ...] = (),
    ) -> tuple[float, CostBreakdown]:
        """Return (success_probability, CostBreakdown) for a proposed step execution."""
        if model_id not in self.models:
            raise ValueError("UNKNOWN_MODEL_ID")
        profile = self.models[model_id]
        stats = self._stats_for(model_id, task_kind)

        in_tokens = int(estimated_input_tokens if estimated_input_tokens is not None else stats.ewma_input_tokens)
        out_tokens = int(estimated_output_tokens if estimated_output_tokens is not None else stats.ewma_output_tokens)
        latency = float(stats.ewma_latency_sec)

        base_p = stats.mean_success_prob
        # If this exact model already failed on an earlier attempt for this step,
        # its conditional probability of succeeding on a repeat drops sharply.
        if model_id in failed_models:
            repeat_count = sum(1 for m in failed_models if m == model_id)
            base_p *= 0.45 ** repeat_count
        elif attempt > 1:
            # Escalating to a fresh model with structured error feedback retains high P(success)
            base_p = min(0.99, base_p * (0.96 ** (attempt - 1)))

        if require_human_supervision:
            base_p = min(0.995, base_p + (1.0 - base_p) * 0.75)

        p_success = max(0.01, min(0.995, base_p))
        p_fail = 1.0 - p_success

        token_cost = (
            (in_tokens / 1000.0) * profile.input_cost_per_1k_minor
            + (out_tokens / 1000.0) * profile.output_cost_per_1k_minor
        )
        compute_cost = latency * profile.compute_cost_per_sec_minor
        total_elapsed = latency + (
            self.policy.human_intervention_latency_sec if require_human_supervision else 0.0
        )
        minutes = total_elapsed / 60.0
        time_cost = minutes * self.policy.time_cost_per_min_minor
        opportunity_cost = minutes * self.policy.opportunity_cost_per_min_minor
        human_cost = float(self.policy.human_intervention_cost_minor) if require_human_supervision else 0.0

        # Expected recovery cost if this call fails: probability of failure * cost of next tier retry
        next_tier_cost = token_cost * 1.5 + compute_cost * 1.5 + (latency / 60.0) * (
            self.policy.time_cost_per_min_minor + self.policy.opportunity_cost_per_min_minor
        )
        recovery_cost = p_fail * next_tier_cost

        breakdown = CostBreakdown(
            token_api_cost_minor=round(token_cost, 4),
            compute_infra_cost_minor=round(compute_cost, 4),
            time_cost_minor=round(time_cost, 4),
            opportunity_cost_minor=round(opportunity_cost, 4),
            human_supervision_cost_minor=round(human_cost, 4),
            recovery_cost_minor=round(recovery_cost, 4),
            elapsed_seconds=round(total_elapsed, 3),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            model_calls=1,
            human_interventions=1 if require_human_supervision else 0,
        )
        return p_success, breakdown

    def evaluate_next_action(
        self,
        *,
        task_kind: str,
        candidate_model_id: str,
        marginal_value_minor: float,
        spent_cost_minor: float = 0.0,
        elapsed_seconds: float = 0.0,
        attempt: int = 1,
        objective_already_verified: bool = False,
        require_human_supervision: bool = False,
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        failed_models: tuple[str, ...] = (),
        allow_reroute: bool = True,
    ) -> MarginalEVDecision:
        """Continuous economic gate: should the agent execute the next step/call?"""
        if objective_already_verified:
            zero = CostBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            return self._seal(
                verdict="STOP_OBJECTIVE_COMPLETE",
                economically_justified=False,
                recommended_model_id=None,
                p_success=1.0,
                marginal_value_minor=0.0,
                expected_gain=0.0,
                breakdown=zero,
                rationale="Objective is already independently verified complete; further spend has zero marginal value.",
            )

        if attempt > self.policy.max_step_attempts:
            zero = CostBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            return self._seal(
                verdict="STOP_NEGATIVE_EXPECTED_VALUE",
                economically_justified=False,
                recommended_model_id=None,
                p_success=0.0,
                marginal_value_minor=marginal_value_minor,
                expected_gain=0.0,
                breakdown=zero,
                rationale=f"Attempt {attempt} exceeds max_step_attempts ({self.policy.max_step_attempts}).",
            )

        p_success, breakdown = self.estimate_step_cost(
            model_id=candidate_model_id,
            task_kind=task_kind,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            attempt=attempt,
            require_human_supervision=require_human_supervision,
            failed_models=failed_models,
        )
        step_cost = breakdown.total_economic_cost_minor
        expected_gain = round(p_success * float(marginal_value_minor), 4)
        ev = round(expected_gain - step_cost, 4)

        # Check hard budget ceiling
        if spent_cost_minor + breakdown.direct_cost_minor > self.policy.budget_ceiling_minor:
            # Check if a cheaper model fits within budget with positive EV
            if allow_reroute and not require_human_supervision:
                alt = self._best_alternative(
                    task_kind=task_kind,
                    marginal_value_minor=marginal_value_minor,
                    spent_cost_minor=spent_cost_minor,
                    elapsed_seconds=elapsed_seconds,
                    attempt=attempt,
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    failed_models=failed_models,
                )
                if alt is not None and alt[0] != candidate_model_id:
                    alt_id, alt_p, alt_bd, alt_gain, alt_ev = alt
                    return self._seal(
                        verdict="REROUTE_MODEL",
                        economically_justified=True,
                        recommended_model_id=alt_id,
                        p_success=alt_p,
                        marginal_value_minor=marginal_value_minor,
                        expected_gain=alt_gain,
                        breakdown=alt_bd,
                        rationale=(
                            f"Candidate {candidate_model_id} exceeds remaining budget; "
                            f"rerouting to {alt_id} with positive EV ({alt_ev:.2f} {self.policy.currency} minor)."
                        ),
                    )
            return self._seal(
                verdict="STOP_BUDGET_EXCEEDED",
                economically_justified=False,
                recommended_model_id=None,
                p_success=p_success,
                marginal_value_minor=marginal_value_minor,
                expected_gain=expected_gain,
                breakdown=breakdown,
                rationale=(
                    f"Projected direct spend ({spent_cost_minor + breakdown.direct_cost_minor:.2f}) "
                    f"exceeds budget ceiling ({self.policy.budget_ceiling_minor})."
                ),
            )

        # Check SLA deadline
        if elapsed_seconds + breakdown.elapsed_seconds > self.policy.sla_seconds:
            if allow_reroute and not require_human_supervision:
                alt = self._best_alternative(
                    task_kind=task_kind,
                    marginal_value_minor=marginal_value_minor,
                    spent_cost_minor=spent_cost_minor,
                    elapsed_seconds=elapsed_seconds,
                    attempt=attempt,
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    failed_models=failed_models,
                )
                if alt is not None and alt[0] != candidate_model_id:
                    alt_id, alt_p, alt_bd, alt_gain, alt_ev = alt
                    return self._seal(
                        verdict="REROUTE_MODEL",
                        economically_justified=True,
                        recommended_model_id=alt_id,
                        p_success=alt_p,
                        marginal_value_minor=marginal_value_minor,
                        expected_gain=alt_gain,
                        breakdown=alt_bd,
                        rationale=(
                            f"Candidate {candidate_model_id} exceeds remaining SLA; "
                            f"rerouting to faster model {alt_id} ({alt_bd.elapsed_seconds:.1f}s) "
                            f"with positive EV ({alt_ev:.2f})."
                        ),
                    )
            return self._seal(
                verdict="STOP_SLA_EXCEEDED",
                economically_justified=False,
                recommended_model_id=None,
                p_success=p_success,
                marginal_value_minor=marginal_value_minor,
                expected_gain=expected_gain,
                breakdown=breakdown,
                rationale=(
                    f"Projected elapsed time ({elapsed_seconds + breakdown.elapsed_seconds:.1f}s) "
                    f"exceeds SLA ({self.policy.sla_seconds:.1f}s)."
                ),
            )

        # Check human supervision justification specifically
        if require_human_supervision and ev <= 0:
            return self._seal(
                verdict="STOP_HUMAN_INTERVENTION_UNJUSTIFIED",
                economically_justified=False,
                recommended_model_id=None,
                p_success=p_success,
                marginal_value_minor=marginal_value_minor,
                expected_gain=expected_gain,
                breakdown=breakdown,
                rationale=(
                    f"Human intervention cost ({breakdown.human_supervision_cost_minor:.1f} + time/opportunity) "
                    f"exceeds expected contribution ({expected_gain:.1f}); EV={ev:.2f}."
                ),
            )

        roi_ratio = (ev / step_cost) if step_cost > 0 else 0.0
        if ev <= 0 or roi_ratio < self.policy.min_expected_roi_ratio:
            if allow_reroute and not require_human_supervision:
                alt = self._best_alternative(
                    task_kind=task_kind,
                    marginal_value_minor=marginal_value_minor,
                    spent_cost_minor=spent_cost_minor,
                    elapsed_seconds=elapsed_seconds,
                    attempt=attempt,
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    failed_models=failed_models,
                )
                if alt is not None:
                    alt_id, alt_p, alt_bd, alt_gain, alt_ev = alt
                    return self._seal(
                        verdict="REROUTE_MODEL",
                        economically_justified=True,
                        recommended_model_id=alt_id,
                        p_success=alt_p,
                        marginal_value_minor=marginal_value_minor,
                        expected_gain=alt_gain,
                        breakdown=alt_bd,
                        rationale=(
                            f"Candidate {candidate_model_id} has non-positive EV ({ev:.2f}); "
                            f"rerouting to {alt_id} with EV={alt_ev:.2f}."
                        ),
                    )
            return self._seal(
                verdict="STOP_NEGATIVE_EXPECTED_VALUE",
                economically_justified=False,
                recommended_model_id=None,
                p_success=p_success,
                marginal_value_minor=marginal_value_minor,
                expected_gain=expected_gain,
                breakdown=breakdown,
                rationale=(
                    f"Expected contribution ({expected_gain:.2f}) < total economic step cost "
                    f"({step_cost:.2f}); net EV={ev:.2f} <= 0."
                ),
            )

        return self._seal(
            verdict="PROCEED",
            economically_justified=True,
            recommended_model_id=candidate_model_id,
            p_success=p_success,
            marginal_value_minor=marginal_value_minor,
            expected_gain=expected_gain,
            breakdown=breakdown,
            rationale=(
                f"Positive marginal EV ({ev:.2f} {self.policy.currency} minor, "
                f"P(success)={p_success:.1%}, step cost={step_cost:.2f})."
            ),
        )

    def _best_alternative(
        self,
        *,
        task_kind: str,
        marginal_value_minor: float,
        spent_cost_minor: float,
        elapsed_seconds: float,
        attempt: int,
        estimated_input_tokens: int | None,
        estimated_output_tokens: int | None,
        failed_models: tuple[str, ...],
    ) -> tuple[str, float, CostBreakdown, float, float] | None:
        best: tuple[str, float, CostBreakdown, float, float] | None = None
        for model_id in self.models:
            p, bd = self.estimate_step_cost(
                model_id=model_id,
                task_kind=task_kind,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                attempt=attempt,
                require_human_supervision=False,
                failed_models=failed_models,
            )
            if spent_cost_minor + bd.direct_cost_minor > self.policy.budget_ceiling_minor:
                continue
            if elapsed_seconds + bd.elapsed_seconds > self.policy.sla_seconds:
                continue
            gain = round(p * float(marginal_value_minor), 4)
            ev = round(gain - bd.total_economic_cost_minor, 4)
            roi = (ev / bd.total_economic_cost_minor) if bd.total_economic_cost_minor > 0 else 0.0
            if ev > 0 and roi >= self.policy.min_expected_roi_ratio:
                if best is None or ev > best[4]:
                    best = (model_id, p, bd, gain, ev)
        return best

    def _seal(
        self,
        *,
        verdict: EconomicVerdict,
        economically_justified: bool,
        recommended_model_id: str | None,
        p_success: float,
        marginal_value_minor: float,
        expected_gain: float,
        breakdown: CostBreakdown,
        rationale: str,
    ) -> MarginalEVDecision:
        step_cost = breakdown.total_economic_cost_minor
        ev = round(expected_gain - step_cost, 4)
        roi = round((ev / step_cost) if step_cost > 0 else 0.0, 4)
        p_fail = round(max(0.0, 1.0 - p_success), 4)
        p_succ = round(p_success, 4)
        payload = {
            "verdict": verdict,
            "economically_justified": economically_justified,
            "recommended_model_id": recommended_model_id,
            "success_probability": p_succ,
            "marginal_value_at_stake_minor": round(float(marginal_value_minor), 4),
            "expected_marginal_gain_minor": expected_gain,
            "expected_step_cost_minor": step_cost,
            "expected_net_value_minor": ev,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return MarginalEVDecision(
            verdict=verdict,
            economically_justified=economically_justified,
            recommended_model_id=recommended_model_id,
            success_probability=p_succ,
            failure_probability=p_fail,
            marginal_value_at_stake_minor=round(float(marginal_value_minor), 4),
            expected_marginal_gain_minor=expected_gain,
            expected_step_cost_minor=step_cost,
            expected_net_value_minor=ev,
            expected_roi_ratio=roi,
            cost_breakdown=breakdown,
            rationale=rationale,
            digest=digest,
        )


class ModelRouter:
    """AI Bridge router supporting static, dynamic, and outcome_driven routing."""

    def __init__(
        self,
        engine: EconomicIntelligenceEngine,
        strategy: RoutingStrategy = "outcome_driven",
        static_model_id: str | None = None,
    ) -> None:
        if strategy not in ("static", "dynamic", "outcome_driven"):
            raise ValueError("ROUTING_STRATEGY_INVALID")
        if static_model_id is None:
            if "gemini-4-carbon" in engine.models:
                static_model_id = "gemini-4-carbon"
            else:
                static_model_id = next(
                    (m.model_id for m in engine.models.values() if m.tier == "frontier"),
                    list(engine.models.keys())[-1],
                )
        if static_model_id not in engine.models:
            raise ValueError("STATIC_MODEL_NOT_IN_CATALOG")
        self.engine = engine
        self.strategy: RoutingStrategy = strategy
        self.static_model_id = static_model_id

    def select_model(
        self,
        *,
        task_kind: str,
        marginal_value_minor: float,
        spent_cost_minor: float = 0.0,
        elapsed_seconds: float = 0.0,
        attempt: int = 1,
        complexity: Literal["low", "medium", "high"] = "medium",
        estimated_input_tokens: int = 900,
        estimated_output_tokens: int = 500,
        failed_models: tuple[str, ...] = (),
        unavailable_models: tuple[str, ...] = (),
    ) -> tuple[str | None, MarginalEVDecision]:
        """Select a model according to the configured strategy and verify its EV."""
        available = [m for m in self.engine.models if m not in unavailable_models]
        if not available:
            zero = CostBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            decision = self.engine._seal(
                verdict="STOP_NEGATIVE_EXPECTED_VALUE",
                economically_justified=False,
                recommended_model_id=None,
                p_success=0.0,
                marginal_value_minor=marginal_value_minor,
                expected_gain=0.0,
                breakdown=zero,
                rationale="All models in catalog are marked unavailable.",
            )
            return None, decision

        if self.strategy == "static":
            chosen = self.static_model_id if self.static_model_id in available else available[-1]
            decision = self.engine.evaluate_next_action(
                task_kind=task_kind,
                candidate_model_id=chosen,
                marginal_value_minor=marginal_value_minor,
                spent_cost_minor=spent_cost_minor,
                elapsed_seconds=elapsed_seconds,
                attempt=attempt,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                failed_models=failed_models,
                allow_reroute=False,
            )
            return (chosen if decision.economically_justified else None), decision

        if self.strategy == "dynamic":
            tier_map = {
                "low": "fast",
                "medium": "balanced",
                "high": "frontier",
            }
            if task_kind in ("triage", "extraction") and attempt == 1:
                target_tier = "fast"
            elif task_kind == "architecture" or complexity == "high" or attempt >= 2:
                target_tier = "frontier"
            else:
                target_tier = tier_map.get(complexity, "balanced")

            tier_candidates = [
                m_id for m_id in available
                if self.engine.models[m_id].tier == target_tier and m_id not in failed_models
            ]
            if not tier_candidates:
                tier_candidates = [m_id for m_id in available if m_id not in failed_models] or available
            chosen = tier_candidates[0]
            decision = self.engine.evaluate_next_action(
                task_kind=task_kind,
                candidate_model_id=chosen,
                marginal_value_minor=marginal_value_minor,
                spent_cost_minor=spent_cost_minor,
                elapsed_seconds=elapsed_seconds,
                attempt=attempt,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                failed_models=failed_models,
                allow_reroute=True,
            )
            final_model = decision.recommended_model_id if decision.economically_justified else None
            return final_model, decision

        # strategy == "outcome_driven":
        # Evaluate every available model and choose the one that maximizes
        # risk-adjusted Expected Verified Net Value (EV = P(verified_success)*V - Hurdle*ExpectedTotalCost)
        # where high-cost models must justify their incremental spend by at least 1.5x marginal cost.
        best_model: str | None = None
        best_decision: MarginalEVDecision | None = None
        best_score: float = -1e18
        for model_id in available:
            decision = self.engine.evaluate_next_action(
                task_kind=task_kind,
                candidate_model_id=model_id,
                marginal_value_minor=marginal_value_minor,
                spent_cost_minor=spent_cost_minor,
                elapsed_seconds=elapsed_seconds,
                attempt=attempt,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                failed_models=failed_models,
                allow_reroute=False,
            )
            # Risk-adjusted capital efficiency score: penalize excess direct/time spend
            # unless it buys a commensurate jump in verified success probability.
            score = decision.expected_marginal_gain_minor - (1.8 * decision.expected_step_cost_minor)
            if best_decision is None:
                best_decision = decision
                best_model = model_id if decision.economically_justified else None
                best_score = score
            else:
                if decision.economically_justified and not best_decision.economically_justified:
                    best_decision = decision
                    best_model = model_id
                    best_score = score
                elif (
                    decision.economically_justified == best_decision.economically_justified
                    and score > best_score
                ):
                    best_decision = decision
                    best_model = model_id if decision.economically_justified else None
                    best_score = score

        assert best_decision is not None
        return best_model, best_decision
