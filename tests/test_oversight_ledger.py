import tempfile
import unittest
from pathlib import Path
from unlimited.runtime import ProviderStore
from unlimited.oversight_ledger import OversightLedger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProviderStore(str(Path(self.tmp.name) / "registry.sqlite"),
                                   lambda p,t,i: (p,t,i)==("provider","tenant","identity"))
        self.store.create_company("provider","tenant","company","Company","identity")
        self.store.publish_service("provider","tenant","company","service","Service",100,"USD","identity")
        self.store.request_service("provider","tenant","company","request","service",{},"identity")
        self.ledger = OversightLedger(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scoped_accounting_without_false_verification(self):
        self.ledger.record("provider","tenant","company","request","entry-one",
                           "post_review","30","60","identity")
        self.ledger.record_costs("provider","tenant","company","request","10","5","identity")
        result = self.ledger.report("provider","tenant","company","request","identity")
        self.assertEqual(result["oversight_cost"], "30")
        self.assertEqual(result["total_cost"], "45")
        self.assertIsNone(result["net_value"])
        self.assertEqual(result["verification_status"], "UNVERIFIED")

    def test_wrong_identity_rejected(self):
        with self.assertRaises(PermissionError):
            self.ledger.report("provider","tenant","company","request","imposter")

    def test_duplicate_entry_rejected(self):
        args=("provider","tenant","company","request","entry-one","pre_control","5","60","identity")
        self.ledger.record(*args)
        with self.assertRaises(Exception):
            self.ledger.record(*args)


if __name__ == "__main__":
    unittest.main()
