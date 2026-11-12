"""Core regression: media tooling is not needed for normal adapter use."""
import unittest
from unittest.mock import patch
from unlimited.screenplay_adapter import ScreenplayAdapter, AdapterConfig

class CoreMediaIsolationTests(unittest.TestCase):
    def test_core_does_not_resolve_ffmpeg(self):
        with patch('unlimited.demo_recorder.find_ffmpeg', side_effect=AssertionError('ffmpeg accessed')):
            adapter = ScreenplayAdapter(config=AdapterConfig())
            self.assertIsNone(adapter.recorder)
            scenario = adapter.from_spec({'name':'core-only','selectors':('button.start',),'duration_seconds':1,'narration':'x'})
            adapter.check_scenario(scenario)
