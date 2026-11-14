"""Tenant-isolated Company Memory and Autonomous Service Factory.

Separates agent self-reports (RECORDED_UNVERIFIED) from independently verified
business outcomes (VERIFIED_OUTCOME), deduplicates harvests, recalls scoped
lessons for future missions, and promotes positive-EV verified workflows into
reusable Service Factory blueprints.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from .autonomy import IndependentOutcomeVerifier, MissionExecutionReport, OutcomeVerificationReceipt
from .runtime import IDENT, UnverifiedIdentity

MemoryClassification = Literal["RECORDED_UNVERIFIED", "VERIFIED_OUTCOME"]
HEX64 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MemoryEntry:
    """Scoped organizational memory entry with explicit epistemic classification."""

    entry_id: str
    provider: str
    tenant: str
    company: str
    task_kind: str
    source_id: str
    classification: MemoryClassification
    independently_verified: bool
    lesson: str
    evidence_digest: str | None
    cost_minor: float
    verified_value_minor: int
    created_at: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ServiceBlueprint:
    """Reusable, evidence-bound service package synthesized by Service Factory."""

    blueprint_id: str
    provider: str
    tenant: str
    company: str
    service_id: str
    title: str
    version: str
    source_objective_id: str
    evidence_digest: str
    currency: str
    observed_cost_minor: float
    verified_value_minor: int
    net_value_minor: float
    recommended_price_minor: int
    budget_ceiling_minor: int
    required_deliverables: tuple[str, ...]
    published_to_catalog: bool

    def as_dict(self) -> dict:
        return asdict(self)


class CompanyMemoryStore:
    """SQLite-backed, JustYou-verified Company Memory with epistemic separation."""

    def __init__(self, database: str | Path, verify_identity: Callable[[str, str, str], bool]) -> None:
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou verifier required")
        self.database = str(database)
        self.verify_identity = verify_identity
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS company_memory (
                    entry_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    company TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    independently_verified INTEGER NOT NULL,
                    lesson TEXT NOT NULL,
                    evidence_digest TEXT,
                    cost_minor REAL NOT NULL DEFAULT 0.0,
                    verified_value_minor INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_company_memory_scope
                    ON company_memory(provider, tenant, company, task_kind, created_at DESC);
                """
            )

    def _authorize(self, provider: str, tenant: str, company: str, identity: str) -> None:
        if any(not isinstance(v, str) or not IDENT.fullmatch(v) for v in (provider, tenant, company)):
            raise ValueError("INVALID_SCOPE_IDENTIFIER")
        if not identity or self.verify_identity(provider, tenant, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")

    def record_unverified(
        self,
        *,
        provider: str,
        tenant: str,
        company: str,
        identity: str,
        task_kind: str,
        source_id: str,
        lesson: str,
    ) -> dict:
        """Record an agent self-reported lesson (marked RECORDED_UNVERIFIED)."""
        self._authorize(provider, tenant, company, identity)
        if not isinstance(task_kind, str) or not IDENT.fullmatch(task_kind):
            raise ValueError("TASK_KIND_INVALID")
        if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 128:
            raise ValueError("SOURCE_ID_INVALID")
        cleaned = " ".join(str(lesson).split()).strip() if isinstance(lesson, str) else ""
        if not cleaned or len(cleaned) > 4096:
            raise ValueError("LESSON_INVALID")

        entry_id = hashlib.sha256(
            f"{provider}\0{tenant}\0{company}\0{task_kind}\0{source_id}\0UNVERIFIED\0{cleaned}".encode("utf-8")
        ).hexdigest()[:32]

        with self._db() as db:
            existing = db.execute(
                "SELECT entry_id FROM company_memory WHERE entry_id=?",
                (entry_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "recorded": True,
                    "duplicate": True,
                    "entry_id": entry_id,
                    "classification": "RECORDED_UNVERIFIED",
                    "independently_verified": False,
                }
            db.execute(
                "INSERT INTO company_memory VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry_id,
                    provider,
                    tenant,
                    company,
                    task_kind,
                    source_id.strip(),
                    "RECORDED_UNVERIFIED",
                    0,
                    cleaned,
                    None,
                    0.0,
                    0,
                    int(time.time()),
                ),
            )
        return {
            "recorded": True,
            "duplicate": False,
            "entry_id": entry_id,
            "classification": "RECORDED_UNVERIFIED",
            "independently_verified": False,
        }

    def record_verified_outcome(
        self,
        *,
        provider: str,
        tenant: str,
        company: str,
        identity: str,
        task_kind: str,
        lesson: str,
        verification: OutcomeVerificationReceipt,
        cost_minor: float = 0.0,
        verified_value_minor: int = 0,
    ) -> dict:
        """Record a lesson backed by an independent OutcomeVerificationReceipt."""
        self._authorize(provider, tenant, company, identity)
        if not isinstance(task_kind, str) or not IDENT.fullmatch(task_kind):
            raise ValueError("TASK_KIND_INVALID")
        if (
            not isinstance(verification, OutcomeVerificationReceipt)
            or verification.independently_verified is not True
            or not HEX64.fullmatch(verification.evidence_digest)
            or not IndependentOutcomeVerifier().verify_receipt_authenticity(
                verification,
                expected_tenant_id=tenant,
                expected_company_id=company,
            )
        ):
            raise ValueError("INDEPENDENT_VERIFICATION_RECEIPT_REQUIRED")
        cleaned = " ".join(str(lesson).split()).strip() if isinstance(lesson, str) else ""
        if not cleaned or len(cleaned) > 4096:
            raise ValueError("LESSON_INVALID")

        entry_id = hashlib.sha256(
            f"{provider}\0{tenant}\0{company}\0{task_kind}\0{verification.objective_id}\0{verification.evidence_digest}".encode(
                "utf-8"
            )
        ).hexdigest()[:32]

        with self._db() as db:
            existing = db.execute(
                "SELECT entry_id FROM company_memory WHERE entry_id=?",
                (entry_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "recorded": True,
                    "duplicate": True,
                    "entry_id": entry_id,
                    "classification": "VERIFIED_OUTCOME",
                    "independently_verified": True,
                    "evidence_digest": verification.evidence_digest,
                }
            db.execute(
                "INSERT INTO company_memory VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry_id,
                    provider,
                    tenant,
                    company,
                    task_kind,
                    verification.objective_id,
                    "VERIFIED_OUTCOME",
                    1,
                    cleaned,
                    verification.evidence_digest,
                    round(float(cost_minor), 4),
                    int(verified_value_minor),
                    int(time.time()),
                ),
            )
        return {
            "recorded": True,
            "duplicate": False,
            "entry_id": entry_id,
            "classification": "VERIFIED_OUTCOME",
            "independently_verified": True,
            "evidence_digest": verification.evidence_digest,
        }

    def recall(
        self,
        *,
        provider: str,
        tenant: str,
        company: str,
        identity: str,
        task_kind: str | None = None,
        verified_only: bool = False,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Recall tenant- and company-isolated lessons, newest first."""
        self._authorize(provider, tenant, company, identity)
        if type(limit) is not int or not (1 <= limit <= 50):
            raise ValueError("LIMIT_INVALID")
        query = (
            "SELECT entry_id, provider, tenant, company, task_kind, source_id, "
            "classification, independently_verified, lesson, evidence_digest, "
            "cost_minor, verified_value_minor, created_at "
            "FROM company_memory WHERE provider=? AND tenant=? AND company=?"
        )
        params: list[object] = [provider, tenant, company]
        if task_kind is not None:
            if not isinstance(task_kind, str) or not IDENT.fullmatch(task_kind):
                raise ValueError("TASK_KIND_INVALID")
            query += " AND task_kind=?"
            params.append(task_kind)
        if verified_only:
            query += " AND independently_verified=1"
        query += " ORDER BY created_at DESC, entry_id ASC LIMIT ?"
        params.append(limit)

        with self._db() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [
            MemoryEntry(
                entry_id=r[0],
                provider=r[1],
                tenant=r[2],
                company=r[3],
                task_kind=r[4],
                source_id=r[5],
                classification=r[6],
                independently_verified=bool(r[7]),
                lesson=r[8],
                evidence_digest=r[9],
                cost_minor=float(r[10]),
                verified_value_minor=int(r[11]),
                created_at=int(r[12]),
            )
            for r in rows
        ]


class ServiceFactory:
    """Promotes independently verified, positive-EV missions into reusable services."""

    def __init__(self, database: str | Path, verify_identity: Callable[[str, str, str], bool]) -> None:
        if not callable(verify_identity):
            raise TypeError("Trusted JustYou verifier required")
        self.database = str(database)
        self.verify_identity = verify_identity
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS service_blueprints (
                    blueprint_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    company TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    source_objective_id TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL UNIQUE,
                    currency TEXT NOT NULL,
                    observed_cost_minor REAL NOT NULL,
                    verified_value_minor INTEGER NOT NULL,
                    net_value_minor REAL NOT NULL,
                    recommended_price_minor INTEGER NOT NULL,
                    budget_ceiling_minor INTEGER NOT NULL,
                    required_deliverables TEXT NOT NULL,
                    published_to_catalog INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def _authorize(self, provider: str, tenant: str, company: str, identity: str) -> None:
        if any(not isinstance(v, str) or not IDENT.fullmatch(v) for v in (provider, tenant, company)):
            raise ValueError("INVALID_SCOPE_IDENTIFIER")
        if not identity or self.verify_identity(provider, tenant, identity) is not True:
            raise UnverifiedIdentity("JUSTYOU_IDENTITY_NOT_VERIFIED")

    def synthesize_from_mission(
        self,
        *,
        provider: str,
        tenant: str,
        company: str,
        identity: str,
        service_id: str,
        title: str,
        report: MissionExecutionReport,
        currency: str = "NOK",
        version: str = "1.0.0",
        provider_store: object | None = None,
    ) -> ServiceBlueprint:
        """Create a reusable ServiceBlueprint from a verified positive-EV mission."""
        self._authorize(provider, tenant, company, identity)
        if not isinstance(service_id, str) or not IDENT.fullmatch(service_id):
            raise ValueError("SERVICE_ID_INVALID")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("SERVICE_TITLE_INVALID")
        if report.tenant_id != tenant or report.company_id != company:
            raise PermissionError("REPORT_SCOPE_MISMATCH")
        if (
            report.status != "VERIFIED_COMPLETE"
            or report.independently_verified is not True
            or report.verification.independently_verified is not True
            or not HEX64.fullmatch(report.verification.evidence_digest)
            or not IndependentOutcomeVerifier().verify_receipt_authenticity(
                report.verification,
                deliverables=report.deliverables,
                expected_tenant_id=tenant,
                expected_company_id=company,
                expected_objective_id=report.objective_id,
            )
        ):
            raise ValueError("INDEPENDENT_VERIFICATION_REQUIRED")
        if report.net_economic_value_minor <= 0 or report.verified_value_minor <= 0:
            raise ValueError("POSITIVE_NET_ECONOMIC_VALUE_REQUIRED")

        blueprint_id = hashlib.sha256(
            f"{provider}\0{tenant}\0{company}\0{service_id}\0{version}\0{report.verification.evidence_digest}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]

        # Calibrate pricing and budget ceiling from actual verified economics
        observed_cost = round(float(report.total_economic_cost_minor), 4)
        recommended_price = max(int(math.ceil(observed_cost * 3.0)), int(report.verified_value_minor * 0.8))
        budget_ceiling = max(int(math.ceil(observed_cost * 2.0)), int(recommended_price * 0.5))
        deliverables = tuple(sorted(report.deliverables.keys()))

        with self._db() as db:
            existing = db.execute(
                "SELECT blueprint_id FROM service_blueprints WHERE evidence_digest=?",
                (report.verification.evidence_digest,),
            ).fetchone()
            if existing is not None:
                raise ValueError("DUPLICATE_EXECUTION_EVENT")

            published = False
            if provider_store is not None and hasattr(provider_store, "publish_service"):
                provider_store.publish_service(
                    provider,
                    tenant,
                    company,
                    service_id,
                    title.strip(),
                    recommended_price,
                    currency,
                    identity,
                )
                published = True

            db.execute(
                "INSERT INTO service_blueprints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    blueprint_id,
                    provider,
                    tenant,
                    company,
                    service_id,
                    title.strip(),
                    version,
                    report.objective_id,
                    report.verification.evidence_digest,
                    currency,
                    observed_cost,
                    report.verified_value_minor,
                    round(float(report.net_economic_value_minor), 4),
                    recommended_price,
                    budget_ceiling,
                    json.dumps(deliverables),
                    1 if published else 0,
                ),
            )

        return ServiceBlueprint(
            blueprint_id=blueprint_id,
            provider=provider,
            tenant=tenant,
            company=company,
            service_id=service_id,
            title=title.strip(),
            version=version,
            source_objective_id=report.objective_id,
            evidence_digest=report.verification.evidence_digest,
            currency=currency,
            observed_cost_minor=observed_cost,
            verified_value_minor=report.verified_value_minor,
            net_value_minor=round(float(report.net_economic_value_minor), 4),
            recommended_price_minor=recommended_price,
            budget_ceiling_minor=budget_ceiling,
            required_deliverables=deliverables,
            published_to_catalog=published,
        )

    def list_blueprints(
        self,
        *,
        provider: str,
        tenant: str,
        company: str,
        identity: str,
    ) -> list[ServiceBlueprint]:
        self._authorize(provider, tenant, company, identity)
        with self._db() as db:
            rows = db.execute(
                "SELECT blueprint_id, provider, tenant, company, service_id, title, version, "
                "source_objective_id, evidence_digest, currency, observed_cost_minor, "
                "verified_value_minor, net_value_minor, recommended_price_minor, "
                "budget_ceiling_minor, required_deliverables, published_to_catalog "
                "FROM service_blueprints WHERE provider=? AND tenant=? AND company=? "
                "ORDER BY service_id, version",
                (provider, tenant, company),
            ).fetchall()
        return [
            ServiceBlueprint(
                blueprint_id=r[0],
                provider=r[1],
                tenant=r[2],
                company=r[3],
                service_id=r[4],
                title=r[5],
                version=r[6],
                source_objective_id=r[7],
                evidence_digest=r[8],
                currency=r[9],
                observed_cost_minor=float(r[10]),
                verified_value_minor=int(r[11]),
                net_value_minor=float(r[12]),
                recommended_price_minor=int(r[13]),
                budget_ceiling_minor=int(r[14]),
                required_deliverables=tuple(json.loads(r[15])),
                published_to_catalog=bool(r[16]),
            )
            for r in rows
        ]


import math  # noqa: E402
