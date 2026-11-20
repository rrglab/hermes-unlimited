"""Offline tests for the fail-closed A2UI 1.0 presentation boundary."""
import json
import tempfile
import unittest
from pathlib import Path

from unlimited.a2ui_adapter import (
    BASIC_CATALOG,
    A2UIValidationError,
    company_surface,
    delete_surface,
    encode_jsonl,
    request_surface,
    validate_envelope,
)
from unlimited.runtime import ProviderStore, UnverifiedIdentity


class A2UIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProviderStore(
            Path(self.tmp.name) / "companies.db",
            lambda provider, tenant, identity:
                provider == "provider1" and tenant == "tenant1" and identity == "valid",
        )
        self.store.create_company("provider1", "tenant1", "acme", "Acme Ltd", "valid")
        self.store.publish_service("provider1", "tenant1", "acme", "support", "Support", 100, "NOK", "valid")
        self.store.request_service("provider1", "tenant1", "acme", "req1", "support", {}, "valid")

    def tearDown(self):
        self.tmp.cleanup()

    def test_company_surface_uses_v1_0_envelope_and_basic_catalog(self):
        msg = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        surface = msg["createSurface"]
        self.assertEqual(msg["version"], "1.0")
        self.assertEqual(surface["catalogId"], BASIC_CATALOG)
        self.assertFalse(surface["sendDataModel"])
        self.assertEqual(surface["components"][0]["id"], "root")
        self.assertIn("Acme Ltd", str(surface["components"]))
        self.assertEqual(surface["dataModel"], {})

    def test_request_surface_is_read_only_and_does_not_export_results(self):
        msg = request_surface(self.store, "provider1", "tenant1", "acme", "valid", surface_id="requests_1")
        wire = json.dumps(msg)
        self.assertIn("req1", wire)
        self.assertIn("queued", wire)
        self.assertNotIn("payload", wire)
        self.assertNotIn("callRendererFunction", wire)
        self.assertNotIn("action", wire)

    def test_unverified_identity_fails_closed(self):
        with self.assertRaises(UnverifiedIdentity):
            company_surface(self.store, "provider1", "tenant1", "forged", surface_id="companies_1")
        with self.assertRaises(UnverifiedIdentity):
            request_surface(self.store, "provider1", "tenant2", "acme", "valid", surface_id="requests_1")

    def test_invalid_surface_id_rejected(self):
        for name in ("", "../other", "some-id", "other tenant", "a" * 65):
            with self.subTest(name=name), self.assertRaises(A2UIValidationError):
                company_surface(self.store, "provider1", "tenant1", "valid", surface_id=name)

    def test_actions_and_untrusted_components_rejected(self):
        msg = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        msg["createSurface"]["components"].append({
            "id": "execute", "component": "Button",
            "child": "heading", "action": {"event": {"name": "executeTask"}},
        })
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)
        msg["createSurface"]["components"][-1]["component"] = "Html"
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)

    def test_duplicate_ids_and_missing_children_rejected(self):
        msg = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        msg["createSurface"]["components"].append({"id": "heading", "component": "Text", "text": "repeat"})
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)
        msg["createSurface"]["components"].pop()
        msg["createSurface"]["components"][0]["children"] = ["missing"]
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)

    def test_wrong_version_theme_and_unexpected_rpc_rejected(self):
        msg = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        msg["version"] = "0.9"
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)
        msg["version"] = "1.0"
        msg["createSurface"]["theme"] = {}
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)
        with self.assertRaises(A2UIValidationError):
            validate_envelope({"version": "1.0", "callRendererFunction": {"functionCallId": "x"}})

    def test_jsonl_framing_and_delete(self):
        first = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        wire = encode_jsonl([first, delete_surface("companies_1")])
        rows = [json.loads(row) for row in wire.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertIn("deleteSurface", rows[1])

    def test_oversize_message_fails(self):
        msg = company_surface(self.store, "provider1", "tenant1", "valid", surface_id="companies_1")
        msg["createSurface"]["dataModel"] = {"secret": "x" * 70000}
        with self.assertRaises(A2UIValidationError):
            validate_envelope(msg)


if __name__ == "__main__":
    unittest.main()
