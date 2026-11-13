"""Tenant-owned, fail-closed provider connection registry.

Only references to customer-controlled secrets are stored. Secret material is
resolved at use time from a caller-supplied secret manager, never from SQLite.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal


@dataclass(frozen=True)
class CustomerConnection:
    tenant_id: str
    connection_id: str
    provider: Literal["smtp", "stripe"]
    secret_ref: str
    config: dict
    enabled: bool = True


class CustomerConnectionRegistry:
    def __init__(self, database: str | Path, verify_identity: Callable[[str, str], bool]):
        self.database = str(database)
        self.verify_identity = verify_identity
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS customer_connections (
                tenant_id TEXT NOT NULL, connection_id TEXT NOT NULL,
                provider TEXT NOT NULL, secret_ref TEXT NOT NULL,
                config_json TEXT NOT NULL, enabled INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, connection_id))''')

    def connect(self, *, tenant_id: str, identity: str, connection_id: str,
                provider: str, secret_ref: str, config: dict,
                authorized: bool = False) -> CustomerConnection:
        if authorized is not True or not tenant_id or not identity or not connection_id or \
                self.verify_identity(tenant_id, identity) is not True:
            raise PermissionError("CUSTOMER_CONNECTION_AUTHORIZATION_REQUIRED")
        if provider not in ("smtp", "stripe"):
            raise ValueError("CUSTOMER_PROVIDER_UNSUPPORTED")
        if not secret_ref.startswith("vault://") or len(secret_ref) < 10:
            raise ValueError("CUSTOMER_SECRET_VAULT_REFERENCE_REQUIRED")
        allowed = {"smtp": {"host", "port", "sender"}, "stripe": {"account_label"}}[provider]
        if set(config) - allowed:
            raise ValueError("CUSTOMER_CONNECTION_CONFIG_UNEXPECTED_FIELD")
        if provider == "smtp" and (not config.get("host") or not config.get("sender") or config.get("port", 465) != 465):
            raise ValueError("CUSTOMER_SMTP_TLS_CONFIGURATION_REQUIRED")
        record = CustomerConnection(tenant_id, connection_id, provider, secret_ref, dict(config))
        with sqlite3.connect(self.database) as db:
            db.execute('''INSERT INTO customer_connections VALUES (?,?,?,?,?,1)
                ON CONFLICT(tenant_id, connection_id) DO UPDATE SET
                provider=excluded.provider, secret_ref=excluded.secret_ref,
                config_json=excluded.config_json, enabled=1''',
                (tenant_id, connection_id, provider, secret_ref, json.dumps(config, sort_keys=True)))
        return record

    def get(self, *, tenant_id: str, identity: str, connection_id: str) -> CustomerConnection:
        if self.verify_identity(tenant_id, identity) is not True:
            raise PermissionError("CUSTOMER_CONNECTION_IDENTITY_DENIED")
        with sqlite3.connect(self.database) as db:
            row = db.execute('''SELECT provider, secret_ref, config_json, enabled
                FROM customer_connections WHERE tenant_id=? AND connection_id=?''',
                (tenant_id, connection_id)).fetchone()
        if not row or not row[3]:
            raise LookupError("CUSTOMER_CONNECTION_NOT_AVAILABLE")
        return CustomerConnection(tenant_id, connection_id, row[0], row[1], json.loads(row[2]), True)

    def disconnect(self, *, tenant_id: str, identity: str, connection_id: str,
                   authorized: bool = False) -> None:
        if authorized is not True or self.verify_identity(tenant_id, identity) is not True:
            raise PermissionError("CUSTOMER_CONNECTION_AUTHORIZATION_REQUIRED")
        with sqlite3.connect(self.database) as db:
            db.execute('''UPDATE customer_connections SET enabled=0
                WHERE tenant_id=? AND connection_id=?''', (tenant_id, connection_id))

    def resolve_adapter(self, *, tenant_id: str, identity: str, connection_id: str,
                        secret_resolver: Callable[[str, str], dict], smtp_factory=None,
                        stripe_client=None):
        from .external_effects import SMTPDeliveryAdapter, StripePaymentAdapter
        record = self.get(tenant_id=tenant_id, identity=identity, connection_id=connection_id)
        credentials = secret_resolver(tenant_id, record.secret_ref)
        if not isinstance(credentials, dict):
            raise PermissionError("CUSTOMER_SECRET_UNAVAILABLE")
        if record.provider == "smtp":
            return SMTPDeliveryAdapter(host=record.config["host"], port=record.config.get("port", 465),
                sender=record.config["sender"], username=credentials["username"],
                password=credentials["password"], smtp_factory=smtp_factory)
        return StripePaymentAdapter(api_key=credentials["api_key"], stripe_client=stripe_client)
