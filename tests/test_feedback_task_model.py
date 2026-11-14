import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from feedback_task_model.feedback import (
    build_batch, consent_valid, preview, publish, record, set_consent, validate_trial,
)

NOW = datetime(2026, 11, 14, 13, 0, tzinfo=timezone.utc)
TRIAL = {"task_family": "file_lookup", "model": "nous/solar-mini:free",
         "verified": True, "success": True, "completed": True, "latency_ms": 2200,
         "cost_usd": 0.0001, "input_tokens": 50, "output_tokens": 5}


class FeedbackTaskModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def add_events(self, count=3, at=None):
        set_consent(self.dir, agree=True, now=NOW - timedelta(hours=3))
        for _ in range(count):
            record(self.dir, TRIAL, now=at or NOW - timedelta(hours=2))

    def test_record_exact_allowlist_rejects_sensitive_inputs(self):
        self.add_events(1)
        self.assertNotIn("prompt", (self.dir / "events.jsonl").read_text())
        with self.assertRaises(ValueError):
            validate_trial({**TRIAL, "prompt": "customer secret"})
        with self.assertRaises(ValueError):
            validate_trial({**TRIAL, "model": "../anything"})
        with self.assertRaises(ValueError):
            validate_trial({**TRIAL, "success": True, "verified": False})

    def test_consent_is_explicit_expires_and_revocable(self):
        self.assertFalse(consent_valid(self.dir, now=NOW))
        set_consent(self.dir, agree=True, days=1, now=NOW)
        self.assertTrue(consent_valid(self.dir, now=NOW))
        self.assertFalse(consent_valid(self.dir, now=NOW + timedelta(days=2)))
        set_consent(self.dir, agree=False)
        self.assertFalse(consent_valid(self.dir, now=NOW))

    def test_suppress_small_groups_and_only_complete_half_days(self):
        self.add_events(2)
        batch = preview(self.dir, now=NOW)
        self.assertEqual(batch["groups"], [])
        self.assertEqual(batch["suppressed_groups"], 1)
        self.add_events(1)
        batch = preview(self.dir, now=NOW)
        self.assertEqual(batch["groups"][0]["samples"], 3)
        self.assertEqual(batch["groups"][0]["verified_successes"], 3)
        self.assertNotIn("timestamp", json.dumps(batch["groups"]))
        record(self.dir, TRIAL, now=NOW)
        self.assertEqual(preview(self.dir, now=NOW)["groups"][0]["samples"], 3)

    def test_publish_is_fail_closed_without_consent_or_public_issues(self):
        self.add_events()
        set_consent(self.dir, agree=False)
        calls = []
        def mock_runner(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="false\n", stderr="")
        self.assertEqual(publish(self.dir, now=NOW, runner=mock_runner), "NOT_SENT_NO_VALID_CONSENT")
        self.assertEqual(calls, [])
        set_consent(self.dir, agree=True, now=NOW)
        self.assertEqual(publish(self.dir, now=NOW, runner=mock_runner), "NOT_SENT_TARGET_ISSUES_DISABLED")
        self.assertEqual(len(calls), 1)

    def test_successful_public_aggregate_is_idempotent(self):
        self.add_events()
        set_consent(self.dir, agree=True, now=NOW)
        bodies = []
        def fake_runner(cmd, **kwargs):
            if cmd[1] == "api":
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            body = Path(cmd[cmd.index("--body-file") + 1]).read_text()
            bodies.append(body)
            return subprocess.CompletedProcess(cmd, 0,
                stdout="https://github.com/rrglab/hermes-unlimited/issues/123\n", stderr="")
        result = publish(self.dir, now=NOW, runner=fake_runner)
        self.assertTrue(result.startswith("SENT_AGGREGATES"))
        self.assertIn('"samples": 3', bodies[0])
        self.assertNotIn("customer secret", bodies[0])
        self.assertIn("```json", bodies[0])
        self.assertEqual(publish(self.dir, now=NOW, runner=fake_runner), "NOT_SENT_ALREADY_RECORDED")
        self.assertEqual(len(bodies), 1)

    def test_manual_record_requires_consent(self):
        with self.assertRaisesRegex(ValueError, "NO_VALID_FEEDBACK_CONSENT"):
            record(self.dir, TRIAL, now=NOW)
        self.assertFalse((self.dir / "events.jsonl").exists())
        set_consent(self.dir, agree=True, now=NOW)
        record(self.dir, TRIAL, now=NOW)
        set_consent(self.dir, agree=False)
        with self.assertRaisesRegex(ValueError, "NO_VALID_FEEDBACK_CONSENT"):
            record(self.dir, TRIAL, now=NOW)
        self.assertEqual(len((self.dir / "events.jsonl").read_text().splitlines()), 1)

    def test_publish_reservation_blocks_reentrant_sender(self):
        self.add_events()
        calls = []
        def runner(cmd, **kwargs):
            if cmd[1] == "api":
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            calls.append(cmd)
            # Emulate another cron process racing to send this slot.
            self.assertEqual(publish(self.dir, now=NOW, runner=runner),
                             "NOT_SENT_ALREADY_RECORDED")
            return subprocess.CompletedProcess(cmd, 0,
                stdout="https://github.com/rrglab/hermes-unlimited/issues/123\n", stderr="")
        self.assertTrue(publish(self.dir, now=NOW, runner=runner).startswith("SENT_AGGREGATES"))
        self.assertEqual(len(calls), 1)

    def test_ambiguous_remote_failure_blocks_retry(self):
        self.add_events()
        calls = []
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "api":
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            raise subprocess.TimeoutExpired(cmd, 30)
        self.assertEqual(publish(self.dir, now=NOW, runner=runner),
                         "NOT_SENT_PUBLISH_UNCERTAIN_RECONCILE")
        before = len(calls)
        self.assertEqual(publish(self.dir, now=NOW, runner=runner),
                         "NOT_SENT_ALREADY_RECORDED")
        self.assertEqual(len(calls), before)

    def test_invalid_event_log_lines_cannot_expand_public_schema(self):
        self.add_events()
        with (self.dir / "events.jsonl").open("a") as f:
            f.write(json.dumps({"timestamp": "2026-11-14T11:00:00Z", **TRIAL, "password": "never"}) + "\n")
        result = preview(self.dir, now=NOW)
        self.assertEqual(result["groups"][0]["samples"], 3)
        self.assertNotIn("never", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
