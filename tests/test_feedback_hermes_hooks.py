import json
from pathlib import Path
import tempfile
import unittest

from feedback_task_model.feedback import set_consent
from feedback_task_model.hermes_hooks import register_feedback_hooks


class Host:
    def __init__(self):
        self.callbacks = {}
    def register_hook(self, name, callback):
        self.callbacks[name] = callback


class FeedbackObserverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.ctx = Host()
        register_feedback_hooks(self.ctx, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def exercise(self):
        self.ctx.callbacks["post_api_request"](
            session_id="sample-session", usage={"input_tokens": 22, "output_tokens": 6},
            api_duration=0.2, assistant_message="hidden", response={"content": "hidden"})
        self.ctx.callbacks["post_tool_call"](
            session_id="sample-session", tool_name="read_file",
            args={"path": "/hidden/data"}, result="hidden")
        self.ctx.callbacks["on_session_end"](
            session_id="sample-session", model="nous/test-small",
            completed=True, failed=False)

    def test_off_by_default(self):
        self.exercise()
        self.assertFalse((self.path / "events.jsonl").exists())

    def test_safe_observations_only(self):
        set_consent(self.path, agree=True)
        self.exercise()
        data = (self.path / "events.jsonl").read_text()
        self.assertNotIn("sample-session", data)
        self.assertNotIn("/hidden/data", data)
        self.assertNotIn("hidden", data)
        event = json.loads(data)
        self.assertEqual(event["task_family"], "file_lookup")
        self.assertTrue(event["completed"])
        self.assertFalse(event["verified"])
        self.assertFalse(event["success"])
        self.assertIsNone(event["cost_usd"])
        self.assertEqual(event["input_tokens"], 22)
        self.assertEqual(event["output_tokens"], 6)

    def test_revoke_stops_collection(self):
        set_consent(self.path, agree=True)
        self.exercise()
        set_consent(self.path, agree=False)
        self.exercise()
        self.assertEqual(len((self.path / "events.jsonl").read_text().splitlines()), 1)
