"""Durable, scoped tool-schema fingerprint snapshots for future junior discovery.

No account credentials, API responses, tool arguments, user content or model
outputs are persisted here. An observed source disappearing must not promote
anything to execution; drift requires separate review and qualification.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable

_SCOPE = re.compile(r"^[a-zA-Z0-9_.:/ -]{1,160}$")


def source_key(source: str, *, toolset: str | None = None,
               query: str | None = None, namespace: str | None = None) -> str:
    if source == "hermes":
        value = toolset
    elif source == "connector":
        value = query
    elif source in ("mcp", "openapi"):
        value = namespace
    else:
        raise ValueError("INVALID_DISCOVERY_SOURCE")
    if (not isinstance(value, str) or not _SCOPE.fullmatch(value) or not value.strip()
        or ".." in value or value.startswith("/") or "//" in value):
        raise ValueError("DISCOVERY_SCOPE_REQUIRED")
    return source + ":" + value


def sync_discovery(db_path: str, provider: str, tenant: str, key: str,
                   discover: Callable[[dict[str, str]], dict[str, Any]]) -> dict[str, Any]:
    if not all(isinstance(v, str) and v.strip() for v in (db_path, provider, tenant, key)):
        raise ValueError("INVALID_DISCOVERY_STORAGE_SCOPE")
    if not callable(discover):
        raise ValueError("DISCOVERY_CALLABLE_REQUIRED")
    # db_path is sourced exclusively from verified Hermes host configuration.
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS unlimited_tool_fingerprints (
            provider TEXT NOT NULL, tenant TEXT NOT NULL, source_key TEXT NOT NULL,
            tool_name TEXT NOT NULL, schema_digest TEXT NOT NULL,
            PRIMARY KEY (provider, tenant, source_key, tool_name))""")
        rows = conn.execute("""SELECT tool_name, schema_digest FROM unlimited_tool_fingerprints
            WHERE provider=? AND tenant=? AND source_key=?""",(provider,tenant,key)).fetchall()
        previous = dict(rows)
        result = discover(previous)
        if not isinstance(result, dict) or result.get("execution_authorized") is not False:
            raise PermissionError("INVALID_DISCOVERY_RESULT")
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict) or not snapshot or any(
            not isinstance(n, str) or not isinstance(d, str) or not re.fullmatch(r"[0-9a-f]{64}", d)
            for n,d in snapshot.items()
        ):
            raise ValueError("INVALID_DISCOVERY_SNAPSHOT")
        conn.execute("DELETE FROM unlimited_tool_fingerprints WHERE provider=? AND tenant=? AND source_key=?",
                     (provider,tenant,key))
        conn.executemany("""INSERT INTO unlimited_tool_fingerprints
            (provider,tenant,source_key,tool_name,schema_digest) VALUES (?,?,?,?,?)""",
            [(provider,tenant,key,name,digest) for name,digest in snapshot.items()])
        return {**result, "durably_snapshotted": True, "source_key": key,
                "previous_count": len(previous), "state": "DRAFT_CATALOG_ONLY"}
