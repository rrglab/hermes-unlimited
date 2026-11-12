"""Unit tests for the bounded demo build pipeline (issue #9, fragment 2).

Offline, deterministic tests for the preflight-without-recording step and
the single-command pipeline.  Requires a real ffmpeg binary to exercise the
recording and validation steps; several tests intentionally avoid ffmpeg.
"""
import json
import tempfile
import unittest
from pathlib import Path

from unlimited.demo_pipeline import (
    DemoPackage,
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


class FromSpecTests(unittest.TestCase):
    def test_builds_from_valid_spec(self):
        scenario = from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 5,
                "width": 640,
                "height": 360,
                "narration": "Welcome to Hermes Unlimited.",
                "brand": "Hermes Unlimited",
            }
        )
        self.assertIsInstance(scenario, DemoScenario)
        self.assertEqual(scenario.selectors, ("button.start", "span.status"))
        self.assertEqual(scenario.brand, "Hermes Unlimited")

    def test_from_spec_rejects_missing_keys(self):
        with self.assertRaises(DemoScenarioSpecError):
            from_spec({"name": "x", "selectors": ()})  # no duration/width/height/narration

    def test_from_spec_rejects_non_positive_duration(self):
        for value in (0, -1, "5"):
            with self.subTest(value=value), self.assertRaises(DemoScenarioSpecError):
                from_spec(
                    {
                        "name": "x",
                        "selectors": ("button.start",),
                        "duration_seconds": value,
                        "width": 640,
                        "height": 360,
                        "narration": "x",
                    }
                )

    def test_from_spec_rejects_non_positive_dimensions(self):
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(DemoScenarioSpecError):
                from_spec(
                    {
                        "name": "x",
                        "selectors": ("button.start",),
                        "duration_seconds": 1,
                        "width": value,
                        "height": 360,
                        "narration": "x",
                    }
                )

    def test_from_spec_rejects_non_dict(self):
        with self.assertRaises(DemoScenarioSpecError):
            from_spec(["not", "a", "dict"])


class CheckScenarioTests(unittest.TestCase):
    def setUp(self):
        self.scenario = DemoScenario(
            name="demo-standard",
            selectors=("button.start", "span.status"),
            duration_seconds=5,
            width=640,
            height=360,
            narration="Welcome.",
            brand="Hermes Unlimited",
        )

    def test_accepts_clean_scenario(self):
        check_scenario(self.scenario)

    def test_rejects_empty_selectors(self):
        with self.assertRaises(SelectorPreCheckError):
            check_scenario(
                DemoScenario(
                    name="bad", selectors=(), duration_seconds=1, width=640,
                    height=360, narration="x", brand="Hermes Unlimited",
                )
            )

    def test_rejects_unsafe_selector(self):
        with self.assertRaises(SelectorPreCheckError):
            check_scenario(
                DemoScenario(
                    name="bad", selectors=('button."start"',), duration_seconds=1,
                    width=640, height=360, narration="x", brand="Hermes Unlimited",
                )
            )

    def test_rejects_zero_duration(self):
        with self.assertRaises(FfmpegMissingArgError):
            check_scenario(
                DemoScenario(
                    name="bad", selectors=("button.start",), duration_seconds=0,
                    width=640, height=360, narration="x", brand="Hermes Unlimited",
                )
            )


class BuildDemoPackageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="demo-pipe-test-"))
        self.scenario = from_spec(
            {
                "name": "demo-standard",
                "selectors": ("button.start", "span.status"),
                "duration_seconds": 5,
                "width": 640,
                "height": 360,
                "narration": "Welcome to Hermes Unlimited.",
                "brand": "Hermes Unlimited",
            }
        )
        self.revision = "feedf00d"

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_end_to_end_produces_pinned_package(self):
        package = build_demo_package(
            self.scenario, self.revision, self._tmp, raw_logs="token=AKEY12345 debug=ok"
        )
        self.assertEqual(package.mp4.suffix, ".mp4")
        self.assertGreater(package.mp4.stat().st_size, 0)
        self.assertEqual(package.screenshot.suffix, ".png")
        self.assertGreater(package.screenshot.stat().st_size, 0)
        self.assertEqual(package.manifest.name, "demo-standard.manifest.json")
        self.assertEqual(package.sanitized_logs.suffix, ".log")
        self.assertGreater(package.sanitized_logs.stat().st_size, 0)
        self.assertEqual(package.ffprobe["nb_frames"], "150")  # 5s @ 30fps = 150
        self.assertGreater(float(package.ffprobe["duration"]), 0)
        # Manifest pins the source revision.
        manifest = json.loads(package.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_revision"], self.revision)
        # Sanitised logs have redacted the secret.
        self.assertNotIn("AKEY12345", package.sanitized_logs.read_text(encoding="utf-8"))
        self.assertIn("***REDACTED***", package.sanitized_logs.read_text(encoding="utf-8"))

    def test_end_to_end_is_deterministic(self):
        first = build_demo_package(self.scenario, self.revision, self._tmp / "run1")
        second = build_demo_package(self.scenario, self.revision, self._tmp / "run2")
        # Recording is deterministic for identical inputs; generated_at is
        # intentionally excluded because it is wall-clock time.
        self.assertEqual(first.mp4.read_bytes(), second.mp4.read_bytes())
        self.assertEqual(first.screenshot.read_bytes(), second.screenshot.read_bytes())
        first_manifest = json.loads(first.manifest.read_text(encoding="utf-8"))
        second_manifest = json.loads(second.manifest.read_text(encoding="utf-8"))
        first_manifest.pop("generated_at")
        second_manifest.pop("generated_at")
        self.assertEqual(first_manifest, second_manifest)

    def test_raw_logs_default_is_empty(self):
        package = build_demo_package(self.scenario, self.revision, self._tmp)
        self.assertEqual(package.sanitized_logs.read_text(encoding="utf-8"), "")

    def test_recorder_requires_positive_duration(self):
        bad = DemoScenario(
            name="bad", selectors=("button.start",), duration_seconds=0,
            width=640, height=360, narration="x", brand="Hermes Unlimited",
        )
        with self.assertRaises(FfmpegMissingArgError):
            build_demo_package(bad, self.revision, self._tmp)


class DemoPackageDataclassTests(unittest.TestCase):
    def test_package_is_frozen(self):
        package = DemoPackage(
            mp4=Path("/x.mp4"),
            screenshot=Path("/x.png"),
            manifest=Path("/x.manifest.json"),
            sanitized_logs=Path("/x.log"),
            ffprobe={"nb_frames": "0"},
        )
        with self.assertRaises(AttributeError):
            package.mp4 = Path("/y.mp4")


if __name__ == "__main__":
    unittest.main()
