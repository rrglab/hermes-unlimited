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
            session_id="sample-session", turn_id="turn-1", api_request_id="call-1", model="nous/test-small", usage={"input_tokens": 22, "output_tokens": 6},
            api_duration=0.2, assistant_message="hidden", response={"content": "hidden"})
        self.ctx.callbacks["post_tool_call"](
            session_id="sample-session", turn_id="turn-1", tool_name="read_file",
            args={"path": "/hidden/data"}, result="hidden")
        self.ctx.callbacks["on_session_end"](
            session_id="sample-session", turn_id="turn-1", model="nous/test-small",
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

    def test_interleaved_turns_do_not_mix_tokens_or_categories(self):
        set_consent(self.path, agree=True)
        self.ctx.callbacks["post_api_request"](session_id="shared-session", turn_id="first",
            api_request_id="req1", model="m1", usage={"input_tokens": 10, "output_tokens": 2}, api_duration=.1)
        self.ctx.callbacks["post_api_request"](session_id="shared-session", turn_id="second",
            api_request_id="req2", model="m2", usage={"input_tokens": 30, "output_tokens": 3}, api_duration=.2)
        self.ctx.callbacks["post_tool_call"](session_id="shared-session", turn_id="first", tool_name="read_file")
        self.ctx.callbacks["on_session_end"](session_id="shared-session", turn_id="second", model="m2",
                                                completed=True, failed=False)
        self.ctx.callbacks["on_session_end"](session_id="shared-session", turn_id="first", model="m1",
                                                completed=True, failed=False)
        records = [json.loads(s) for s in (self.path / "events.jsonl").read_text().splitlines()]
        self.assertEqual([(x["model"], x["input_tokens"], x["task_family"]) for x in records],
                         [("m2", 30, "general"), ("m1", 10, "file_lookup")])
        self.assertNotIn("shared-session", (self.path / "events.jsonl").read_text())

    def test_duplicate_api_receipt_is_counted_once(self):
        set_consent(self.path, agree=True)
        api = dict(session_id="s", turn_id="t", api_request_id="same", model="m",
                   usage={"input_tokens": 500, "output_tokens": 20}, api_duration=.5)
        self.ctx.callbacks["post_api_request"](**api)
        self.ctx.callbacks["post_api_request"](**api)
        self.ctx.callbacks["on_session_end"](session_id="s", turn_id="t", model="m",
                                                completed=True, failed=False)
        item = json.loads((self.path / "events.jsonl").read_text())
        self.assertEqual((item["input_tokens"], item["output_tokens"], item["latency_ms"]), (500, 20, 500))

    def test_missing_turn_identity_or_model_change_fails_closed(self):
        set_consent(self.path, agree=True)
        self.ctx.callbacks["post_api_request"](session_id="s", model="m",
             usage={"input_tokens": 99, "output_tokens": 9})
        self.ctx.callbacks["on_session_end"](session_id="s", model="m", completed=True)
        self.ctx.callbacks["post_api_request"](session_id="s", turn_id="t", model="m1",
             usage={"input_tokens": 11, "output_tokens": 1})
        self.ctx.callbacks["on_session_end"](session_id="s", turn_id="t", model="m2", completed=True)
        self.assertFalse((self.path / "events.jsonl").exists())
