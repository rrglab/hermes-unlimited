"""Offline regressions for publicly reported Hermes Unlimited QA defects."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from unlimited.comfyui import ComfyUI
from unlimited.justyou_host import LoopbackSessionStore, _private_bytes
from unlimited.oversight_ledger import OversightLedger
from unlimited.runtime import ProviderStore
from unlimited.tools import register_company_tools


class PublicQASecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProviderStore(
            Path(self.temp.name) / "qa.sqlite",
            lambda provider, tenant, identity:
                (provider, tenant, identity) == ("provider", "tenant", "identity"),
        )
        self.store.create_company("provider", "tenant", "company", "Company", "identity")
        self.store.publish_service(
            "provider", "tenant", "company", "service", "Service", 10, "USD", "identity"
        )
        self.store.request_service(
            "provider", "tenant", "company", "request", "service", {}, "identity"
        )

    def test_duplicate_errors_return_safe_structured_json(self):
        handlers = {}
        ctx = SimpleNamespace(profile_name="role-a")
        ctx.register_tool = lambda name, toolset, schema, handler: handlers.__setitem__(name, handler)
        register_company_tools(
            ctx, lambda key, default="": {
                "HERMES_UNLIMITED_PROVIDER_ID": "provider",
                "HERMES_UNLIMITED_REGISTRY_DB": str(Path(self.temp.name) / "qa.sqlite"),
            }.get(key, default),
            lambda: ("tenant", {"verified": True, "identity": "identity"}),
        )
        duplicate = json.loads(handlers["unlimited_company_create"](
            {"company_id": "company", "display_name": "Again"}
        ))
        self.assertEqual(duplicate, {"ok": False, "reason": "REGISTRY_CONFLICT"})
        huge = json.loads(handlers["unlimited_service_publish"]({
            "company_id": "company", "service_id": "other",
            "title": "Other", "price_minor": 10**25, "currency": "USD",
        }))
        self.assertEqual(huge, {"ok": False, "reason": "ValueError"})

    def test_oversight_rejects_unbounded_decimal_and_keeps_audit(self):
        ledger = OversightLedger(self.store)
        args = ("provider", "tenant", "company", "request")
        with self.assertRaises(ValueError):
            ledger.record(*args, "oversight", "post_review", "1e999999", "1", "identity")
        with self.assertRaises(ValueError):
            ledger.record_costs(*args, "1e999999", "0", "identity")
        ledger.record_costs(*args, "500", "100", "identity")
        ledger.record_costs(*args, "0", "0", "identity")
        with self.store._db() as db:
            rows = db.execute(
                "SELECT ai_cost,recovery_cost FROM oversight_cost_audit ORDER BY rowid"
            ).fetchall()
        self.assertEqual(rows, [("500", "100"), ("0", "0")])

    def test_bounded_human_oversight_does_not_crash_report(self):
        ledger = OversightLedger(self.store)
        args = ("provider", "tenant", "company", "request")
        with self.assertRaises(ValueError):
            ledger.record(*args, "entry", "pre_control", "1000000000000",
                          "1000000000000", "identity")
        self.assertEqual(ledger.report(*args, "identity")["total_cost"], "0")

    def test_comfyui_rejects_link_local_and_remote_hosts(self):
        for url in ("http://169.254.169.254", "http://127.0.0.2:8188",
                    "http://localhost:8188", "https://example.org"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ComfyUI(url)
        self.assertEqual(ComfyUI().base_url, "http://127.0.0.1:8188")

    def test_private_file_rejects_symlinks_and_group_access(self):
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("O_NOFOLLOW not supported")
        secret = Path(self.temp.name) / "bindings.json"
        secret.write_text('{"bindings":[]}', encoding="utf-8")
        secret.chmod(0o600)
        self.assertIn(b"bindings", _private_bytes(secret))
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(secret)
        with self.assertRaises(PermissionError):
            _private_bytes(link)
        secret.chmod(0o640)
        with self.assertRaises(PermissionError):
            _private_bytes(secret)

    def test_loopback_dns_alias_not_trusted(self):
        with self.assertRaises(ValueError):
            LoopbackSessionStore("http://localhost:8999")

    def test_missing_ai_costs_can_never_prove_within_cap(self):
        from unlimited.economic_scenario import evaluate_cost_scenario
        ledger = OversightLedger(self.store)
        ledger.record("provider", "tenant", "company", "request",
                      "entry", "pre_control", "6", "100", "identity")
        result = evaluate_cost_scenario(
            ledger, "provider", "tenant", "company", "request", "identity", scenario_cap="100"
        )
        self.assertEqual(result["comparison"], "INSUFFICIENT_COST_INPUT")
        self.assertIsNone(result["within_scenario_cap"])

    def test_economic_scenario_counts_only_recorded_human_cost(self):
        from unlimited.economic_scenario import evaluate_cost_scenario
        ledger = OversightLedger(self.store)
        ledger.record("provider", "tenant", "company", "request",
                      "entry", "pre_control", "30", "100", "identity")
        result = evaluate_cost_scenario(
            ledger, "provider", "tenant", "company", "request", "identity", scenario_cap="10"
        )
        self.assertEqual(result["comparison"], "MODEL_INPUT_OVER_CAP")
        self.assertFalse(result["within_scenario_cap"])


if __name__ == "__main__":
    unittest.main()
