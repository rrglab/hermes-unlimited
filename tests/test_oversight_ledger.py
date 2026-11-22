import sqlite3
import tempfile
import unittest
from pathlib import Path

from unlimited.oversight_ledger import OversightLedger
from unlimited.runtime import ProviderStore


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

    def test_report_carries_service_currency_and_input_provenance(self):
        self.ledger.record("provider", "tenant", "company", "request", "entry-one",
                           "pre_control", "30", "60", "identity")
        recorded = self.ledger.record_costs("provider", "tenant", "company", "request",
                                            "10", "2", "identity")
        report = self.ledger.report("provider", "tenant", "company", "request", "identity")
        self.assertEqual(recorded["currency"], "USD")
        self.assertEqual(report["currency"], "USD")
        self.assertEqual(report["cost_input_provenance"], "MODEL_SUBMITTED_UNVERIFIED")
        self.assertFalse(report["independently_verified"])
        self.assertIsNone(report["net_value"])

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record("provider","tenant","company","request","entry-nan",
                               "pre_control","NaN","60","identity")
        with self.assertRaises(ValueError):
            self.ledger.record_costs("provider","tenant","company","request",
                                     "Infinity","0","identity")

    def test_cost_report_is_tenant_scoped(self):
        self.ledger.record_costs("provider","tenant","company","request","2","3","identity")
        with self.assertRaises(ValueError):
            self.ledger.report("provider","tenant","company","other-request","identity")

    def test_wrong_identity_rejected(self):
        with self.assertRaises(PermissionError):
            self.ledger.report("provider","tenant","company","request","imposter")

    def test_duplicate_entry_rejected(self):
        args=("provider","tenant","company","request","entry-one","pre_control","5","60","identity")
        self.ledger.record(*args)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.record(*args)

    def test_cost_revisions_are_append_only_and_audited(self):
        r1 = self.ledger.record_costs("provider", "tenant", "company", "request", "500.00", "100.00", "identity")
        r2 = self.ledger.record_costs("provider", "tenant", "company", "request", "0", "0", "identity")
        self.assertEqual(r1["revision"], 1)
        self.assertEqual(r2["revision"], 2)
        report = self.ledger.report("provider", "tenant", "company", "request", "identity")
        self.assertEqual(report["cost_revisions"], 2)
        self.assertEqual(len(report["cost_history"]), 2)
        self.assertEqual(report["cost_history"][0]["ai_cost"], "500.00")
        self.assertEqual(report["cost_history"][0]["recovery_cost"], "100.00")
        self.assertEqual(report["cost_history"][1]["ai_cost"], "0")
        self.assertEqual(report["total_cost"], "0")

    def test_unbounded_and_extreme_amounts_rejected(self):
        for bad in ("1e999999", "1000000000001", "-1", "9" * 45, True, None, ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.ledger.record_costs("provider", "tenant", "company", "request", bad, "0", "identity")
                with self.assertRaises(ValueError):
                    self.ledger.record("provider", "tenant", "company", "request", "e-bad",
                                       "pre_control", bad, "10", "identity")


if __name__ == "__main__":
    unittest.main()
