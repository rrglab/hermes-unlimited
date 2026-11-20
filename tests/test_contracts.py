import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from unlimited.contracts import CompanySpec, TaskReceipt


class ContractTests(unittest.TestCase):
    def test_justyou_required(self):
        with self.assertRaises(ValueError):
            CompanySpec("provider", "tenant", "company", "Name", "")

    def test_provider_and_tenant_distinct(self):
        company = CompanySpec("provider", "customer-tenant", "company", "Name", "binding")
        self.assertNotEqual(company.provider_id, company.tenant_id)

    def test_receipt_not_execution_authority(self):
        receipt = TaskReceipt("tenant", "company", "task", "completed", "sha256:example")
        self.assertEqual(receipt.status, "completed")
        self.assertFalse(hasattr(receipt, "authority_granted"))

    def test_plugin_skeleton_reports_not_ready(self):
        spec = importlib.util.spec_from_file_location("unlimited_plugin_entry", ROOT / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.get_status("test-profile")
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["identity_verified"])


if __name__ == "__main__":
    unittest.main()
