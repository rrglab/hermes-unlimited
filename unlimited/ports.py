"""Protocol boundaries for integrations; implementations are not bundled in skeleton."""
from typing import Protocol

from .contracts import CompanySpec, ServiceSpec, TaskReceipt


class IdentityVerifier(Protocol):
    def verify_justyou_binding(self, company: CompanySpec) -> bool: ...


class CompanyProvisioner(Protocol):
    def provision(self, company: CompanySpec) -> str: ...


class ServicePublisher(Protocol):
    def publish(self, tenant_id: str, service: ServiceSpec) -> str: ...


class TaskExecutor(Protocol):
    def submit(self, tenant_id: str, company_id: str, task_kind: str, payload: dict) -> TaskReceipt: ...


class ResultHarvester(Protocol):
    def read(self, tenant_id: str, task_id: str) -> TaskReceipt: ...


class BillingProvider(Protocol):
    def record_usage(self, tenant_id: str, receipt: TaskReceipt) -> str: ...
