"""Pin an existing, network-isolated Hermes Desktop systemd service to its installed source.

This is NOT a new launcher or a replacement for NIPH isolation. We refuse to
configure a service without the expected existing private-network boundary.
Default mode is read-only. '--apply' creates one drop-in and requires
'systemctl --user daemon-reload' afterward; no process restart is implicit.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

UNIT_NAME = "hermes-desktop-niph.service"
DROPIN_NAME = "95-pin-installed-source.conf"


class UnsafeService(ValueError):
    pass


def prepare(home: Path, *, apply: bool = False) -> str:
    home = home.expanduser().resolve()
    systemd = home / ".config" / "systemd" / "user"
    unit = systemd / UNIT_NAME
    launch_script = home / ".hermes" / "niph-desktop-isolated-launcher.py"
    source = home / ".hermes" / "hermes-agent"
    exe = source / ".hermes" / "bin" / "hermes"
    dropdir = systemd / f"{UNIT_NAME}.d"
    dropin = dropdir / DROPIN_NAME
    if not (source / ".git").exists() or not (source / "hermes_cli" / "main.py").is_file():
        raise UnsafeService("no verified existing Hermes source")
    if not exe.is_file() or not os.access(exe, os.X_OK):
        raise UnsafeService("Hermes runtime CLI is missing")
    if launch_script.is_symlink() or not launch_script.is_file():
        raise UnsafeService("NIPH launcher missing or symlink")
    if unit.is_symlink() or not unit.is_file():
        raise UnsafeService("pre-existing NIPH systemd service is required")
    for path in (unit, launch_script):
        if path.stat().st_uid != os.getuid():
            raise UnsafeService("untrusted owner of NIPH launcher/service")
    text = unit.read_text(encoding="utf-8")
    required = (
        "[Service]",
        f"ExecStart=/usr/bin/python3 {launch_script}",
        "PrivateNetwork=yes",
        "RestrictAddressFamilies=AF_UNIX AF_INET",
        "IPAddressDeny=any",
        "IPAddressAllow=localhost",
        "NoNewPrivileges=yes",
    )
    lines = {line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")}
    if any(line not in lines for line in required):
        raise UnsafeService("NIPH service lacks required isolation contract")
    expected = f"[Service]\nEnvironment=HERMES_DESKTOP_HERMES_ROOT={source}\n"
    if dropin.is_symlink() or dropdir.is_symlink():
        raise UnsafeService("symbolic link on systemd drop-in path")
    if dropin.exists():
        if dropin.read_text(encoding="utf-8") == expected and dropin.stat().st_uid == os.getuid():
            return "ALREADY_PINNED"
        raise UnsafeService("unrecognized existing drop-in; refusing overwrite")
    if not apply:
        return "PENDING"
    dropdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dropdir.stat().st_uid != os.getuid():
        raise UnsafeService("drop-in directory has untrusted owner")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=dropdir,
                                         prefix="." + DROPIN_NAME, delete=False) as f:
            temp = Path(f.name)
            f.write(expected)
        temp.chmod(0o600)
        if dropin.exists() or dropin.is_symlink():
            raise UnsafeService("drop-in appeared concurrently")
        os.replace(temp, dropin)
    finally:
        if temp:
            temp.unlink(missing_ok=True)
    return "APPLIED_RELOAD_REQUIRED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(prepare(Path.home(), apply=args.apply))
        return 0
    except (UnsafeService, OSError) as exc:
        print("REFUSED", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
