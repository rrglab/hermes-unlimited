import importlib.util
from pathlib import Path
import tempfile
import unittest

from feedback_task_model import register
from feedback_task_model.feedback import consent_valid


class FakeHost:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, callback, **kwargs):
        self.hooks[name] = callback


class FeedbackSidecarTest(unittest.TestCase):
    def test_registers_only_three_observers(self):
        host = FakeHost()
        register(host)
        self.assertEqual(set(host.hooks), {"post_api_request", "post_tool_call", "on_session_end"})

    def test_default_no_consent_no_record(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(consent_valid(Path(directory)))
