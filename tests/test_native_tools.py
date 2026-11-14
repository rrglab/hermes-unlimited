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

    def test_autonomous_tool_requires_host_authorization_and_real_worker(self):
        self.call("unlimited_company_create", {"company_id": "company-a", "display_name": "A"})
        mission = {"company_id": "company-a", "objective_id": "mission-1",
                   "title": "Real customer outcome", "target_value_minor": 5000}
        cycle = {"company_id": "company-a", "strategic_direction": "deliver",
                 "candidates": [{"objective_id": "mission-1", "title": "Real outcome",
                                 "target_value_minor": 5000}]}
        for name, args in (("unlimited_mission_run", mission),
                           ("unlimited_company_cycle", cycle)):
            result = self.call(name, args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "PermissionError")
        self.ctx.authorize_mission = lambda *args: True
        for name, args in (("unlimited_mission_run", mission),
                           ("unlimited_company_cycle", cycle)):
            result = self.call(name, args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "RuntimeError")
        # Even when a host worker exists, an independent host verifier is required.
        self.ctx.mission_worker = lambda *_a: None
        for name, args in (("unlimited_mission_run", mission),
                           ("unlimited_company_cycle", cycle)):
            result = self.call(name, args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "RuntimeError")
        self.assertEqual(len(self.submissions), 0)

    def test_unauthorized_live_worker_flag_does_not_enable_execution(self):
        """A legacy config flag cannot substitute for an approved host worker."""
        from unittest.mock import patch
        self.call("unlimited_company_create", {"company_id": "company-a", "display_name": "A"})
        mission = {"company_id": "company-a", "objective_id": "mission-live-denied",
                   "title": "No unauthorized execution", "target_value_minor": 5000}
        self.ctx.authorize_mission = lambda *args: True
        self.ctx.mission_worker = None
        with patch.dict("os.environ", {"HERMES_UNLIMITED_LIVE_WORKER": "1"}):
            result = self.call("unlimited_mission_run", mission)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "RuntimeError")
        self.assertEqual(len(self.submissions), 0)

    def test_manifest_declares_all_registered_tools(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        tools_section = manifest.split("provides_tools:", 1)[1].split("\nprovides_hooks:", 1)[0]
        names = set(line.strip()[2:] for line in tools_section.splitlines()
                    if line.strip().startswith("- "))
        self.assertEqual(names, set(self.ctx.handlers),
                         "plugin.yaml must match registered tools exactly")

    def test_manifest_declares_feedback_hooks(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        hooks_section = manifest.split("provides_hooks:", 1)[1].split("\nrequires_env:", 1)[0]
        names = {line.strip()[2:] for line in hooks_section.splitlines()
                 if line.strip().startswith("- ")}
        self.assertEqual(names, {"post_api_request", "post_tool_call", "on_session_end"})

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

    def test_unavailable_creative_backend_not_advertised(self):
        self.assertNotIn("unlimited_creative_render", self.ctx.handlers)
        self.assertNotIn("unlimited_creative_result", self.ctx.handlers)


if __name__ == "__main__":
    unittest.main()
