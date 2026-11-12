"""Optional real JustYou acceptance; run with PYTHONPATH pointing to JustYou.

The registry, challenge response, Ed25519 profile binding and plugin registry
are real. By default Kanban is stubbed; an opt-in isolated Hermes-home mode
uses the real native Kanban CLI without dispatching a model worker.
"""
import importlib.util
import os
import subprocess
import uuid
from contextlib import nullcontext
import json
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from identity_layer.immutable import ZERO_HASH, generate_signing_key, sign_state
    from protocol.authoritative_binding import AuthorityBinding, Ed25519Authority
    from registry.auth import ChallengeAuthenticator, sign_auth_challenge
    from registry.recovery import RecoveryStore
    from registry.server import RegistryHTTPServer
    from registry.session import SessionStore
    from registry.store import RegistryStore
except ImportError:
    Ed25519Authority = None

from unlimited.justyou_host import trusted_components


@unittest.skipIf(Ed25519Authority is None, "canonical JustYou package unavailable")
class LiveCustomerAcceptance(unittest.TestCase):
    def test_real_session_signed_binding_and_company_service(self):
        with tempfile.TemporaryDirectory() as root:
            state = pathlib.Path(root)
            db = state / "registry.db"
            registry = RegistryStore(str(db))
            recovery = RecoveryStore(registry, str(db))
            sessions = SessionStore(registry, str(db))
            auth = ChallengeAuthenticator(registry)
            server = RegistryHTTPServer(("127.0.0.1", 0), registry, recovery, auth, sessions)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root_private, root_public = generate_signing_key("test-root", role="root")
                device_private, device_public = generate_signing_key("test-device", role="device")
                identity = "@unlimited-public-synthetic"
                registry.publish(sign_state(
                    signers=(("test-root", root_private),), core_id="jy:unlimited:synthetic",
                    handle=identity, entity_kind="human", sequence=0,
                    previous_state_hash=ZERO_HASH,
                    active_keys=(root_public, device_public), signature_threshold=1,
                    continuity_ref="unlimited-public-acceptance"))
                challenge = auth.begin(identity, "hermes-unlimited")
                proof = sign_auth_challenge(challenge, device_private)
                session = sessions.issue(auth.verify(challenge.challenge_id, "test-device", proof))

                signer = Ed25519Authority("test-authority", Ed25519PrivateKey.generate())
                now = datetime.now(timezone.utc)
                binding = signer.sign_binding(AuthorityBinding(
                    identity=identity, version=1, carrier="hermes-profile",
                    endpoint="hermes-profile:acceptancepublic1111", endpoint_key_id="test-device",
                    authority_key_id="test-authority", valid_from=now - timedelta(minutes=1),
                    valid_until=now + timedelta(hours=1)))
                bindings = state / "bindings.json"
                bindings.write_text(json.dumps({"bindings": [{**binding.unsigned_payload(),
                                                                 "signature": binding.signature}],
                                                "announcements": []}))
                public_key = state / "authority.pub"
                public_key.write_text(signer.public_key_b64())
                token_file = state / "session.token"
                token_file.write_text(session.token)
                for file in (bindings, public_key, token_file):
                    file.chmod(0o600)
                live_kanban = os.environ.get("HERMES_UNLIMITED_LIVE_KANBAN") == "1"
                tenant = "synthetic-tenant-" + uuid.uuid4().hex[:8] if live_kanban else "synthetic-tenant"
                hermes_cli = os.environ.get("HERMES_UNLIMITED_HERMES_CLI", "hermes")
                if live_kanban:
                    hermes_home = os.environ.get("HERMES_HOME")
                    self.assertTrue(hermes_home, "isolated HERMES_HOME is mandatory")
                    self.assertNotEqual(pathlib.Path(hermes_home).resolve(),
                                        pathlib.Path.home() / ".hermes")
                    self.assertTrue(pathlib.Path(hermes_home).is_dir())
                    from unlimited.hermes_kanban import board_for
                    board = board_for("synthetic-provider", tenant)
                    prepared = subprocess.run(
                        [hermes_cli, "kanban", "boards", "create", board],
                        capture_output=True, text=True, timeout=45, check=False)
                    self.assertEqual(prepared.returncode, 0,
                                     prepared.stderr + prepared.stdout)
                settings = {
                    "HERMES_UNLIMITED_PROVIDER_ID": "synthetic-provider",
                    "HERMES_UNLIMITED_TENANT_ID": tenant,
                    "HERMES_UNLIMITED_HERMES_CLI": hermes_cli,
                    "HERMES_UNLIMITED_JUSTYOU_IDENTITY": identity,
                    "HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL":
                        f"http://127.0.0.1:{server.server_port}",
                    "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": session.token,
                    "JUSTYOU_BINDINGS_FILE": str(bindings),
                    "JUSTYOU_AUTHORITY_KEY_ID": "test-authority",
                    "JUSTYOU_AUTHORITY_KEY_FILE": str(public_key),
                    "HERMES_UNLIMITED_REGISTRY_DB": str(state / "companies.db"),
                }
                secret = lambda name, default="": settings.get(name, default)
                ctx = SimpleNamespace(profile_name="acceptancepublic1111", handlers={})
                ctx.get_config = lambda name, default="": settings.get(name, default)
                store, resolver, token = trusted_components(ctx, secret)
                from unlimited.justyou import JustYouVerifier
                evidence = JustYouVerifier(store, resolver, ctx.profile_name, token).verify()
                self.assertTrue(evidence["verified"], evidence)
                self.assertEqual(evidence["identity"], identity)

                agent, scope = types.ModuleType("agent"), types.ModuleType("agent.secret_scope")
                agent.__path__ = []
                scope.get_secret = secret
                ctx.register_tool = lambda name, toolset, schema, handler: ctx.handlers.__setitem__(name, handler)

                class FakeKanban:
                    def __init__(self, **kwargs):
                        pass
                    def enqueue(self, **kwargs):
                        return {"task_id": "synthetic-task-1"}
                    def result(self, **kwargs):
                        return {"found": True, "completed": True, "status": "done",
                                "independently_verified": False}

                spec = importlib.util.spec_from_file_location(
                    "hermes_unlimited_live", pathlib.Path(__file__).resolve().parents[1] / "__init__.py")
                plugin = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plugin)
                kanban_override = (nullcontext() if live_kanban else
                                   patch("unlimited.hermes_kanban.HermesKanban", FakeKanban))
                with patch.dict(sys.modules, {"agent": agent, "agent.secret_scope": scope}), \
                     kanban_override:
                    plugin.register(ctx)
                    def call(name, params):
                        return json.loads(ctx.handlers[name](params))
                    self.assertTrue(call("unlimited_company_create", {
                        "company_id": "synthetic-company", "display_name": "Synthetic Test"})["created"])
                    self.assertTrue(call("unlimited_service_publish", {
                        "company_id": "synthetic-company", "service_id": "brief", "title": "Brief",
                        "price_minor": 0, "currency": "NOK"})["published"])
                    result = call("unlimited_service_request", {
                        "company_id": "synthetic-company", "service_id": "brief",
                        "request_id": "synthetic-request", "payload": {"test": True}})
                    if live_kanban:
                        self.assertTrue(result["task_id"].startswith("t_"), result)
                        observed = call("unlimited_service_result", {
                            "company_id": "synthetic-company", "request_id": "synthetic-request"})
                        self.assertTrue(observed["found"], observed)
                        self.assertFalse(observed["completed"], observed)
                    else:
                        self.assertEqual(result["task_id"], "synthetic-task-1")
                        self.assertTrue(call("unlimited_service_result", {
                            "company_id": "synthetic-company", "request_id": "synthetic-request"})["completed"])
                    settings["HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN"] = "revoked-or-invalid"
                    self.assertFalse(call("unlimited_company_create", {
                        "company_id": "denied", "display_name": "Denied"})["ok"])
            finally:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()
                sessions.close()
                recovery.close()
                registry.close()


if __name__ == "__main__":
    unittest.main()
