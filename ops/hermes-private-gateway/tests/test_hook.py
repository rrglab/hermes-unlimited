"""Offline safety and idempotency tests for Hermes private gateway hook."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

HOOK = Path(__file__).resolve().parents[1] / "hook" / "handler.py"
spec = importlib.util.spec_from_file_location("hermes_private_gateway_hook", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class PrivateGatewayBridgeTests(unittest.TestCase):
    def setUp(self):
        hook._PROCESSES.clear()

    def test_no_action_for_other_events(self):
        with patch.object(hook.subprocess, "Popen") as popen:
            hook.handle("agent:end", {})
            popen.assert_not_called()

    def test_fail_closed_if_external_route_present(self):
        real_read = hook.Path.read_text

        def read(path, *args, **kwargs):
            if str(path) == "/proc/self/net/route":
                return "Iface Destination\neth0 00000000\n"
            return real_read(path, *args, **kwargs)

        with patch.object(hook.Path, "read_text", read), patch.object(hook.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "non-loopback route"):
                hook.handle("gateway:startup", {})
            popen.assert_not_called()

    def test_refuses_unowned_runtime_directory(self):
        with patch.object(hook.Path, "read_text", return_value="Iface Destination\n"), \
             patch.object(hook.os, "getuid", return_value=424242), \
             patch.object(hook.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "runtime directory ownership"):
                hook.handle("gateway:startup", {})
            popen.assert_not_called()

    def test_bridge_targets_are_loopback_only_and_idempotent(self):
        with patch.object(hook.Path, "read_text", return_value="Iface Destination\n"), \
             patch.object(hook.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = None
            hook.handle("gateway:startup", {})
            self.assertEqual(popen.call_count, 2)
            for call, port in zip(popen.call_args_list, (9120, 8642)):
                argv = call.args[0]
                self.assertEqual(argv[0], "/usr/bin/socat")
                self.assertIn("mode=0600", argv[1])
                self.assertEqual(argv[2], f"TCP:127.0.0.1:{port}")
            hook.handle("gateway:startup", {})
            self.assertEqual(popen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
