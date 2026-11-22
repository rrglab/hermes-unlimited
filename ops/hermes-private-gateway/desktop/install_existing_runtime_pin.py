"""Pin Hermes Desktop to a verified existing source installation, avoiding false first-run bootstrap.

This only updates the user's existing .desktop launcher; no installer, network or
model/provider operation is performed. Default invocation is read-only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import tempfile


class LaunchPinError(RuntimeError):
    pass


def pin(home: Path, *, apply: bool = False) -> str:
    home = home.expanduser().resolve()
    if any(c.isspace() for c in str(home)) or any(c in str(home) for c in ('"', "'", "\\")):
        raise LaunchPinError("unsupported home path for literal desktop Exec")

    runtime = home / ".hermes" / "hermes-agent"
    cli = runtime / ".hermes" / "bin" / "hermes"
    published = home / ".local" / "bin" / "hermes"
    desktop = home / ".local" / "share" / "applications" / "com.nousresearch.hermes.desktop"

    if not (runtime / ".git").exists() or not (runtime / "hermes_cli" / "main.py").is_file():
        raise LaunchPinError("installed Hermes source root could not be verified")
    if not cli.is_file() or not os.access(cli, os.X_OK) or not published.is_file():
        raise LaunchPinError("installed Hermes launcher not executable or not published")
    if desktop.is_symlink() or not desktop.is_file():
        raise LaunchPinError("desktop entry missing or is a symlink")
    if desktop.stat().st_uid != os.getuid():
        raise LaunchPinError("desktop entry not owned by calling user")

    expected = f"Exec={published} desktop --skip-build"
    pinned = (
        f"Exec=env HERMES_DESKTOP_HERMES_ROOT={runtime} "
        f"{published} desktop --skip-build"
    )
    raw = desktop.read_text(encoding="utf-8")
    rows = raw.splitlines()
    existing = [row for row in rows if row.startswith("Exec=")]
    if existing == [pinned]:
        return "ALREADY_PINNED"
    if existing != [expected] or raw.count(expected) != 1:
        raise LaunchPinError("desktop entry has an unexpected Exec; refusing change")
    if not apply:
        return "PENDING"

    backup = desktop.with_name(desktop.name + ".pre-pinned-runtime")
    if backup.exists() or backup.is_symlink():
        raise LaunchPinError("backup already exists; refusing to overwrite")
    shutil.copy2(desktop, backup)
    payload = raw.replace(expected, pinned, 1)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=desktop.parent,
            prefix=desktop.name + ".", suffix=".tmp", delete=False
        ) as f:
            tmp = Path(f.name)
            f.write(payload)
        tmp.chmod(desktop.stat().st_mode & 0o777)
        os.replace(tmp, desktop)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return "APPLIED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(pin(Path.home(), apply=args.apply))
    except (LaunchPinError, OSError) as exc:
        print("REFUSED:", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
