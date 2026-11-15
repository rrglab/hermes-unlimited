"""Tenant-scoped oversight ledger bound to existing Hermes service requests.

Requires trusted JustYou verification via ProviderStore; never accepts an agent's
self-report as independent verification or as a monetary benefit claim.
"""
import json
import sqlite3
from decimal import Decimal
from human_oversight_economics import DeliveryEconomics, OversightEntry, OversightPhase, evaluate


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
        return item

    def record(self, provider, tenant, company, request, entry_id, phase, minutes, hourly_rate, identity):
        self._request(provider, tenant, company, request, identity)
        self.store._ids(entry_id)
        entry = OversightEntry(request, OversightPhase(phase), Decimal(str(minutes)), Decimal(str(hourly_rate)))
        with self.store._db() as db:
            db.execute("""INSERT INTO oversight_entries VALUES(?,?,?,?,?,?,?,?)""",
                       (provider, tenant, company, request, entry_id, entry.phase.value,
                        str(entry.minutes), str(entry.hourly_rate)))
        return {"recorded": True, "request": request, "entry_id": entry_id}

    def record_costs(self, provider, tenant, company, request, ai_cost, recovery_cost, identity):
        self._request(provider, tenant, company, request, identity)
        ai, recovery = Decimal(str(ai_cost)), Decimal(str(recovery_cost))
        if not ai.is_finite() or not recovery.is_finite() or min(ai, recovery) < 0:
            raise ValueError("COST_INVALID")
        with self.store._db() as db:
            db.execute("""INSERT INTO oversight_costs VALUES(?,?,?,?,?,?)
                ON CONFLICT(provider,tenant,company,request)
                DO UPDATE SET ai_cost=excluded.ai_cost,recovery_cost=excluded.recovery_cost""",
                (provider, tenant, company, request, str(ai), str(recovery)))
        return {"recorded": True, "request": request}

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
        d = DeliveryEconomics(request, Decimal("0"),
                             Decimal(cost[0]) if cost else Decimal("0"),
                             Decimal(cost[1]) if cost else Decimal("0"), False)
        result = evaluate(d, entries)
        return {"request": request, "task_id": item["task_id"], "task_state": item["state"],
                "costs_recorded": cost is not None,
                **{k: ({x: str(y) for x,y in v.items()} if isinstance(v, dict) else
                       str(v) if isinstance(v, Decimal) else v) for k,v in result.items()}}
