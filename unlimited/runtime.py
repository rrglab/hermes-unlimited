"""Tenant-isolated company and service registry with explicit identity enforcement.

This is a local provider control plane, not a Hermes task executor. All operations
require caller-supplied verified JustYou identity from a trusted adapter. Never
accept identity or verification claims from a customer payload.
"""
import json
import re
import sqlite3
import time
from pathlib import Path

IDENT = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class UnverifiedIdentity(PermissionError):
    pass


class ProviderStore:
    def __init__(self, database, verify_identity):
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou verifier required")
        self.database = str(database)
        self.verify_identity = verify_identity
        path = Path(self.database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _db(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    provider TEXT NOT NULL, tenant TEXT NOT NULL,
                    company TEXT NOT NULL, name TEXT NOT NULL,
                    identity_ref TEXT NOT NULL,
                    PRIMARY KEY(provider, tenant, company)
                );
                CREATE TABLE IF NOT EXISTS services (
                    provider TEXT NOT NULL, tenant TEXT NOT NULL,
                    company TEXT NOT NULL, service TEXT NOT NULL,
                    title TEXT NOT NULL, price_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    PRIMARY KEY(provider, tenant, company, service),
                    FOREIGN KEY(provider, tenant, company)
                        REFERENCES companies(provider, tenant, company)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    provider TEXT NOT NULL, tenant TEXT NOT NULL,
                    company TEXT NOT NULL, request TEXT NOT NULL,
                    service TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    result TEXT,
                    task_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(provider, tenant, company, request),
                    FOREIGN KEY(provider, tenant, company, service)
                        REFERENCES services(provider, tenant, company, service)
                );
                CREATE TABLE IF NOT EXISTS missions (
                    provider TEXT NOT NULL, tenant TEXT NOT NULL,
                    company TEXT NOT NULL, objective TEXT NOT NULL,
                    title TEXT NOT NULL, status TEXT NOT NULL,
                    independently_verified INTEGER NOT NULL DEFAULT 0,
                    target_value_minor INTEGER NOT NULL DEFAULT 0,
                    verified_value_minor INTEGER NOT NULL DEFAULT 0,
                    total_cost_minor REAL NOT NULL DEFAULT 0.0,
                    net_value_minor REAL NOT NULL DEFAULT 0.0,
                    routing_strategy TEXT NOT NULL DEFAULT 'outcome_driven',
                    report_json TEXT NOT NULL,
                    report_digest TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(provider, tenant, company, objective),
                    FOREIGN KEY(provider, tenant, company)
                        REFERENCES companies(provider, tenant, company)
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(requests)")}
            if "task_id" not in columns:
                db.execute("ALTER TABLE requests ADD COLUMN task_id TEXT")
            if "attempts" not in columns:
                db.execute("ALTER TABLE requests ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ids(*values):
        if any(not isinstance(value, str) or not IDENT.fullmatch(value) for value in values):
            raise ValueError("INVALID_SCOPE_IDENTIFIER")

    def _authorize(self, provider, tenant, identity):
        self._ids(provider, tenant)
        # Verifier must be a trusted object controlled by the host, never a payload flag.
        if not identity or self.verify_identity(provider, tenant, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")

    def create_company(self, provider, tenant, company, name, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company)
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise ValueError("COMPANY_NAME_INVALID")
        with self._db() as db:
            db.execute(
                "INSERT INTO companies VALUES(?,?,?,?,?)",
                (provider, tenant, company, name.strip(), identity),
            )
        return {"provider": provider, "tenant": tenant, "company": company, "created": True}

    def list_companies(self, provider, tenant, identity):
        self._authorize(provider, tenant, identity)
        with self._db() as db:
            rows = db.execute(
                "SELECT company,name FROM companies WHERE provider=? AND tenant=? ORDER BY company",
                (provider, tenant),
            ).fetchall()
        return [{"company": c, "name": n} for c, n in rows]

    def publish_service(self, provider, tenant, company, service, title, price_minor, currency, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, service)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("SERVICE_TITLE_INVALID")
        if type(price_minor) is not int or price_minor < 0:
            raise ValueError("PRICE_INVALID")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("CURRENCY_INVALID")
        with self._db() as db:
            db.execute(
                "INSERT INTO services VALUES(?,?,?,?,?,?,?)",
                (provider, tenant, company, service, title.strip(), price_minor, currency),
            )
        return {"service": service, "published": True, "price_minor": price_minor, "currency": currency}

    def request_service(self, provider, tenant, company, request, service, payload, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, request, service)
        serialized = json.dumps(payload, separators=(",", ":"))
        if not isinstance(payload, dict) or len(serialized) > 16384:
            raise ValueError("PAYLOAD_INVALID")
        with self._db() as db:
            db.execute(
                "INSERT INTO requests(provider,tenant,company,request,service,payload,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (provider, tenant, company, request, service, serialized, int(time.time())),
            )
        # Queued is not executed, authorized, billed or completed.
        return {"request": request, "state": "queued", "executed": False}

    def list_requests(self, provider, tenant, company, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company)
        with self._db() as db:
            rows = db.execute(
                "SELECT request,service,state,result FROM requests "
                "WHERE provider=? AND tenant=? AND company=? ORDER BY created_at,request",
                (provider, tenant, company),
            ).fetchall()
        return [{"request": r, "service": s, "state": st, "result": json.loads(res) if res else None}
                for r, s, st, res in rows]

    def get_request(self, provider, tenant, company, request, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, request)
        with self._db() as db:
            row = db.execute(
                "SELECT service,payload,state,result,task_id,attempts FROM requests "
                "WHERE provider=? AND tenant=? AND company=? AND request=?",
                (provider, tenant, company, request)).fetchone()
        if row is None:
            return None
        return {"request": request, "service": row[0], "payload": json.loads(row[1]),
                "state": row[2], "result": json.loads(row[3]) if row[3] else None,
                "task_id": row[4], "attempts": int(row[5] or 0)}

    def attach_task(self, provider, tenant, company, request, task_id, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, request)
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", task_id):
            raise ValueError("TASK_ID_INVALID")
        with self._db() as db:
            updated = db.execute(
                "UPDATE requests SET task_id=?,state='running',attempts=CASE WHEN attempts=0 THEN 1 ELSE attempts END "
                "WHERE provider=? AND tenant=? AND company=? AND request=? "
                "AND (task_id IS NULL OR task_id=?)",
                (task_id, provider, tenant, company, request, task_id)).rowcount
        if updated != 1:
            raise ValueError("REQUEST_NOT_FOUND_OR_TASK_CONFLICT")

    def recover_blocked_request(self, provider, tenant, company, request, new_task_id, identity, *, max_attempts=3):
        self._authorize(provider, tenant, identity)
        self._ids(company, request)
        if not isinstance(new_task_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", new_task_id):
            raise ValueError("TASK_ID_INVALID")
        with self._db() as db:
            row = db.execute(
                "SELECT state, task_id, attempts FROM requests "
                "WHERE provider=? AND tenant=? AND company=? AND request=?",
                (provider, tenant, company, request),
            ).fetchone()
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            state, old_task_id, attempts = row[0], row[1], int(row[2] or 1)
            if state != "blocked":
                raise ValueError("REQUEST_NOT_BLOCKED")
            if attempts >= max_attempts:
                raise ValueError("MAX_RECOVERY_ATTEMPTS_EXCEEDED")
            if new_task_id == old_task_id:
                raise ValueError("RECOVERY_REQUIRES_NEW_TASK_ID")
            db.execute(
                "UPDATE requests SET task_id=?,state='running',attempts=? "
                "WHERE provider=? AND tenant=? AND company=? AND request=? AND state='blocked'",
                (new_task_id, attempts + 1, provider, tenant, company, request),
            )
        return {"request": request, "state": "running", "task_id": new_task_id,
                "previous_task_id": old_task_id, "attempts": attempts + 1, "recovered": True}

    def record_task_result(self, provider, tenant, company, request, task_id, result, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, request)
        if not isinstance(result, dict) or result.get("found") is not True:
            raise ValueError("TASK_RESULT_UNVERIFIED")
        status = result.get("status")
        if status not in {"ready", "running", "review", "done", "blocked", "scheduled", "todo", "triage", "archived"}:
            raise ValueError("TASK_STATE_INVALID")
        serialized = json.dumps(result, separators=(",", ":"))
        with self._db() as db:
            updated = db.execute(
                "UPDATE requests SET state=?,result=? WHERE provider=? AND tenant=? "
                "AND company=? AND request=? AND task_id=?",
                (status, serialized, provider, tenant, company, request, task_id)).rowcount
        if updated != 1:
            raise ValueError("REQUEST_TASK_MISMATCH")

    def record_mission(self, provider, tenant, company, report_dict, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company)
        if not isinstance(report_dict, dict):
            raise ValueError("MISSION_REPORT_INVALID")
        objective = report_dict.get("objective_id", "")
        self._ids(objective)
        if report_dict.get("tenant_id") != tenant or report_dict.get("company_id") != company:
            raise PermissionError("MISSION_SCOPE_MISMATCH")
        serialized = json.dumps(report_dict, separators=(",", ":"), default=str)
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO missions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    provider,
                    tenant,
                    company,
                    objective,
                    str(report_dict.get("title", objective))[:160],
                    str(report_dict.get("status", "UNKNOWN")),
                    1 if report_dict.get("independently_verified") is True else 0,
                    int(report_dict.get("target_value_minor", 0)),
                    int(report_dict.get("verified_value_minor", 0)),
                    float(report_dict.get("total_economic_cost_minor", 0.0)),
                    float(report_dict.get("net_economic_value_minor", 0.0)),
                    str(report_dict.get("routing_strategy", "outcome_driven")),
                    serialized,
                    str(report_dict.get("report_digest", "")),
                    int(time.time()),
                ),
            )
        return {"objective_id": objective, "recorded": True}

    def list_missions(self, provider, tenant, company, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company)
        with self._db() as db:
            rows = db.execute(
                "SELECT objective, status, independently_verified, verified_value_minor, "
                "total_cost_minor, net_value_minor, routing_strategy, report_digest "
                "FROM missions WHERE provider=? AND tenant=? AND company=? ORDER BY created_at, objective",
                (provider, tenant, company),
            ).fetchall()
        return [
            {
                "objective": r[0],
                "status": r[1],
                "independently_verified": bool(r[2]),
                "verified_value_minor": int(r[3]),
                "total_cost_minor": float(r[4]),
                "net_value_minor": float(r[5]),
                "routing_strategy": r[6],
                "report_digest": r[7],
            }
            for r in rows
        ]

    def get_mission(self, provider, tenant, company, objective, identity):
        self._authorize(provider, tenant, identity)
        self._ids(company, objective)
        with self._db() as db:
            row = db.execute(
                "SELECT report_json FROM missions WHERE provider=? AND tenant=? AND company=? AND objective=?",
                (provider, tenant, company, objective),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])
