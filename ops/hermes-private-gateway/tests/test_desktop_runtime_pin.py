"""Offline tests for safe, idempotent Hermes Desktop installed-source pinning."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "install_existing_runtime_pin.py"
spec = importlib.util.spec_from_file_location("hermes_desktop_pin", SCRIPT)
pinmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pinmod)


class DesktopPinTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.home = Path(self.sandbox.name) / "owner"
        runtime = self.home / ".hermes" / "hermes-agent"
        (runtime / ".git").mkdir(parents=True)
        (runtime / "hermes_cli").mkdir()
        (runtime / "hermes_cli" / "main.py").write_text("# test-only\n")
        cli = runtime / ".hermes" / "bin" / "hermes"
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\nexit 0\n")
        cli.chmod(0o700)
        self.published = self.home / ".local" / "bin" / "hermes"
        self.published.parent.mkdir(parents=True)
        self.published.write_text("#!/bin/sh\nexit 0\n")
        self.desktop = self.home / ".local" / "share" / "applications" / "com.nousresearch.hermes.desktop"
        self.desktop.parent.mkdir(parents=True)
        self.original = ("[Desktop Entry]\nType=Application\nName=Hermes\n"
                         f"Exec={self.published} desktop --skip-build\nTerminal=false\n")
        self.desktop.write_text(self.original)
        self.desktop.chmod(0o600)

    def test_default_is_read_only(self):
        self.assertEqual(pinmod.pin(self.home), "PENDING")
        self.assertEqual(self.desktop.read_text(), self.original)
        self.assertFalse(self.desktop.with_name(self.desktop.name + ".pre-pinned-runtime").exists())

    def test_apply_and_idempotency(self):
        self.assertEqual(pinmod.pin(self.home, apply=True), "APPLIED")
        backup = self.desktop.with_name(self.desktop.name + ".pre-pinned-runtime")
        self.assertEqual(backup.read_text(), self.original)
        expected = f"Exec=env HERMES_DESKTOP_HERMES_ROOT={self.home}/.hermes/hermes-agent"
        self.assertIn(expected, self.desktop.read_text())
        self.assertEqual(self.desktop.stat().st_mode & 0o777, 0o600)
        self.assertEqual(pinmod.pin(self.home, apply=True), "ALREADY_PINNED")
        self.assertEqual(backup.read_text(), self.original)

    def test_unexpected_entry_refused(self):
        self.desktop.write_text(self.original.replace("desktop --skip-build", "update --force"))
        with self.assertRaisesRegex(pinmod.LaunchPinError, "unexpected Exec"):
            pinmod.pin(self.home, apply=True)

    def test_missing_install_refused(self):
        (self.home / ".hermes" / "hermes-agent" / "hermes_cli" / "main.py").unlink()
        with self.assertRaisesRegex(pinmod.LaunchPinError, "source root"):
            pinmod.pin(self.home, apply=True)

    def test_symlink_desktop_refused(self):
        real = self.desktop.with_suffix(".real")
        self.desktop.replace(real)
        self.desktop.symlink_to(real)
        with self.assertRaisesRegex(pinmod.LaunchPinError, "symlink"):
            pinmod.pin(self.home, apply=True)

    def test_backup_collision_refused(self):
        self.desktop.with_name(self.desktop.name + ".pre-pinned-runtime").write_text("existing backup")
        with self.assertRaisesRegex(pinmod.LaunchPinError, "backup already exists"):
            pinmod.pin(self.home, apply=True)


if __name__ == "__main__":
    unittest.main()
