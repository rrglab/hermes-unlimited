import pathlib
import sqlite3
import tempfile
import unittest

from unlimited.runtime import ProviderStore, UnverifiedIdentity


class ProviderFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProviderStore(pathlib.Path(self.temp.name) / "provider.sqlite",
                                   lambda provider, tenant, identity: identity == f"{provider}:{tenant}:verified")

    def tearDown(self):
        self.temp.cleanup()

    def _identity(self, tenant):
        return "owner:" + tenant + ":verified"

    def test_provider_customer_service_request(self):
        i = self._identity("customer-a")
        self.store.create_company("owner", "customer-a", "agency", "Agency", i)
        self.store.publish_service("owner", "customer-a", "agency", "research", "Research", 9900, "NOK", i)
        queued = self.store.request_service("owner", "customer-a", "agency", "req-01", "research",
                                            {"brief": "Market scan"}, i)
        self.assertEqual(queued, {"request": "req-01", "state": "queued", "executed": False})
        self.assertEqual(len(self.store.list_requests("owner", "customer-a", "agency", i)), 1)

    def test_fail_closed_missing_identity(self):
        with self.assertRaises(UnverifiedIdentity):
            self.store.create_company("owner", "customer-a", "agency", "Agency", "")

    def test_cross_tenant_cannot_read(self):
        i = self._identity("customer-a")
        self.store.create_company("owner", "customer-a", "agency", "Agency", i)
        self.assertEqual(self.store.list_companies("owner", "customer-b", self._identity("customer-b")), [])
        with self.assertRaises(UnverifiedIdentity):
            self.store.list_companies("owner", "customer-a", self._identity("customer-b"))

    def test_reject_duplicate_request_no_double_enqueue(self):
        i = self._identity("customer-a")
        self.store.create_company("owner", "customer-a", "agency", "Agency", i)
        self.store.publish_service("owner", "customer-a", "agency", "research", "Research", 0, "NOK", i)
        self.store.request_service("owner", "customer-a", "agency", "req-01", "research", {}, i)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.request_service("owner", "customer-a", "agency", "req-01", "research", {}, i)
        self.assertEqual(len(self.store.list_requests("owner", "customer-a", "agency", i)), 1)

    def test_invalid_service_scope_rejected(self):
        i = self._identity("customer-a")
        self.store.create_company("owner", "customer-a", "agency", "Agency", i)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.request_service("owner", "customer-a", "agency", "req-01", "missing", {}, i)

    def test_task_binding_and_result_are_tenant_scoped(self):
        i = self._identity("customer-a")
        self.store.create_company("owner", "customer-a", "agency", "Agency", i)
        self.store.publish_service("owner", "customer-a", "agency", "brief", "Brief", 0, "NOK", i)
        self.store.request_service("owner", "customer-a", "agency", "req-1", "brief", {}, i)
        self.store.attach_task("owner", "customer-a", "agency", "req-1", "kanban-1", i)
        self.store.attach_task("owner", "customer-a", "agency", "req-1", "kanban-1", i)
        with self.assertRaises(ValueError):
            self.store.attach_task("owner", "customer-a", "agency", "req-1", "kanban-2", i)
        self.store.record_task_result("owner", "customer-a", "agency", "req-1", "kanban-1",
                                      {"found": True, "status": "done", "completed": True,
                                       "independently_verified": False}, i)
        self.assertEqual(self.store.get_request("owner", "customer-a", "agency", "req-1", i)["state"], "done")
        self.assertIsNone(self.store.get_request("owner", "customer-b", "agency", "req-1",
                                                   self._identity("customer-b")))


if __name__ == "__main__":
    unittest.main()
