import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_agent = sys.modules.get("agent")
        self.previous_scope = sys.modules.get("agent.secret_scope")
        settings = {
            "HERMES_UNLIMITED_PROVIDER_ID": "owner",
            "HERMES_UNLIMITED_TENANT_ID": "tenant-a",
            "HERMES_UNLIMITED_JUSTYOU_IDENTITY": "@owner",
            "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": "session",
            "HERMES_UNLIMITED_REGISTRY_DB": str(pathlib.Path(self.temp.name) / "data.sqlite"),
        }
        self.settings = settings
        agent = types.ModuleType("agent")
        agent.__path__ = []
        scope = types.ModuleType("agent.secret_scope")
        scope.get_secret = lambda name, default="": settings.get(name, default)
        sys.modules["agent"] = agent
        sys.modules["agent.secret_scope"] = scope

        class SessionStore:
            def validate(self, token, audience, required_scope):
                return SimpleNamespace(valid=True, authority=False, address="@owner",
                                       audience=audience, scopes=("read-profile",))
        class Binding:
            identity, carrier, endpoint, version = "@owner", "hermes-profile", "hermes-profile:role-a", 1
            def digest(self):
                return "digest"
        class Resolver:
            def resolve(self, identity, **kwargs):
                return Binding(), SimpleNamespace(identity=identity, binding_digest="digest",
                                                  resolved_version=1, status="RESOLVED")
        self.ctx = SimpleNamespace(profile_name="role-a", justyou_session_store=SessionStore(),
                                   justyou_resolver=Resolver(), handlers={})
        def register_tool(name, toolset, schema, handler):
            self.ctx.handlers[name] = handler
        self.ctx.register_tool = register_tool
        self.ctx.get_config = lambda name, default="": settings.get(name, default)
        self.submissions = []
        self.kanban_unavailable = False
        outer = self
        class FakeKanban:
            def __init__(self, **_kwargs):
                pass
            def enqueue(self, **kwargs):
                if outer.kanban_unavailable:
                    raise RuntimeError("HERMES_KANBAN_UNAVAILABLE")
                outer.submissions.append(kwargs)
                return {"task_id": "task-" + str(len(outer.submissions))}
            def result(self, **kwargs):
                return {"found": True, "completed": True, "status": "done",
                        "independently_verified": False}
        self.patcher = patch("unlimited.hermes_kanban.HermesKanban", FakeKanban)
        self.patcher.start()

        spec = importlib.util.spec_from_file_location("hermes_unlimited_test_entry", ROOT / "__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        plugin.register(self.ctx)

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()
        for key, prior in (("agent", self.previous_agent), ("agent.secret_scope", self.previous_scope)):
            if prior is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prior

    def call(self, tool, args=None):
        return json.loads(self.ctx.handlers[tool](args or {}))

    def test_manifest_declares_all_registered_tools(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        tools_section = manifest.split("provides_tools:", 1)[1].split("\nrequires_env:", 1)[0]
        names = set(line.strip()[2:] for line in tools_section.splitlines()
                    if line.strip().startswith("- "))
        self.assertEqual(names, set(self.ctx.handlers),
                         "plugin.yaml must match registered tools exactly")

    def test_public_company_service_request_path(self):
        created = self.call("unlimited_company_create",
                            {"company_id": "company-a", "display_name": "Research Firm"})
        self.assertTrue(created["created"])
        service = self.call("unlimited_service_publish",
                            {"company_id": "company-a", "service_id": "brief",
                             "title": "Research brief", "price_minor": 9900, "currency": "NOK"})
        self.assertTrue(service["published"])
        req = self.call("unlimited_service_request",
                        {"company_id": "company-a", "service_id": "brief",
                         "request_id": "request-a", "payload": {"topic": "market"}})
        self.assertEqual(req["state"], "running")
        self.assertEqual(req["task_id"], "task-1")
        self.assertEqual(len(self.submissions), 1)
        result = self.call("unlimited_service_result", {"company_id": "company-a",
                                                      "request_id": "request-a"})
        self.assertTrue(result["completed"])
        self.assertFalse(result["independently_verified"])
        self.assertEqual(self.call("unlimited_company_list")["companies"][0]["company"], "company-a")

    def test_a2ui_loopback_bridge_calls_real_registered_hermes_handler(self):
        import threading
        import urllib.request
        from unlimited.a2ui_bridge import make_bridge, new_transport_token
        self.call("unlimited_company_create", {"company_id":"company-a", "display_name":"Live through Hermes"})
        token = new_transport_token()
        server = make_bridge(self.ctx.handlers["unlimited_a2ui_surface"], token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/surface?view=companies&surface_id=live"
            request = urllib.request.Request(url, headers={"Authorization":"Bearer "+token})
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertIn("Live through Hermes", response.read().decode())
            self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"]="@other"
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(blocked.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_a2ui_native_tool_is_read_only_and_tenant_scoped(self):
        self.call("unlimited_company_create", {"company_id": "company-a", "display_name": "Research Firm"})
        surface = self.call("unlimited_a2ui_surface", {"view": "companies", "surface_id": "companies_1"})
        self.assertEqual(surface["version"], "1.0")
        self.assertIn("Research Firm", json.dumps(surface))
        self.assertNotIn("action", json.dumps(surface))
        self.assertEqual(len(self.submissions), 0)
        invalid = self.call("unlimited_a2ui_surface", {"view": "companies", "company_id": "company-a", "surface_id": "x"})
        self.assertFalse(invalid["ok"])
        invalid = self.call("unlimited_a2ui_surface", {"view": "requests", "surface_id": "x"})
        self.assertFalse(invalid["ok"])
        self.settings["HERMES_UNLIMITED_TENANT_ID"] = "tenant-b"
        isolated = self.call("unlimited_a2ui_surface", {"view": "companies", "surface_id": "companies_2"})
        self.assertEqual(isolated["version"], "1.0")
        self.assertNotIn("Research Firm", json.dumps(isolated))

    def test_dispatch_idempotent_and_scoped(self):
        self.call("unlimited_company_create", {"company_id": "company-a", "display_name": "A"})
        self.call("unlimited_service_publish", {"company_id": "company-a", "service_id": "brief",
                                               "title": "Brief", "price_minor": 0, "currency": "NOK"})
        self.call("unlimited_service_request", {"company_id": "company-a", "service_id": "brief",
                                               "request_id": "req-1", "payload": {}})
        again = self.call("unlimited_service_dispatch", {"company_id": "company-a", "request_id": "req-1"})
        self.assertEqual(again["task_id"], "task-1")
        self.assertEqual(len(self.submissions), 1)
        self.settings["HERMES_UNLIMITED_TENANT_ID"] = "tenant-b"
        self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"] = "@owner"
        denied = self.call("unlimited_service_result", {"company_id": "company-a", "request_id": "req-1"})
        self.assertFalse(denied.get("found", False))

    def test_unavailable_kanban_keeps_request_for_retry(self):
        self.call("unlimited_company_create", {"company_id": "company-a", "display_name": "A"})
        self.call("unlimited_service_publish", {"company_id": "company-a", "service_id": "brief",
                                               "title": "Brief", "price_minor": 0, "currency": "NOK"})
        self.kanban_unavailable = True
        queued = self.call("unlimited_service_request", {"company_id": "company-a", "service_id": "brief",
                                                       "request_id": "req-1", "payload": {}})
        self.assertTrue(queued["dispatch_pending"])
        self.assertEqual(queued["state"], "queued")
        self.kanban_unavailable = False
        dispatched = self.call("unlimited_service_dispatch", {"company_id": "company-a", "request_id": "req-1"})
        self.assertEqual(dispatched["task_id"], "task-1")
        self.assertEqual(len(self.submissions), 1)

    def test_identity_mismatch_fails_all_writes(self):
        self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"] = "@other"
        response = self.call("unlimited_company_create",
                             {"company_id": "company-a", "display_name": "Research Firm"})
        self.assertFalse(response["ok"])

    def test_caller_cannot_choose_tenant(self):
        response = self.call("unlimited_company_create",
                             {"company_id": "company-a", "display_name": "Research Firm",
                              "tenant": "other"})
        self.assertEqual(response["reason"], "INVALID_ARGUMENTS")

    def test_community_adapter_discovery_is_static_and_nonexecuting(self):
        data=self.call("unlimited_adapter_discover")
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["count"],1)
        self.assertFalse(data["execution_enabled"])
        self.assertTrue(all(item["can_execute"] is False for item in data["adapters"]))
        self.assertFalse(self.call("unlimited_adapter_discover", {"tenant": "forged"})["ok"])
        self.assertEqual(self.call("unlimited_adapter_discover", {"id": "not-present"})["count"],0)

    def test_memory_recall_native_handler_fail_closed_and_read_only(self):
        import sqlite3
        response=self.call("unlimited_memory_recall", {"company_id":"company-a"})
        self.assertFalse(response["memory_available"])
        self.assertFalse(response["attestation_verified"])
        with sqlite3.connect(self.settings["HERMES_UNLIMITED_REGISTRY_DB"]) as db:
            db.execute("""CREATE TABLE company_memory (
                entry_id TEXT PRIMARY KEY, provider TEXT, tenant TEXT, company TEXT,
                task_kind TEXT, source_id TEXT, classification TEXT,
                independently_verified INTEGER, lesson TEXT, evidence_digest TEXT,
                cost_minor REAL, verified_value_minor INTEGER, created_at INTEGER)""")
            db.execute("INSERT INTO company_memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("memo-1","owner","tenant-a","company-a","triage","task-1",
                        "RECORDED_UNVERIFIED",0,"Read this later",None,0,0,1))
            db.execute("INSERT INTO company_memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("memo-2","owner","tenant-b","company-a","triage","task-2",
                        "RECORDED_UNVERIFIED",0,"Other tenant",None,0,0,2))
        result=self.call("unlimited_memory_recall", {"company_id":"company-a"})
        self.assertEqual([x["entry_id"] for x in result["entries"]],["memo-1"])
        self.assertFalse(result["attestation_verified"])
        self.assertFalse(result["entries"][0]["independent_attestation_checked"])
        self.assertFalse(self.call("unlimited_memory_recall", {"company_id":"company-a", "tenant":"tenant-b"})["ok"])
        self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"]="@other"
        self.assertFalse(self.call("unlimited_memory_recall", {"company_id":"company-a"})["ok"])

    def test_specialist_factory_requires_host_registry_and_no_effects(self):
        denied = self.call("unlimited_specialist_factory", {"operation":"discover", "toolset":"dns"})
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["reason"], "PermissionError")
        local = self.call("unlimited_specialist_factory", {"operation":"discover", "toolset":"hermes_unlimited"})
        self.assertEqual(local["source"], "LOCAL_PLUGIN_DECLARATION_ONLY")
        self.assertFalse(local["execution_authorized"])
        self.assertEqual(len(local["capabilities"]), len(self.ctx.handlers)-1)  # excludes this discovery tool
        self.assertTrue(all(x["effect"] == "unknown" and not x["availability_verified"] for x in local["capabilities"]))
        local_proposal = self.call("unlimited_specialist_factory", {"operation":"propose", "toolset":"hermes_unlimited",
                    "objective":"Review local catalog", "selected_tools":["unlimited_company_list"]})
        self.assertEqual(local_proposal["source"], "LOCAL_PLUGIN_DECLARATION_ONLY")
        self.assertFalse(local_proposal["execution_authorized"])
        class TrustedRegistry:
            def get_all_tool_names(self): return ["dns_read", "dns_write", "other"]
            def get_toolset_for_tool(self, name): return "dns" if name.startswith("dns_") else "other"
            def get_definitions(self, names, quiet=False):
                return [{"function": {"name": name, "parameters":
                        {"type":"object", "properties":{}}}} for name in names]
        self.ctx.tool_registry = TrustedRegistry()
        result = self.call("unlimited_specialist_factory", {"operation":"discover", "toolset":"dns"})
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(all(cap["effect"] == "unknown" for cap in result["capabilities"]))
        draft = self.call("unlimited_specialist_factory", {"operation":"propose", "toolset":"dns",
                    "objective":"Evaluate records", "selected_tools":["dns_read"]})
        self.assertEqual(draft["status"],"DRAFT_UNVERIFIED")
        self.assertFalse(draft["execution_authorized"])
        forged = self.call("unlimited_specialist_factory", {"operation":"discover", "toolset":"dns",
                           "tool_schemas":[{"name":"forged"}]})
        self.assertFalse(forged["ok"])
        self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"] = "@forged"
        denied_identity = self.call("unlimited_specialist_factory", {"operation":"discover", "toolset":"dns"})
        self.assertFalse(denied_identity["ok"])

    def test_economic_scenario_handler_no_false_authority(self):
        self.call("unlimited_company_create",{"company_id":"company-a", "display_name":"A"})
        self.call("unlimited_service_publish",{"company_id":"company-a", "service_id":"brief",
             "title":"Brief", "price_minor":1000, "currency":"NOK"})
        self.call("unlimited_service_request",{"company_id":"company-a", "service_id":"brief",
             "request_id":"req-1", "payload":{}})
        args = {"company_id":"company-a", "request_id":"req-1", "scenario_cap":"25"}
        missing=self.call("unlimited_economic_evaluate",args)
        self.assertEqual(missing["comparison"],"INSUFFICIENT_COST_INPUT")
        self.assertIsNone(missing["within_scenario_cap"])
        self.call("unlimited_oversight_costs",{"company_id":"company-a", "request_id":"req-1",
             "ai_cost":"12", "recovery_cost":"8"})
        result=self.call("unlimited_economic_evaluate",args)
        self.assertEqual(result["comparison"],"MODEL_INPUT_WITHIN_CAP")
        self.assertEqual(result["currency"],"NOK")
        self.assertEqual(result["difference"],"5")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["independently_verified"])
        self.assertIsNone(result["net_value"])
        self.assertFalse(self.call("unlimited_economic_evaluate",dict(args, tenant="other"))["ok"])
        self.settings["HERMES_UNLIMITED_JUSTYOU_IDENTITY"]="@forged"
        self.assertFalse(self.call("unlimited_economic_evaluate",args)["ok"])

    def test_unavailable_creative_backend_not_advertised(self):
        self.assertNotIn("unlimited_creative_render", self.ctx.handlers)
        self.assertNotIn("unlimited_creative_result", self.ctx.handlers)


if __name__ == "__main__":
    unittest.main()
