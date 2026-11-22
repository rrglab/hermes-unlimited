import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from unlimited.authoritative_binding import AuthorityBinding, Ed25519Authority
from unlimited.justyou_host import (
    LoopbackSessionStore,
    _private_bytes,
    load_resolver,
    trusted_components,
)


class HostBridgeTests(unittest.TestCase):
    def test_loopback_only_no_redirects_or_remote_host(self):
        for url in ("https://127.0.0.1:9999", "http://example.com:9999",
                    "http://127.0.0.1:9999/path", "http://localhost:9999/?x=1",
                    "http://localhost:9999", "http://[::1]:9999",
                    "http://169.254.169.254:80",
                    "http://127.0.0.1", "http://user@127.0.0.1:9999"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LoopbackSessionStore(url)
        self.assertEqual(LoopbackSessionStore("http://127.0.0.1:9999").url,
                         "http://127.0.0.1:9999/session/validate")

    def test_host_injection_preserved(self):
        store, resolver = object(), object()
        ctx = SimpleNamespace(justyou_session_store=store,
                              justyou_resolver=resolver, justyou_session_token="host-token")
        actual = trusted_components(ctx, lambda name, default="": default)
        self.assertEqual(actual, (store, resolver, "host-token"))

    def test_plugin_file_path_fallback_is_ignored(self):
        settings = {"HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL": "http://127.0.0.1:9999",
                    "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": "session",
                    "JUSTYOU_BINDINGS_FILE": "/private/bindings",
                    "JUSTYOU_AUTHORITY_KEY_ID": "key",
                    "JUSTYOU_AUTHORITY_KEY_FILE": "/private/key"}
        ctx = SimpleNamespace(get_config=lambda name, default="": settings.get(name, default))
        store, resolver, token = trusted_components(
            ctx, lambda name, default="": settings.get(name, default))
        self.assertIsInstance(store, LoopbackSessionStore)
        self.assertIsNone(resolver)
        self.assertEqual(token, "session")

    def test_signed_profile_settings_verify_against_host_public_key(self):
        key_id = "k-1"
        signer = Ed25519Authority(key_id, Ed25519PrivateKey.generate())
        now = datetime.now(timezone.utc)
        binding = signer.sign_binding(AuthorityBinding(
            identity="@owner", version=1, carrier="hermes-profile",
            endpoint="hermes-profile:role-a", endpoint_key_id="device",
            authority_key_id=key_id, valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(hours=1)))
        settings = {
            "HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL": "http://127.0.0.1:9999",
            "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": "session",
            "HERMES_UNLIMITED_JUSTYOU_AUTHORITY_PUBLIC_KEY": signer.public_key_b64(),
            "JUSTYOU_TRUSTED_AUTHORITY_KEY_ID": key_id,
            "JUSTYOU_SIGNED_BINDINGS_JSON": json.dumps({
                "bindings": [{**binding.unsigned_payload(), "signature": binding.signature}],
                "announcements": [],
            }),
        }
        ctx = SimpleNamespace(get_config=lambda name, default="": settings.get(name, default))
        store, resolver, token = trusted_components(
            ctx, lambda name, default="": settings.get(name, default))
        self.assertIsInstance(store, LoopbackSessionStore)
        self.assertIsNotNone(resolver)
        self.assertEqual(token, "session")
        resolved, _ = resolver.resolve("@owner", now=now)
        self.assertEqual(resolved.digest(), binding.digest())

    def test_private_bytes_rejects_symlinks_hardlinks_and_group_readable_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            target = root / "secret.pub"
            target.write_bytes(b"abc")
            target.chmod(0o600)
            self.assertEqual(_private_bytes(str(target)), b"abc")

            sym = root / "sym.pub"
            sym.symlink_to(target)
            with self.assertRaises(PermissionError):
                _private_bytes(str(sym))

            target.chmod(0o640)
            with self.assertRaises(PermissionError):
                _private_bytes(str(target))
            target.chmod(0o600)

            hard = root / "hard.pub"
            hard.hardlink_to(target)
            with self.assertRaises(PermissionError):
                _private_bytes(str(target))
            hard.unlink()
            self.assertEqual(_private_bytes(str(target)), b"abc")

            # Host provisioning helper still works on valid private files
            signer = Ed25519Authority("k1", Ed25519PrivateKey.generate())
            kfile = root / "auth.pub"
            kfile.write_text(signer.public_key_b64(), encoding="ascii")
            kfile.chmod(0o600)
            bfile = root / "bindings.json"
            bfile.write_text('{"bindings":[],"announcements":[]}', encoding="utf-8")
            bfile.chmod(0o600)
            self.assertIsNotNone(load_resolver(str(bfile), "k1", str(kfile)))


if __name__ == "__main__":
    unittest.main()
