"""Pin the installed Hermes source for Desktop only, without changing other CLI calls.

Hermes Desktop rewrites the .desktop launcher on startup. Therefore the already
published user CLI wrapper (the entrypoint used by the .desktop launcher) is the
durable interception point. This tool defaults to validation without mutation.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import shlex
import tempfile


class LaunchPinError(RuntimeError):
    pass


def pin(home: Path, *, apply: bool = False) -> str:
    home = home.expanduser().resolve()
    runtime = home / ".hermes" / "hermes-agent"
    cli = runtime / ".hermes" / "bin" / "hermes"
    wrapper = home / ".local" / "bin" / "hermes"
    desktop = home / ".local" / "share" / "applications" / "com.nousresearch.hermes.desktop"

    if not (runtime / ".git").exists() or not (runtime / "hermes_cli" / "main.py").is_file():
        raise LaunchPinError("installed Hermes source root could not be verified")
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise LaunchPinError("installed Hermes CLI not executable")
    if not wrapper.is_file() or wrapper.is_symlink() or wrapper.stat().st_uid != os.getuid():
        raise LaunchPinError("published CLI wrapper missing, foreign-owned, or is a symlink")
    if not desktop.is_file() or desktop.is_symlink() or desktop.stat().st_uid != os.getuid():
        raise LaunchPinError("installed Desktop entry missing or foreign-owned")

    old = f"#!/bin/sh\nexec {shlex.quote(str(cli))} \"$@\"\n"
    new = (
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = desktop ]; then\n"
        f"  export HERMES_DESKTOP_HERMES_ROOT={shlex.quote(str(runtime))}\n"
        "fi\n"
        f"exec {shlex.quote(str(cli))} \"$@\"\n"
    )
    original = wrapper.read_text(encoding="utf-8")
    if original == new:
        return "ALREADY_PINNED"
    if original != old:
        raise LaunchPinError("unexpected published Hermes wrapper; refusing change")
    desktop_exec = f"Exec={wrapper} desktop --skip-build"
    if desktop_exec not in desktop.read_text(encoding="utf-8").splitlines():
        raise LaunchPinError("Desktop does not invoke published CLI wrapper")
    if not apply:
        return "PENDING"

    backup = wrapper.with_name(wrapper.name + ".pre-desktop-runtime-pin")
    if backup.exists() or backup.is_symlink():
        raise LaunchPinError("backup already exists; refusing to overwrite")
    shutil.copy2(wrapper, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=wrapper.parent,
            prefix=wrapper.name + ".", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(new)
        temporary.chmod(wrapper.stat().st_mode & 0o777)
        os.replace(temporary, wrapper)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
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
