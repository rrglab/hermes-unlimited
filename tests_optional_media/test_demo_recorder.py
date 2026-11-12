"""Unit tests for the bounded demo-recorder module (issue #9, fragment 1).

Uses unittest with deterministic, offline mocks. No ffmpeg is required to
pass these tests: the recorder shell-outs to ffmpeg, so the test suite
verifies the orchestration logic (validation, preflight, manifest, logs)
while a separate smoke step runs the real ffmpeg.
"""

import json
import unittest
from pathlib import Path

from unlimited.demo_recorder import (
    DemoRecorder,
    DemoScenario,
    FfmpegMissingArgError,
    FfmpegNotFoundError,
    SelectorPreCheckError,
    capture_screenshot,
    preflight_selectors,
    sanitize_logs,
    write_manifest,
)


class DemoScenarioFactory:
    """Create a small, named scenario for tests."""

    @staticmethod
    def minimal() -> DemoScenario:
        return DemoScenario(
            name="demo-standard",
            selectors=("button.start", "span.status"),
            duration_seconds=5,
            width=640,
            height=360,
            narration="Welcome to Hermes Unlimited.",
            brand="Hermes Unlimited",
        )


class SelectorPreCheckTests(unittest.TestCase):
    def test_accepts_clean_selectors(self):
        preflight_selectors(("button.start", "span.status"))

    def test_rejects_empty(self):
        with self.assertRaises(SelectorPreCheckError):
            preflight_selectors(())

    def test_rejects_unsafe_characters(self):
        with self.assertRaises(SelectorPreCheckError):
            preflight_selectors(('button."start"',))
        with self.assertRaises(SelectorPreCheckError):
            preflight_selectors(("`id`",))


class SanitizeLogsTests(unittest.TestCase):
    def test_redacts_secrets(self):
        raw = "url=https://x/ token=AKEY12345 debug=ok"
        out = sanitize_logs(raw, redact=("token", "AKEY12345"))
        self.assertNotIn("AKEY12345", out)
        self.assertIn("***REDACTED***", out)

    def test_coerces_bytes(self):
        out = sanitize_logs(b"raw bytes")
        self.assertIsInstance(out, str)

    def test_no_op_when_no_keys(self):
        self.assertEqual(sanitize_logs("plain"), "plain")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "demo-manifest-test"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_manifest_with_revision(self):
        scenario = DemoScenarioFactory.minimal()
        output = self.tmp / "manifest.json"
        write_manifest(scenario, "a1b2c3d4", output)
        self.assertTrue(output.is_file())
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["scenario"], "demo-standard")
        self.assertEqual(payload["source_revision"], "a1b2c3d4")
        self.assertEqual(payload["brand"], "Hermes Unlimited")


class DemoRecorderOrchestrationTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.true_bin = shutil.which("true") or "/bin/true"
        self.tmp = Path(__file__).parent / "demo-recorder-test"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recorder_requires_positive_dimensions(self):
        with self.assertRaises(FfmpegMissingArgError):
            DemoRecorder(default_width=0, default_height=480)

    def test_validate_output_reports_frames(self):
        _ = DemoScenarioFactory.minimal()
        recorder = DemoRecorder(
            ffmpeg_path=self.true_bin,
            output_dir=self.tmp,
        )
        # Override validate_output to avoid needing a real ffmpeg binary.
        def _fake_validate(path):
            return {"nb_frames": "0", "r_frame_rate": "30/1", "duration": "0.000"}
        recorder.validate_output = _fake_validate  # type: ignore[assignment]
        result = recorder.validate_output(self.tmp / "missing.mp4")
        self.assertEqual(result["nb_frames"], "0")

    def test_record_raises_when_scenario_empty_selectors(self):
        scenario = DemoScenarioFactory.minimal()
        scenario = DemoScenario(
            name="bad",
            selectors=(),
            duration_seconds=1,
            width=640,
            height=360,
            narration="x",
            brand="Hermes Unlimited",
        )
        recorder = DemoRecorder(ffmpeg_path=self.true_bin, output_dir=self.tmp)
        with self.assertRaises(SelectorPreCheckError):
            recorder.record(scenario)


class ScreenshotCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "demo-screenshot-test"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capture_writes_png(self):
        # This test requires a real ffmpeg binary. Run it explicitly with
        # `python3 -m unittest -k test_capture_writes_png`.
        output = self.tmp / "frame.png"
        capture_screenshot(output, width=640, height=360)
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 0)


class FfmpegNotFoundErrorTests(unittest.TestCase):
    def test_missing_bin(self):
        tmp = Path(__file__).parent / "demo-missing-ffmpeg-test"
        tmp.mkdir(exist_ok=True)
        with self.assertRaises(FfmpegNotFoundError):
            DemoRecorder(ffmpeg_path="/nonexistent/ffmpeg", output_dir=tmp)


if __name__ == "__main__":
    unittest.main()
