"""Manual Tailcat transport smoke: two Docker peers on ONE host.

This proves an actual Tailcat CLI data transfer, not Hermes/JustYou E2E,
independent hosts, tenant isolation, authenticated service, or DERP fallback.
Requires explicit operator execution and Docker with network access.
The bearer-capability address is never printed or stored.
"""
import re
import select
import subprocess
import sys
import time

IMAGE = "ghcr.io/tailscale/tailcat@sha256:5ce9b638e399bdc398da2a1fd84ce9542077fbc97d3fe571ac597737afb560a1"
MARKER = b"hello-tailcat-pr13\n"


def main():
    server = None
    try:
        server = subprocess.Popen(
            ["docker", "run", "--rm", "-i", IMAGE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )
        address = None
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            ready, _, _ = select.select([server.stderr], [], [], 1)
            if ready:
                line = server.stderr.readline().decode(errors="replace")
                if not line:
                    break
                match = re.search(r"(tc[A-Za-z0-9_-]{20,4096})", line)
                if match:
                    address = match.group(1)
                    break
            if server.poll() is not None:
                break
        if not address:
            print("BLOCKED: Tailcat server did not publish a valid ephemeral address")
            return 2
        client = subprocess.run(
            ["docker", "run", "--rm", "-i", IMAGE, address],
            input=MARKER, capture_output=True, timeout=35, check=False,
        )
        if client.returncode:
            print("FAIL: Tailcat client returned nonzero exit")
            return 1
        ready, _, _ = select.select([server.stdout], [], [], 10)
        if not ready or server.stdout.readline() != MARKER:
            print("FAIL: Tailcat peer payload mismatch")
            return 1
        print("PASS: local two-container Tailcat data transfer (not full E2E)")
        return 0
    except (OSError, subprocess.SubprocessError):
        print("BLOCKED: Docker or network invocation failed")
        return 2
    finally:
        if server:
            server.terminate()
            try:
                server.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.communicate()


if __name__ == "__main__":
    sys.exit(main())
