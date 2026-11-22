"""Tenant-scoped oversight ledger bound to existing Hermes service requests.

Requires trusted JustYou verification via ProviderStore; never accepts an agent's
self-report as independent verification or as a monetary benefit claim.
"""
from decimal import Decimal, InvalidOperation

from .human_oversight_economics import (
    DeliveryEconomics,
    OversightEntry,
    OversightPhase,
    evaluate,
)

MAX_AMOUNT = Decimal(1000000000000)


def _bounded_amount(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 40:
        raise ValueError("COST_INVALID")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("COST_INVALID") from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise ValueError("COST_INVALID")
    return amount


class OversightLedger:
    def __init__(self, store):
        self.store = store
        with store._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS oversight_entries (
                provider TEXT NOT NULL, tenant TEXT NOT NULL, company TEXT NOT NULL,
                request TEXT NOT NULL, entry_id TEXT NOT NULL,
                phase TEXT NOT NULL, minutes TEXT NOT NULL, hourly_rate TEXT NOT NULL,
                PRIMARY KEY(provider, tenant, company, request, entry_id),
                FOREIGN KEY(provider, tenant, company, request)
                REFERENCES requests(provider, tenant, company, request)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS oversight_cost_audit (
                provider TEXT NOT NULL, tenant TEXT NOT NULL, company TEXT NOT NULL,
                request TEXT NOT NULL, ai_cost TEXT NOT NULL, recovery_cost TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS oversight_costs (
                provider TEXT NOT NULL, tenant TEXT NOT NULL, company TEXT NOT NULL,
                request TEXT NOT NULL, ai_cost TEXT NOT NULL, recovery_cost TEXT NOT NULL,
                PRIMARY KEY(provider, tenant, company, request),
                FOREIGN KEY(provider, tenant, company, request)
                REFERENCES requests(provider, tenant, company, request)
            )""")

    def _request(self, provider, tenant, company, request, identity):
        item = self.store.get_request(provider, tenant, company, request, identity)
        if item is None:
            raise ValueError("REQUEST_NOT_FOUND")
        # Derive the unit from the existing tenant-scoped service contract,
        # never from model-authored cost payloads.
        with self.store._db() as db:
            row = db.execute("""SELECT currency FROM services WHERE
                provider=? AND tenant=? AND company=? AND service=?""",
                (provider, tenant, company, item["service"])).fetchone()
        if row is None:
            raise ValueError("SERVICE_CURRENCY_UNAVAILABLE")
        item["currency"] = row[0]
        return item

    def record(self, provider, tenant, company, request, entry_id, phase, minutes, hourly_rate, identity):
        item = self._request(provider, tenant, company, request, identity)
        self.store._ids(entry_id)
        try:
            entry = OversightEntry(request, OversightPhase(phase), _bounded_amount(minutes), _bounded_amount(hourly_rate))
            if entry.cost > MAX_AMOUNT:
                raise ValueError("OVERSIGHT_INVALID")
        except (ArithmeticError, ValueError) as exc:
            raise ValueError("OVERSIGHT_INVALID") from exc
        with self.store._db() as db:
            db.execute("""INSERT INTO oversight_entries VALUES(?,?,?,?,?,?,?,?)""",
                       (provider, tenant, company, request, entry_id, entry.phase.value,
                        str(entry.minutes), str(entry.hourly_rate)))
        return {"recorded": True, "request": request, "entry_id": entry_id,
                "currency": item["currency"], "cost_input_provenance": "MODEL_SUBMITTED_UNVERIFIED"}

    def record_costs(self, provider, tenant, company, request, ai_cost, recovery_cost, identity):
        item = self._request(provider, tenant, company, request, identity)
        try:
            ai, recovery = _bounded_amount(ai_cost), _bounded_amount(recovery_cost)
        except ArithmeticError as exc:
            raise ValueError("COST_INVALID") from exc
        if not ai.is_finite() or not recovery.is_finite() or min(ai, recovery) < 0:
            raise ValueError("COST_INVALID")
        with self.store._db() as db:
            db.execute("""INSERT INTO oversight_cost_audit
                (provider,tenant,company,request,ai_cost,recovery_cost) VALUES(?,?,?,?,?,?)""",
                (provider, tenant, company, request, str(ai), str(recovery)))
            db.execute("""INSERT INTO oversight_costs VALUES(?,?,?,?,?,?)
                ON CONFLICT(provider,tenant,company,request)
                DO UPDATE SET ai_cost=excluded.ai_cost,recovery_cost=excluded.recovery_cost""",
                (provider, tenant, company, request, str(ai), str(recovery)))
        return {"recorded": True, "request": request,
                "currency": item["currency"], "cost_input_provenance": "MODEL_SUBMITTED_UNVERIFIED"}

    def report(self, provider, tenant, company, request, identity):
        item = self._request(provider, tenant, company, request, identity)
        with self.store._db() as db:
            rows = db.execute("""SELECT phase,minutes,hourly_rate FROM oversight_entries
                WHERE provider=? AND tenant=? AND company=? AND request=?""",
                (provider, tenant, company, request)).fetchall()
            cost = db.execute("""SELECT ai_cost,recovery_cost FROM oversight_costs
                WHERE provider=? AND tenant=? AND company=? AND request=?""",
                (provider, tenant, company, request)).fetchone()
        entries = [OversightEntry(request, OversightPhase(p), Decimal(m), Decimal(h)) for p,m,h in rows]
        # Native Hermes Kanban reports are self-reports; never infer independent verification.
        d = DeliveryEconomics(request, Decimal(0),
                             Decimal(cost[0]) if cost else Decimal(0),
                             Decimal(cost[1]) if cost else Decimal(0), False)
        result = evaluate(d, entries)
        return {"request": request, "task_id": item["task_id"], "task_state": item["state"],
                "currency": item["currency"],
                "cost_input_provenance": "MODEL_SUBMITTED_UNVERIFIED",
                "independently_verified": False,
                "costs_recorded": cost is not None,
                **{k: ({x: str(y) for x,y in v.items()} if isinstance(v, dict) else
                       str(v) if isinstance(v, Decimal) else v) for k,v in result.items()}}
