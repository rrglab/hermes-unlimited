"""Tests the durable CLI-wrapper pin without executing real Hermes or network calls."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "desktop" / "install_existing_runtime_pin.py"
spec = importlib.util.spec_from_file_location("hermes_desktop_runtime_pin", SCRIPT)
pinmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pinmod)


class DesktopPinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "owner"
        self.runtime = self.home / ".hermes" / "hermes-agent"
        (self.runtime / ".git").mkdir(parents=True)
        (self.runtime / "hermes_cli").mkdir()
        (self.runtime / "hermes_cli" / "main.py").write_text("# fixture\n")
        self.cli = self.runtime / ".hermes" / "bin" / "hermes"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text("#!/bin/sh\nexit 0\n")
        self.cli.chmod(0o700)
        self.wrapper = self.home / ".local" / "bin" / "hermes"
        self.wrapper.parent.mkdir(parents=True)
        self.original = f'#!/bin/sh\nexec {self.cli} "$@"\n'
        self.wrapper.write_text(self.original)
        self.wrapper.chmod(0o700)
        self.desktop = self.home / ".local" / "share" / "applications" / "com.nousresearch.hermes.desktop"
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text(
            f'[Desktop Entry]\nType=Application\nName=Hermes\n'
            f'Exec={self.wrapper} desktop --skip-build\nTerminal=false\n'
        )
        self.desktop.chmod(0o600)

    def test_default_is_read_only(self):
        self.assertEqual(pinmod.pin(self.home), "PENDING")
        self.assertEqual(self.wrapper.read_text(), self.original)
        self.assertFalse(self.wrapper.with_name(self.wrapper.name + ".pre-desktop-runtime-pin").exists())

    def test_apply_idempotent_keeps_other_command_path(self):
        self.assertEqual(pinmod.pin(self.home, apply=True), "APPLIED")
        new = self.wrapper.read_text()
        self.assertIn('if [ "${1:-}" = desktop ]; then', new)
        self.assertIn(f"HERMES_DESKTOP_HERMES_ROOT={self.runtime}", new)
        self.assertIn(f'exec {self.cli} "$@"', new)
        self.assertEqual(self.wrapper.stat().st_mode & 0o777, 0o700)
        backup = self.wrapper.with_name(self.wrapper.name + ".pre-desktop-runtime-pin")
        self.assertEqual(backup.read_text(), self.original)
        self.assertEqual(pinmod.pin(self.home, apply=True), "ALREADY_PINNED")
        self.assertEqual(backup.read_text(), self.original)
        self.assertEqual(self.desktop.read_text().splitlines()[3],
                         f"Exec={self.wrapper} desktop --skip-build")

    def test_unexpected_wrapper_refused(self):
        self.wrapper.write_text("#!/bin/sh\nexec /tmp/foreign-CLI \"$@\"\n")
        with self.assertRaisesRegex(pinmod.LaunchPinError, "unexpected published"):
            pinmod.pin(self.home, apply=True)

    def test_missing_install_refused(self):
        (self.runtime / "hermes_cli" / "main.py").unlink()
        with self.assertRaisesRegex(pinmod.LaunchPinError, "source root"):
            pinmod.pin(self.home, apply=True)

    def test_symlink_wrapper_refused(self):
        original = self.wrapper.with_suffix(".original")
        self.wrapper.replace(original)
        self.wrapper.symlink_to(original)
        with self.assertRaisesRegex(pinmod.LaunchPinError, "symlink"):
            pinmod.pin(self.home, apply=True)

    def test_auto_rewritten_desktop_entry_still_valid(self):
        self.assertEqual(pinmod.pin(self.home, apply=True), "APPLIED")
        self.desktop.write_text(
            f'[Desktop Entry]\nType=Application\nName=Hermes\n'
            f'Exec={self.wrapper} desktop --skip-build\nTerminal=false\n'
        )
        self.assertEqual(pinmod.pin(self.home), "ALREADY_PINNED")

    def test_refuses_when_desktop_bypasses_wrapper(self):
        self.desktop.write_text("Exec=/usr/local/bin/hermes desktop --skip-build\n")
        with self.assertRaisesRegex(pinmod.LaunchPinError, "does not invoke"):
            pinmod.pin(self.home, apply=True)

    def test_refuses_backup_collision(self):
        self.wrapper.with_name(self.wrapper.name + ".pre-desktop-runtime-pin").write_text("previous")
        with self.assertRaisesRegex(pinmod.LaunchPinError, "backup already exists"):
            pinmod.pin(self.home, apply=True)


if __name__ == "__main__":
    unittest.main()
