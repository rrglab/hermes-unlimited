"""Tailcat contract tests; all peers and CLI calls are mocked."""
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unlimited.tailcat_transport import TailcatError, TailcatTransport

ADDR = "tc" + "A" * 40


class TailcatTransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = TailcatTransport(timeout_seconds=5)

    def test_missing_dependency(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(TailcatError):
                self.transport.ping(ADDR)

    def test_rejects_address_injection(self):
        with patch("subprocess.run") as run:
            for value in ("", "--help", "tcX;rm -rf /", "tcX\\nfoo", "https://example.com", "tcA"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.transport.exchange(value, 8080, b"hi")
            run.assert_not_called()

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_direct_probe(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(self.transport.ping(ADDR, require_direct=True))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tailcat", "ping", "--timeout", "5s", "--until-direct", ADDR])

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_exchange_port_and_bounded_output(self, run, _which):
        def fake_run(*args, **kwargs):
            kwargs["stdout"].write(b"reply")
            return subprocess.CompletedProcess([], 0)
        run.side_effect = fake_run
        self.assertEqual(self.transport.exchange(ADDR, 8080, b"hello"), b"reply")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tailcat", ADDR, "8080"])
        self.assertEqual(run.call_args.kwargs["input"], b"hello")
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_oversized_response(self, run, _which):
        def fake_run(*args, **kwargs):
            kwargs["stdout"].write(b"12345")
            return subprocess.CompletedProcess([], 0)
        run.side_effect = fake_run
        with self.assertRaises(TailcatError):
            self.transport.exchange(ADDR, 8080, b"ok", max_bytes=4)

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["tailcat"], 5))
    def test_timeout_redacts_capability(self, _run, _which):
        with self.assertRaises(TailcatError) as caught:
            self.transport.exchange(ADDR, 8080, b"hello")
        self.assertNotIn(ADDR, str(caught.exception))

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1))
    def test_nonzero_exit(self, _run, _which):
        with self.assertRaises(TailcatError):
            self.transport.exchange(ADDR, 8080, b"hello")

    def test_invalid_limits_and_port(self):
        for value in (0, 121, 1.5, True):
            with self.assertRaises(ValueError):
                TailcatTransport(timeout_seconds=value)
        for value in (0, 65536, True, "80"):
            with self.assertRaises(ValueError):
                self.transport.exchange(ADDR, value, b"hello")
        with self.assertRaises(ValueError):
            self.transport.exchange(ADDR, 8080, b"too long", max_bytes=2)


if __name__ == "__main__":
    unittest.main()
