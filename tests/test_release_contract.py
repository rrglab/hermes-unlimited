"""Release-surface invariant: a public Hermes plugin is a versioned, bounded artifact."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_canonical_version_matches_manifest(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        self.assertRegex(version, r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")
        match = re.search(r"(?m)^version:\s*['\"]?([^\s'\"]+)", manifest)
        self.assertIsNotNone(match)
        self.assertEqual(version, match.group(1))

    def test_native_tool_declarations_are_unique_and_bounded(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        section = re.search(r"(?ms)^provides_tools:\s*\n(.*?)(?=^[^\s#][^\n]*:|\Z)", manifest)
        self.assertIsNotNone(section)
        tools = re.findall(r"(?m)^\s+-\s+([a-z][a-z0-9_]+)\s*$", section.group(1))
        self.assertTrue(tools)
        self.assertEqual(len(tools), len(set(tools)), "duplicate public tool declaration")
        # alpha.4 is the currently accepted ten-tool catalog surface.
        if (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0-alpha.4":
            self.assertEqual(len(tools), 10, "alpha.4 must not silently expand the public tool surface")

    def test_public_source_must_not_override_host_approval(self):
        for path in (ROOT / "unlimited").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for assignment in ("HERMES_YOLO_MODE", "HERMES_ACCEPT_HOOKS"):
                self.assertNotRegex(
                    source,
                    rf"(?:os\.environ\s*\[\s*['\"]{assignment}['\"]\s*\]|os\.environ\.setdefault\(\s*['\"]{assignment}['\"])",
                    f"host approval override in {path.relative_to(ROOT)}",
                )


if __name__ == "__main__":
    unittest.main()
