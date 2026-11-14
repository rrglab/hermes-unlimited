"""Offline Tailcat contract and real subprocess boundary tests (no Tailcat peer)."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from unlimited.tailcat_transport import TailcatError, TailcatTransport

ADDR = "tc" + "A" * 40


class TailcatTransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = TailcatTransport(timeout_seconds=5, allow_argv_secret_exposure=True)

    def test_missing_dependency(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(TailcatError):
                self.transport.ping(ADDR)

    def test_rejects_address_injection(self):
        with patch("subprocess.Popen") as popen:
            for value in ("", "--help", "tcX;rm -rf /", "tcX\\nfoo", "https://example.com", "tcA"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.transport.exchange(value, 8080, b"hi")
            popen.assert_not_called()

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run")
    def test_direct_probe(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(self.transport.ping(ADDR, require_direct=True))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tailcat", "ping", "--timeout", "5s", "--until-direct", ADDR])

    def _fake_cli(self, body):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "fake-tailcat"
        path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o700)
        return str(path)

    def test_real_process_request_reply(self):
        path = self._fake_cli("""
            import sys
            assert len(sys.argv) == 3
            assert sys.argv[2] == '8080'
            request = sys.stdin.buffer.read()
            sys.stdout.buffer.write(b'reply:' + request)
        """)
        transport = TailcatTransport(executable=path, timeout_seconds=2, allow_argv_secret_exposure=True)
        self.assertEqual(transport.exchange(ADDR, 8080, b"hello"), b"reply:hello")

    def test_real_process_oversized_response_killed(self):
        path = self._fake_cli("""
            import sys
            sys.stdin.buffer.read()
            sys.stdout.buffer.write(b'Z' * 1048576)
            sys.stdout.buffer.flush()
        """)
        transport = TailcatTransport(executable=path, timeout_seconds=2, allow_argv_secret_exposure=True)
        with self.assertRaisesRegex(TailcatError, "byte limit"):
            transport.exchange(ADDR, 8080, b"ok", max_bytes=4)

    def test_real_process_timeout(self):
        path = self._fake_cli("""
            import sys, time
            sys.stdin.buffer.read()
            time.sleep(10)
        """)
        transport = TailcatTransport(executable=path, timeout_seconds=1, allow_argv_secret_exposure=True)
        with self.assertRaisesRegex(TailcatError, "timed out"):
            transport.exchange(ADDR, 8080, b"ok")

    def test_argv_secret_requires_explicit_opt_in(self):
        transport = TailcatTransport()
        with patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
            with self.assertRaisesRegex(TailcatError, "explicit"):
                transport.exchange(ADDR, 8080, b"hello")
            with self.assertRaisesRegex(TailcatError, "explicit"):
                transport.ping(ADDR)
            popen.assert_not_called()
            run.assert_not_called()

    @patch("shutil.which", return_value="/usr/bin/tailcat")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["tailcat", ADDR], 5))
    def test_timeout_redacts_capability(self, _run, _which):
        with self.assertRaises(TailcatError) as caught:
            self.transport.ping(ADDR)
        self.assertNotIn(ADDR, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_real_process_nonzero_exit(self):
        path = self._fake_cli("""
            import sys
            sys.stdin.buffer.read()
            sys.exit(1)
        """)
        transport = TailcatTransport(executable=path, timeout_seconds=2, allow_argv_secret_exposure=True)
        with self.assertRaises(TailcatError):
            transport.exchange(ADDR, 8080, b"hello")

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
