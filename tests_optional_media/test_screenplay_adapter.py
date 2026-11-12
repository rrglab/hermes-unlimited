"""Tests for the bounded Screenplay adapter (issue #16, orchestration + smoke).

All tests are offline and deterministic. No display, real browser or network is
opened: the recorder shell-outs to a trusted ffmpeg binary, and the tests
override it with a deterministic stand-in where needed.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from unlimited.demo_pipeline import (
    DemoScenarioSpecError,
    build_demo_package,
    check_scenario,
    from_spec,
)
from unlimited.demo_recorder import (
    DemoScenario,
    FfmpegMissingArgError,
    SelectorPreCheckError,
)
from unlimited.screenplay_adapter import (
    AdapterConfig,
    ScreenplayAdapter,
    ScreenplayAdapterError,
)


class ScreenplayAdapterSpecTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ScreenplayAdapter(config=AdapterConfig())

    def test_from_spec_applies_defaults(self):
        scenario = self.adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 5,
                "narration": "Welcome.",
            }
        )
        self.assertEqual(scenario.brand, "Hermes Unlimited")
        self.assertEqual(scenario.width, 1280)
        self.assertEqual(scenario.height, 720)
        self.assertEqual(scenario.duration_seconds, 5)

    def test_from_spec_uses_caller_overrides(self):
        scenario = self.adapter.from_spec(
            {
                "name": "demo-smoke",
                "selectors": ("button.start",),
                "duration_seconds": 2,
                "width": 640,
                "height": 360,
                "narration": "Smoke.",
                "brand": "TestCo",
            }
        )
        self.assertEqual(scenario.brand, "TestCo")
        self.assertEqual(scenario.width, 640)

    def test_from_spec_rejects_missing_keys(self):
        with self.assertRaises(DemoScenarioSpecError):
            self.adapter.from_spec({"name": "x", "selectors": ()})

    def test_check_scenario_accepts_clean(self):
        scenario = self.adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 5,
                "width": 640,
                "height": 360,
                "narration": "Welcome.",
            }
        )
        check_scenario(scenario)

    def test_check_scenario_rejects_empty_selectors(self):
        scenario = DemoScenario(
            name="bad", selectors=(), duration_seconds=1, width=640,
            height=360, narration="x", brand="Hermes Unlimited",
        )
        with self.assertRaises(SelectorPreCheckError):
            check_scenario(scenario)

    def test_check_scenario_rejects_unsafe_selector(self):
        scenario = DemoScenario(
            name="bad", selectors=('button."start"',), duration_seconds=1,
            width=640, height=360, narration="x", brand="Hermes Unlimited",
        )
        with self.assertRaises(SelectorPreCheckError):
            check_scenario(scenario)

    def test_check_scenario_rejects_zero_duration(self):
        scenario = DemoScenario(
            name="bad", selectors=("button.start",), duration_seconds=0,
            width=640, height=360, narration="x", brand="Hermes Unlimited",
        )
        with self.assertRaises(FfmpegMissingArgError):
            check_scenario(scenario)

    def test_record_rejects_missing_revision(self):
        adapter = ScreenplayAdapter(config=AdapterConfig())
        scenario = adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 1,
                "width": 640,
                "height": 360,
                "narration": "Welcome.",
            }
        )
        with self.assertRaises(ScreenplayAdapterError):
            adapter.record(scenario, source_revision="")

    def test_record_is_deterministic(self):
        adapter = ScreenplayAdapter(config=AdapterConfig())
        scenario = adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 3,
                "width": 320,
                "height": 180,
                "narration": "Deterministic.",
            }
        )
        tmp = Path(tempfile.mkdtemp(prefix="spi-bound-"))
        try:
            first = adapter.record(scenario, "feedf00d", raw_logs="", output_dir=tmp)
            second = adapter.record(
                scenario, "feedf00d", raw_logs="", output_dir=tmp / "run2"
            )
            self.assertEqual(first.ffprobe["nb_frames"], "90")  # 3s @ 30fps
            self.assertEqual(first.mp4.read_bytes(), second.mp4.read_bytes())
            self.assertEqual(first.screenshot.read_bytes(), second.screenshot.read_bytes())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ScreenplayAdapterVerifyTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ScreenplayAdapter(config=AdapterConfig())
        self.scenario = self.adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 2,
                "width": 640,
                "height": 360,
                "narration": "Welcome.",
            }
        )
        self.tmp = Path(tempfile.mkdtemp(prefix="spi-verify-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_verify_returns_evidence(self):
        package = self.adapter.record(
            self.scenario, "aabb1111", raw_logs="token=AKEY12345", output_dir=self.tmp
        )
        evidence = self.adapter.verify(package)
        self.assertEqual(evidence["status"], "verified")
        self.assertEqual(evidence["source_revision"], "aabb1111")
        self.assertTrue(evidence["sanitised_logs_redacted"])
        self.assertIn("mp4", evidence)
        self.assertIn("screenshot", evidence)
        self.assertIn("manifest", evidence)

    def test_verify_fails_closed_on_missing_frames(self):
        # Build a real package, then present a probe report without frame data
        # so the adapter must not claim verification.
        tmp = self.tmp
        package = build_demo_package(
            self.scenario, "deadbeef", tmp, raw_logs=""
        )
        fake = _FakeProbePackage(
            mp4=package.mp4,
            screenshot=package.screenshot,
            manifest=package.manifest,
            sanitized_logs=package.sanitized_logs,
            ffprobe={"nb_frames": "0", "r_frame_rate": "30/1", "duration": "1.000"},
        )
        evidence = self.adapter.verify(fake)
        self.assertEqual(evidence["status"], "missing_frames")


class ScreenplayAdapterLogRedactionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ScreenplayAdapter(config=AdapterConfig())
        self.scenario = self.adapter.from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start",),
                "duration_seconds": 1,
                "width": 640,
                "height": 360,
                "narration": "Welcome.",
            }
        )
        self.tmp = Path(tempfile.mkdtemp(prefix="spi-log-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_raw_logs_secret_is_redacted(self):
        package = self.adapter.record(
            self.scenario,
            "deadbeef",
            raw_logs="url=/debug token=AKEY12345 debug=ok",
            output_dir=self.tmp,
        )
        text = package.sanitized_logs.read_text(encoding="utf-8")
        self.assertNotIn("AKEY12345", text)
        self.assertIn("***REDACTED***", text)

    def test_raw_logs_default_empty(self):
        package = self.adapter.record(
            self.scenario, "deadbeef", raw_logs="", output_dir=self.tmp
        )
        self.assertEqual(package.sanitized_logs.read_text(encoding="utf-8"), "")


class ScreenplayAdapterReExportTests(unittest.TestCase):
    """Guard: ``unlimited.screenplay_adapter.from_spec`` shadows the pipeline."""

    def test_from_spec_resolution(self):
        from unlimited.demo_pipeline import from_spec as pipeline_from_spec

        self.assertIs(pipeline_from_spec, from_spec)


class _FakeProbePackage:
    """Minimal stand-in for DemoPackage with a controllable probe report."""

    def __init__(self, mp4, screenshot, manifest, sanitized_logs, ffprobe):
        self.mp4 = mp4
        self.screenshot = screenshot
        self.manifest = manifest
        self.sanitized_logs = sanitized_logs
        self.ffprobe = ffprobe
