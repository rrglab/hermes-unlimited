"""Offline acceptance tests for the existing isolated Desktop service pin."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "desktop" / "pin_niph_existing_runtime.py"
spec = importlib.util.spec_from_file_location("hermes_niph_pin", SCRIPT)
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)


class NiphPinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "user"
        self.src = self.home / ".hermes" / "hermes-agent"
        (self.src / ".git").mkdir(parents=True)
        (self.src / "hermes_cli").mkdir()
        (self.src / "hermes_cli" / "main.py").write_text("# no-op\n")
        exe = self.src / ".hermes" / "bin" / "hermes"
        exe.parent.mkdir(parents=True)
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o700)
        self.script = self.home / ".hermes" / "niph-desktop-isolated-launcher.py"
        self.script.write_text("# fixture\n")
        self.unit = self.home / ".config" / "systemd" / "user" / "hermes-desktop-niph.service"
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text(
            "[Unit]\nDescription=isolated Desktop\n[Service]\n"
            f"ExecStart=/usr/bin/python3 {self.script}\n"
            "PrivateNetwork=yes\n"
            "RestrictAddressFamilies=AF_UNIX AF_INET\n"
            "IPAddressDeny=any\nIPAddressAllow=localhost\n"
            "NoNewPrivileges=yes\n"
        )


        self.config = self.home / ".hermes" / "config.yaml"
        self.config.write_text("gateway:\\n  multiplex_profiles: true\\n\\ndesktop:\\n  manage_launcher_entry: false\\n".replace("\\\\n", "\\n"))
        self.desktop = self.home / ".local" / "share" / "applications" / "com.nousresearch.hermes.desktop"
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text(
            "Type=Application\\nName=Hermes\\n"
            "Exec=/usr/bin/systemctl --user start hermes-desktop-niph.service\\n".replace("\\\\n", "\\n")
        )

    def test_read_only(self):
        self.assertEqual(pin.prepare(self.home), "PENDING")
        self.assertFalse((self.unit.parent / (self.unit.name + ".d")).exists())

    def test_apply_idempotent(self):
        self.assertEqual(pin.prepare(self.home, apply=True), "APPLIED_RELOAD_REQUIRED")
        drop = self.unit.parent / (self.unit.name + ".d") / pin.DROPIN_NAME
        self.assertEqual(drop.read_text(), 
                         f"[Service]\nEnvironment=HERMES_DESKTOP_HERMES_ROOT={self.src}\n")
        self.assertEqual(drop.stat().st_mode & 0o777, 0o600)
        self.assertEqual(pin.prepare(self.home, apply=True), "ALREADY_PINNED")

    def test_refuse_missing_private_network(self):
        self.unit.write_text(self.unit.read_text().replace("PrivateNetwork=yes", "PrivateNetwork=no"))
        with self.assertRaisesRegex(pin.UnsafeService, "isolation"):
            pin.prepare(self.home, apply=True)

    def test_refuse_missing_ip_deny(self):
        self.unit.write_text(self.unit.read_text().replace("IPAddressDeny=any", "IPAddressDeny=localhost"))
        with self.assertRaisesRegex(pin.UnsafeService, "isolation"):
            pin.prepare(self.home, apply=True)

    def test_refuse_foreign_existing_dropin(self):
        folder = self.unit.parent / (self.unit.name + ".d")
        folder.mkdir()
        (folder / pin.DROPIN_NAME).write_text("[Service]\nEnvironment=UNRELATED=1\n")
        with self.assertRaisesRegex(pin.UnsafeService, "unrecognized"):
            pin.prepare(self.home, apply=True)

    def test_refuse_symlinked_service(self):
        real = self.unit.with_suffix(".original")
        self.unit.replace(real)
        self.unit.symlink_to(real)
        with self.assertRaisesRegex(pin.UnsafeService, "pre-existing"):
            pin.prepare(self.home)

    def test_refuse_unverified_runtime(self):
        (self.src / "hermes_cli" / "main.py").unlink()
        with self.assertRaisesRegex(pin.UnsafeService, "verified"):
            pin.prepare(self.home)

    def test_refuse_symlinked_dropin(self):
        folder = self.unit.parent / (self.unit.name + ".d")
        folder.mkdir()
        (folder / pin.DROPIN_NAME).symlink_to(self.unit)
        with self.assertRaisesRegex(pin.UnsafeService, "symbolic"):
            pin.prepare(self.home)


    def test_refuse_launcher_management_enabled(self):
        self.config.write_text("desktop:\\n  manage_launcher_entry: true\\n".replace("\\\\n", "\\n"))
        with self.assertRaisesRegex(pin.UnsafeService, "not protected"):
            pin.prepare(self.home, apply=True)

    def test_refuse_missing_launcher_optout(self):
        self.config.write_text("gateway:\\n  multiplex_profiles: true\\n".replace("\\\\n", "\\n"))
        with self.assertRaisesRegex(pin.UnsafeService, "not protected"):
            pin.prepare(self.home, apply=True)

    def test_refuse_direct_desktop_entry(self):
        self.desktop.write_text("Exec=/home/fake/.local/bin/hermes desktop --skip-build\\n".replace("\\\\n", "\\n"))
        with self.assertRaisesRegex(pin.UnsafeService, "not protected"):
            pin.prepare(self.home, apply=True)


if __name__ == "__main__":
    unittest.main()
