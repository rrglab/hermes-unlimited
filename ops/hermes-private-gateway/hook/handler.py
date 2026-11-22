"""Local Unix bridges for a gateway confined by PrivateNetwork=yes.

No external address, shell, agent action, or paid service is invoked.
"""
from pathlib import Path
import os
import subprocess

_PROCESSES = {}
_PORTS = (9120, 8642)


def handle(event_type, context):
    if event_type != "gateway:startup":
        return
    routes = Path("/proc/self/net/route").read_text().splitlines()[1:]
    if any(route.split()[0] != "lo" for route in routes if route.split()):
        raise RuntimeError("private-loopback-bridge refused: gateway has a non-loopback route")
    run_dir = Path(f"/run/user/{os.getuid()}")
    if not run_dir.is_dir() or run_dir.stat().st_uid != os.getuid():
        raise RuntimeError("private-loopback-bridge refused: runtime directory ownership")
    for port in _PORTS:
        existing = _PROCESSES.get(port)
        if existing and existing.poll() is None:
            continue
        unix_path = run_dir / f"hermes-gw{port}.sock"
        listener = f"UNIX-LISTEN:{unix_path},unlink-early,mode=0600,fork"
        proc = subprocess.Popen(
            ["/usr/bin/socat", listener, f"TCP:127.0.0.1:{port}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _PROCESSES[port] = proc
        print(f"[private-loopback-bridge] started owner-only Unix bridge {port}, pid={proc.pid}", flush=True)
