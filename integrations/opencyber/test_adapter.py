"""Offline unit tests: python -m unittest discover -s integrations/opencyber -p 'test_*.py' -v."""
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("opencyber_adapter", pathlib.Path(__file__).with_name("adapter.py"))
module = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = module
spec.loader.exec_module(module)


class OpenCyberAdapterTests(unittest.TestCase):
    def tool(self, **overrides):
        oc = {"contract_schema_version": 1, "shape": "observe", "effects": ["network"], "scope": "url", "requires_engagement": True, "returns_target_content": True}
        oc.update(overrides)
        return {"name": "oc_http_request", "_meta": {"opencyber": oc}}

    def result(self, status="complete", ok=True):
        data = {"ok": ok, "contract": {"schema_version": 1, "tool": "oc_http_request"}, "coverage": {"status": status}, "limitations": [], "provenance": {"untrusted_content": True, "source": "target"}, "evidence": {"sha256": "a"*64}}
        if not ok:
            data["error"] = {"code": "scope_denied"}
        return data

    def test_capability_requires_clearance(self):
        cap = module.read_tool_capability(self.tool())
        self.assertTrue(cap.requires_external_clearance)
        self.assertEqual(cap.scope, "url")

    def test_self_declared_empty_effects_cannot_bypass_execution_clearance(self):
        for shape in ("execute", "manage", "workflow"):
            with self.subTest(shape=shape):
                cap = module.read_tool_capability(self.tool(
                    shape=shape, effects=[], scope="none",
                    requires_engagement=False, returns_target_content=False
                ))
                self.assertTrue(cap.requires_external_clearance)

    def test_unknown_effect_fails_closed(self):
        with self.assertRaises(module.ContractError):
            module.read_tool_capability(self.tool(effects=["network", "new_effect"]))

    def test_missing_metadata_fails_closed(self):
        with self.assertRaises(module.ContractError):
            module.read_tool_capability({"name": "oc_http_request"})

    def test_partial_is_not_complete(self):
        result = module.assess_result(self.result("partial"), expected_tool="oc_http_request")
        self.assertEqual(result.outcome, "INCOMPLETE")
        self.assertEqual(result.coverage, "partial")

    def test_refusal(self):
        result = module.assess_result(self.result("unknown", False), expected_tool="oc_http_request")
        self.assertEqual(result.outcome, "REFUSED")
        self.assertEqual(result.error_code, "scope_denied")

    def test_wrong_tool_fails_closed(self):
        with self.assertRaises(module.ContractError):
            module.assess_result(self.result(), expected_tool="oc_nmap")

    def test_bad_digest_fails_closed(self):
        data = self.result()
        data["evidence"]["sha256"] = "oops"
        with self.assertRaises(module.ContractError):
            module.assess_result(data, expected_tool="oc_http_request")

    def test_offline_command_no_shell(self):
        self.assertEqual(module.offline_stdio_command()[:3], ("docker", "exec", "-i"))
        with self.assertRaises(module.ContractError):
            module.offline_stdio_command("name;curl")


if __name__ == "__main__":
    unittest.main()
