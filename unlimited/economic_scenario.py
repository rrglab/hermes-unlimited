"""Read-only arithmetic against tenant-scoped, model-submitted cost entries.

A user/model-entered scenario cap is not an approved budget. This module
never routes, authorizes, stops, bills, or asserts independently verified ROI.
"""
from decimal import Decimal, InvalidOperation

MAX_AMOUNT = Decimal(1000000000000)


def _scenario_amount(raw):
    if not isinstance(raw, str) or len(raw) > 40 or not raw:
        raise ValueError("SCENARIO_CAP_INVALID")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError("SCENARIO_CAP_INVALID") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise ValueError("SCENARIO_CAP_INVALID")
    return amount


def evaluate_cost_scenario(ledger, provider, tenant, company, request, identity, *, scenario_cap):
    cap = _scenario_amount(scenario_cap)
    report = ledger.report(provider, tenant, company, request, identity)
    result = {"request": request, "currency": report["currency"],
              "scenario_cap": str(cap), "scenario_cap_source": "MODEL_SUBMITTED_UNVERIFIED",
              "cost_source": "MODEL_SUBMITTED_UNVERIFIED",
              "scenario_only": True, "decision_authority": "NONE",
              "execution_authorized": False, "independently_verified": False,
              "net_value": None, "roi": None, "customer_outcome_verified": False,
              "estimated_cost": report["total_cost"],
              "costs_recorded": report["costs_recorded"]}
    if not report["costs_recorded"]:
        # Human oversight establishes a *lower bound* only: it may prove an
        # over-cap situation, but missing AI/recovery costs can never be green.
        human_cost = Decimal(report["oversight_cost"])
        result.update({"comparison": "MODEL_INPUT_OVER_CAP" if human_cost > cap
                       else "INSUFFICIENT_COST_INPUT",
                       "difference": str(cap - human_cost) if human_cost > cap else None,
                       "within_scenario_cap": False if human_cost > cap else None})
        return result
    try:
        total = Decimal(report["total_cost"])
    except (InvalidOperation, ValueError):
        raise ValueError("COST_INPUT_INVALID") from None
    if not total.is_finite() or total < 0:
        raise ValueError("COST_INPUT_INVALID")
    result.update({"comparison": "MODEL_INPUT_WITHIN_CAP" if total <= cap else "MODEL_INPUT_OVER_CAP",
                   "difference": str(cap - total), "within_scenario_cap": total <= cap})
    return result
