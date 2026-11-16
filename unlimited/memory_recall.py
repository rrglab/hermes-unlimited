"""Read-only compatibility reader for DEV Company Memory records.

No memory ingestion, execution, or promotion. Stored classifications are
unverified claims until independent evidence is checked outside this tool.
"""
from __future__ import annotations

import re
import sqlite3

TASK_KIND = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def recall_existing(store, provider, tenant, company, identity, *, task_kind=None, limit=5, verified_only=False):
    """Read a pre-existing company_memory table with strict trusted scope."""
    store._authorize(provider, tenant, identity)
    store._ids(company)
    if task_kind is not None and (not isinstance(task_kind, str) or not TASK_KIND.fullmatch(task_kind)):
        raise ValueError("TASK_KIND_INVALID")
    if type(limit) is not int or not (1 <= limit <= 50):
        raise ValueError("LIMIT_INVALID")
    if type(verified_only) is not bool:
        raise ValueError("VERIFIED_FILTER_INVALID")
    with store._db() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_memory'").fetchone()
        if not exists:
            return {"entries": [], "memory_available": False,
                    "attestation_verified": False, "source": "EXISTING_LOCAL_MEMORY_ONLY"}
        query = ("SELECT entry_id, task_kind, source_id, classification, independently_verified,"
                 " lesson, evidence_digest, cost_minor, verified_value_minor, created_at "
                 "FROM company_memory WHERE provider=? AND tenant=? AND company=?")
        params = [provider, tenant, company]
        if task_kind is not None:
            query += " AND task_kind=?"
            params.append(task_kind)
        if verified_only:
            query += " AND classification='VERIFIED_OUTCOME' AND independently_verified=1"
        query += " ORDER BY created_at DESC, entry_id ASC LIMIT ?"
        params.append(limit)
        try:
            rows = db.execute(query, params).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError("MEMORY_SCHEMA_UNAVAILABLE") from exc
    entries = []
    for entry_id, kind, source_id, classification, claimed, lesson, digest, cost, value, created in rows:
        if classification not in ("RECORDED_UNVERIFIED", "VERIFIED_OUTCOME"):
            raise ValueError("MEMORY_CLASSIFICATION_INVALID")
        entries.append({
            "entry_id": entry_id, "task_kind": kind, "source_id": source_id,
            "stored_classification": classification,
            "stored_verified_flag": bool(claimed),
            "independent_attestation_checked": False,
            "lesson": lesson, "stored_evidence_digest": digest,
            "stored_cost_minor": cost, "stored_value_minor": value,
            "created_at": created,
        })
    return {"entries": entries, "memory_available": True, "attestation_verified": False,
            "source": "EXISTING_LOCAL_MEMORY_ONLY"}
