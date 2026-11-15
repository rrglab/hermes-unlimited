import unittest

from unlimited.integrations import integration_catalog, integration_for


class IntegrationCatalogTests(unittest.TestCase):
    def test_optional_adapters_are_discoverable_without_claiming_execution(self):
        catalog = integration_catalog()
        self.assertEqual(len(catalog), 8)
        self.assertEqual(len({entry["key"] for entry in catalog}), 8)
        self.assertTrue(all(not entry["can_execute"] for entry in catalog))

    def test_upstream_boundaries(self):
        self.assertEqual(integration_for("postiz").license, "AGPL-3.0")
        self.assertEqual(integration_for("open-seo").interface, "mcp")
        self.assertEqual(integration_for("ghost").interface, "admin_api")
        self.assertEqual(integration_for("comfyui").interface, "http_api")
        self.assertEqual(integration_for("nvidia-openshell").interface, "valo_gateway_runtime_adapter")
        self.assertEqual(integration_for("nvidia-openshell").license, "Apache-2.0")
        self.assertFalse(integration_for("nvidia-openshell").can_execute)
        self.assertEqual(integration_for("nebius").role, "optional_compute_host")
        self.assertFalse(integration_for("nebius").can_execute)
        self.assertIsNone(integration_for("hyperagent"))

    def test_callers_cannot_mutate_catalog(self):
        catalog = integration_catalog()
        catalog[0]["can_execute"] = True
        self.assertFalse(integration_catalog()[0]["can_execute"])


if __name__ == "__main__":
    unittest.main()
