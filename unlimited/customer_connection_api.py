"""Framework-neutral self-service connection controller for host UI/API integration."""
from __future__ import annotations
import re
from .customer_connections import CustomerConnectionRegistry


class CustomerConnectionController:
    def __init__(self, registry: CustomerConnectionRegistry, authenticate_session):
        self.registry = registry
        self.authenticate_session = authenticate_session

    def _scope(self, session):
        tenant, actor = self.authenticate_session(session)
        if not tenant or not actor or self.registry.verify_identity(tenant, actor) is not True:
            raise PermissionError('CUSTOMER_SESSION_REQUIRED')
        return tenant, actor

    def connect(self, session, payload: dict) -> dict:
        tenant, actor = self._scope(session)
        cid = payload.get('connection_id', '')
        ref = payload.get('secret_ref', '')
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cid):
            raise ValueError('CONNECTION_ID_INVALID')
        if not isinstance(ref, str) or not ref.startswith(f'vault://{tenant}/'):
            raise PermissionError('TENANT_SECRET_REFERENCE_REQUIRED')
        record = self.registry.connect(tenant_id=tenant, identity=actor,
            connection_id=cid, provider=payload.get('provider',''),
            secret_ref=ref, config=payload.get('config',{}), authorized=True)
        return {'connection_id':record.connection_id,'provider':record.provider,'enabled':True}

    def get(self, session, connection_id: str) -> dict:
        tenant, actor = self._scope(session)
        record = self.registry.get(tenant_id=tenant, identity=actor, connection_id=connection_id)
        return {'connection_id':record.connection_id,'provider':record.provider,
                'enabled':record.enabled,'config':record.config}

    def disconnect(self, session, connection_id: str) -> None:
        tenant, actor = self._scope(session)
        self.registry.disconnect(tenant_id=tenant, identity=actor,
                                 connection_id=connection_id, authorized=True)
