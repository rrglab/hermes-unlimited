"""Human oversight accounting for verified agent deliveries.

No external effects, no authorization decisions. Monetary values use Decimal.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import Enum


class OversightPhase(str, Enum):
    PRE_CONTROL = "pre_control"
    CO_PLANNING = "co_planning"
    LIVE_MONITORING = "live_monitoring"
    POST_REVIEW = "post_review"


@dataclass(frozen=True)
class OversightEntry:
    delivery_id: str
    phase: OversightPhase
    minutes: Decimal
    hourly_rate: Decimal

    def __post_init__(self):
        if (not self.delivery_id or not self.minutes.is_finite() or not self.hourly_rate.is_finite()
                or self.minutes < 0 or self.hourly_rate < 0):
            raise ValueError("delivery_id required; minutes and hourly_rate must be nonnegative")

    @property
    def cost(self) -> Decimal:
        with localcontext() as context:
            context.prec = 28
            return self.minutes * self.hourly_rate / Decimal(60)


@dataclass(frozen=True)
class DeliveryEconomics:
    delivery_id: str
    verified_benefit: Decimal
    ai_cost: Decimal
    recovery_cost: Decimal
    independently_verified: bool

    def __post_init__(self):
        if (not self.delivery_id or not all(x.is_finite() for x in
                (self.verified_benefit, self.ai_cost, self.recovery_cost))
                or min(self.verified_benefit, self.ai_cost, self.recovery_cost) < 0):
            raise ValueError("delivery_id required; amounts must be nonnegative")


def evaluate(delivery: DeliveryEconomics, entries: list[OversightEntry]) -> dict:
    """Return explicit cost breakdown; unverified deliveries have no claimed net value."""
    if any(e.delivery_id != delivery.delivery_id for e in entries):
        raise ValueError("oversight entries must belong to the delivery")
    phases = {p.value: sum((e.cost for e in entries if e.phase == p), Decimal(0))
              for p in OversightPhase}
    oversight = sum(phases.values(), Decimal(0))
    total = delivery.ai_cost + delivery.recovery_cost + oversight
    return {
        "delivery_id": delivery.delivery_id,
        "verification_status": "VERIFIED" if delivery.independently_verified else "UNVERIFIED",
        "oversight_cost_by_phase": phases,
        "oversight_cost": oversight,
        "total_cost": total,
        "net_value": delivery.verified_benefit - total if delivery.independently_verified else None,
        "benefit_claim_eligible": delivery.independently_verified,
    }
