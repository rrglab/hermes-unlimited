"""Tenant-scoped oversight ledger bound to existing Hermes service requests.

Requires trusted JustYou verification via ProviderStore; never accepts an agent's
self-report as independent verification or as a monetary benefit claim.
"""
import time
from decimal import Decimal, InvalidOperation

from .human_oversight_economics import (
    DeliveryEconomics,
    OversightEntry,
    OversightPhase,
    evaluate,
)

MAX_AMOUNT = Decimal(1000000000000)
MAX_AMOUNT_STR_LEN = 40


def _bounded_amount(raw, error_code):
    if isinstance(raw, bool) or raw is None:
        raise ValueError(error_code)
    text = raw if isinstance(raw, str) else str(raw)
    if not text or len(text) > MAX_AMOUNT_STR_LEN:
        raise ValueError(error_code)
    try:
        amount = Decimal(text)
    except (ArithmeticError, InvalidOperation, ValueError) as exc:
        raise ValueError(error_code) from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise ValueError(error_code)
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
            db.execute("""CREATE TABLE IF NOT EXISTS oversight_costs (
                provider TEXT NOT NULL, tenant TEXT NOT NULL, company TEXT NOT NULL,
                request TEXT NOT NULL, ai_cost TEXT NOT NULL, recovery_cost TEXT NOT NULL,
                PRIMARY KEY(provider, tenant, company, request),
                FOREIGN KEY(provider, tenant, company, request)
                REFERENCES requests(provider, tenant, company, request)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS oversight_cost_revisions (
                provider TEXT NOT NULL, tenant TEXT NOT NULL, company TEXT NOT NULL,
                request TEXT NOT NULL, revision INTEGER NOT NULL,
                ai_cost TEXT NOT NULL, recovery_cost TEXT NOT NULL,
                recorded_at INTEGER NOT NULL,
                PRIMARY KEY(provider, tenant, company, request, revision),
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
            mins = _bounded_amount(minutes, "OVERSIGHT_INVALID")
            rate = _bounded_amount(hourly_rate, "OVERSIGHT_INVALID")
            entry = OversightEntry(request, OversightPhase(phase), mins, rate)
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
        ai = _bounded_amount(ai_cost, "COST_INVALID")
        recovery = _bounded_amount(recovery_cost, "COST_INVALID")
        now = int(time.time())
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT COALESCE(MAX(revision), 0) FROM oversight_cost_revisions
                   WHERE provider=? AND tenant=? AND company=? AND request=?""",
                (provider, tenant, company, request),
            ).fetchone()
            next_rev = int(row[0]) + 1
            if next_rev == 1:
                # Preserve any pre-migration row from oversight_costs as revision 1.
                legacy = db.execute(
                    """SELECT ai_cost, recovery_cost FROM oversight_costs
                       WHERE provider=? AND tenant=? AND company=? AND request=?""",
                    (provider, tenant, company, request),
                ).fetchone()
                if legacy is not None:
                    db.execute(
                        """INSERT INTO oversight_cost_revisions
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (provider, tenant, company, request, 1, legacy[0], legacy[1], now),
                    )
                    next_rev = 2
            db.execute(
                """INSERT INTO oversight_cost_revisions VALUES(?,?,?,?,?,?,?,?)""",
                (provider, tenant, company, request, next_rev, str(ai), str(recovery), now),
            )
            db.execute(
                """INSERT INTO oversight_costs VALUES(?,?,?,?,?,?)
                   ON CONFLICT(provider,tenant,company,request)
                   DO UPDATE SET ai_cost=excluded.ai_cost,recovery_cost=excluded.recovery_cost""",
                (provider, tenant, company, request, str(ai), str(recovery)),
            )
        return {"recorded": True, "request": request, "revision": next_rev,
                "currency": item["currency"], "cost_input_provenance": "MODEL_SUBMITTED_UNVERIFIED"}

    def report(self, provider, tenant, company, request, identity):
        item = self._request(provider, tenant, company, request, identity)
        with self.store._db() as db:
            rows = db.execute("""SELECT phase,minutes,hourly_rate FROM oversight_entries
                WHERE provider=? AND tenant=? AND company=? AND request=?""",
                (provider, tenant, company, request)).fetchall()
            revisions = db.execute("""SELECT revision,ai_cost,recovery_cost,recorded_at
                FROM oversight_cost_revisions
                WHERE provider=? AND tenant=? AND company=? AND request=?
                ORDER BY revision ASC""",
                (provider, tenant, company, request)).fetchall()
            cost = db.execute("""SELECT ai_cost,recovery_cost FROM oversight_costs
                WHERE provider=? AND tenant=? AND company=? AND request=?""",
                (provider, tenant, company, request)).fetchone()
        latest_cost = (revisions[-1][1], revisions[-1][2]) if revisions else cost
        entries = [OversightEntry(request, OversightPhase(p), Decimal(m), Decimal(h)) for p,m,h in rows]
        # Native Hermes Kanban reports are self-reports; never infer independent verification.
        d = DeliveryEconomics(request, Decimal(0),
                             Decimal(latest_cost[0]) if latest_cost else Decimal(0),
                             Decimal(latest_cost[1]) if latest_cost else Decimal(0), False)
        result = evaluate(d, entries)
        cost_history = [
            {"revision": r, "ai_cost": a, "recovery_cost": rec, "recorded_at": ts}
            for r, a, rec, ts in revisions
        ]
        return {"request": request, "task_id": item["task_id"], "task_state": item["state"],
                "currency": item["currency"],
                "cost_input_provenance": "MODEL_SUBMITTED_UNVERIFIED",
                "independently_verified": False,
                "costs_recorded": latest_cost is not None,
                "cost_revisions": len(cost_history),
                "cost_history": cost_history,
                **{k: ({x: str(y) for x,y in v.items()} if isinstance(v, dict) else
                       str(v) if isinstance(v, Decimal) else v) for k,v in result.items()}}
