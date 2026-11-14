"""Hermes bootstrap cannot leak ABI-incompatible dependency paths into the host."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from unlimited.hermes_live_worker import ensure_hermes_runtime_loaded


class HermesRuntimePathTests(unittest.TestCase):
    def test_foreign_interpreter_site_packages_are_removed(self):
        host = f"python{sys.version_info.major}.{sys.version_info.minor}"
        foreign = "python3.14" if host != "python3.14" else "python3.12"
        incompatible = f"/tmp/hermes-foreign/venv/lib/{foreign}/site-packages"
        compatible = f"/tmp/hermes-host/venv/lib/{host}/site-packages"
        original = list(sys.path)
        with tempfile.TemporaryDirectory() as root:
            # Simulate an already activated foreign Hermes environment.
            with patch.object(sys, "path", original + [compatible, incompatible]), \
                 patch.dict(sys.modules, {"hermes_bootstrap": types.ModuleType("hermes_bootstrap")}), \
                 patch.dict("os.environ", {}, clear=False):
                self.assertEqual(ensure_hermes_runtime_loaded(Path(root)), Path(root))
                self.assertNotIn(incompatible, sys.path)
                self.assertIn(compatible, sys.path)
                self.assertIn(str(Path(root)), sys.path)


if __name__ == "__main__":
    unittest.main()
