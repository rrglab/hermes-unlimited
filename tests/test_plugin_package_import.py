"""Ensure oversight tools import when Hermes loads only the plugin package."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PackagedOversightImportTest(unittest.TestCase):
    def test_import_without_repository_root_on_sys_path(self):
        plugin_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "unlimited"
            shutil.copytree(plugin_root / "unlimited", package)
            code = (
                "import sys; "
                f"sys.path.insert(0, {temporary!r}); "
                "from unlimited.oversight_ledger import OversightLedger; "
                "from unlimited.human_oversight_economics import evaluate; "
                "assert OversightLedger and evaluate"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=temporary, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
