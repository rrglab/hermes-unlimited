"""Offline Tailcat adapter tests: no network or installed binary required."""
import subprocess
import unittest
from unittest.mock import patch

from unlimited.tailcat_transport import TailcatError, TailcatTransport

ADDR = "tc" + "A" * 40


class TailcatTransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = TailcatTransport(timeout_seconds=5)

    def test_missing_dependency_fails_closed(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(TailcatError):
                self.transport.ping(ADDR)

    def test_rejects_address_injection_before_launch(self):
        with patch("subprocess.run") as run:
            for value in ["", "--help", "tcX;rm -rf /", "tcX\\nfoo", "https://example.com", "tcA"]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.transport.exchange(value, b"hi")
            run.assert_not_called()

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_ping_direct_probe(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0, b"pong", b"")
        self.assertTrue(self.transport.ping(ADDR, require_direct=True))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tailcat", "ping", "--timeout", "5s", "--until-direct", ADDR])
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_exchange_uses_argv_and_bounded_payload(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0, b"response", b"")
        self.assertEqual(self.transport.exchange(ADDR, b"hello"), b"response")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tailcat", ADDR])
        self.assertEqual(run.call_args.kwargs["input"], b"hello")
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        with self.assertRaises(ValueError):
            self.transport.exchange(ADDR, b"too long", max_bytes=2)

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["tailcat"], 5))
    def test_timeout_does_not_leak_address(self, _run, _which):
        with self.assertRaises(TailcatError) as raised:
            self.transport.exchange(ADDR, b"hello")
        self.assertNotIn(ADDR, str(raised.exception))

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_nonzero_exit_fails(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"secret")
        with self.assertRaises(TailcatError) as raised:
            self.transport.exchange(ADDR, b"hello")
        self.assertNotIn("secret", str(raised.exception))

    def test_bad_timeout(self):
        for value in [0, 121, 1.5, True]:
            with self.assertRaises(ValueError):
                TailcatTransport(timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
