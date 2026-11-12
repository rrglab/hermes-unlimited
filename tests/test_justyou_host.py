import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unlimited.justyou_host import LoopbackSessionStore, trusted_components


class HostBridgeTests(unittest.TestCase):
    def test_loopback_only_no_redirects_or_remote_host(self):
        for url in ("https://127.0.0.1:9999", "http://example.com:9999",
                    "http://127.0.0.1:9999/path", "http://localhost:9999/?x=1",
                    "http://127.0.0.1", "http://user@localhost:9999"):
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

    def test_trusted_profile_settings_can_load_without_host_fields(self):
        settings = {"HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL": "http://127.0.0.1:9999",
                    "HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN": "session",
                    "JUSTYOU_BINDINGS_FILE": "/private/bindings",
                    "JUSTYOU_AUTHORITY_KEY_ID": "key",
                    "JUSTYOU_AUTHORITY_KEY_FILE": "/private/key"}
        with patch("unlimited.justyou_host.load_resolver", return_value="verified-resolver") as loader:
            store, resolver, token = trusted_components(
                SimpleNamespace(), lambda name, default="": settings.get(name, default))
        self.assertIsInstance(store, LoopbackSessionStore)
        self.assertEqual((resolver, token), ("verified-resolver", "session"))
        loader.assert_called_once_with("/private/bindings", "key", "/private/key", "ed25519")


if __name__ == "__main__":
    unittest.main()
