"""Opt-in Tailcat CLI transport; never an identity or authorization verdict.

Tailcat CLI expects a bearer-capability address in argv. This cannot hide that
capability from local process inspection. Use only after explicit opt-in.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from dataclasses import dataclass

_ADDRESS = re.compile(r"^tc[A-Za-z0-9_-]{20,4096}$")


class TailcatError(RuntimeError):
    """Transport failure with no peer address or subprocess exception details."""


@dataclass(frozen=True)
class TailcatTransport:
    executable: str = "tailcat"
    timeout_seconds: int = 15
    allow_argv_secret_exposure: bool = False

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        if not isinstance(self.executable, str) or not self.executable:
            raise ValueError("executable must be nonempty")
        if type(self.allow_argv_secret_exposure) is not bool:
            raise ValueError("allow_argv_secret_exposure must be a bool")

    def _binary(self) -> str:
        binary = shutil.which(self.executable)
        if binary is None:
            raise TailcatError("Tailcat CLI is not installed")
        return binary

    @staticmethod
    def _address(address: str) -> str:
        if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
            raise ValueError("invalid Tailcat address")
        return address

    @staticmethod
    def _port(port: int) -> int:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        return port

    def _require_opt_in(self) -> None:
        if not self.allow_argv_secret_exposure:
            raise TailcatError(
                "Tailcat CLI requires a bearer secret in process arguments; "
                "explicit allow_argv_secret_exposure is required"
            )

    def ping(self, address: str, *, require_direct: bool = False) -> bool:
        address = self._address(address)
        self._require_opt_in()
        cmd = [self._binary(), "ping", "--timeout", f"{self.timeout_seconds}s"]
        if require_direct:
            cmd.append("--until-direct")
        cmd.append(address)
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds + 2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise TailcatError("Tailcat connectivity probe failed") from None
        return result.returncode == 0

    def exchange(self, address: str, port: int, payload: bytes, *, max_bytes: int = 1024 * 1024) -> bytes:
        """One request/reply; caller must separately authorize endpoint and service.

        Reads at most max_bytes + 1 bytes into memory and kills a peer that
        exceeds the cap. No unbounded temporary file or communicate() buffer.
        """
        address = self._address(address)
        port = self._port(port)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError("max_bytes out of bounds")
        if not isinstance(payload, bytes) or len(payload) > max_bytes:
            raise ValueError("invalid or oversized payload")
        self._require_opt_in()

        proc = None
        timer = None
        timed_out = threading.Event()
        write_errors = []

        try:
            proc = subprocess.Popen(
                [self._binary(), address, str(port)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, shell=False,
            )

            def write_request() -> None:
                try:
                    proc.stdin.write(payload)
                    proc.stdin.flush()
                except (OSError, ValueError) as exc:
                    write_errors.append(type(exc).__name__)
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            def expire() -> None:
                if proc.poll() is None:
                    timed_out.set()
                    proc.kill()

            timer = threading.Timer(self.timeout_seconds, expire)
            timer.daemon = True
            timer.start()
            writer = threading.Thread(target=write_request, daemon=True)
            writer.start()
            response = proc.stdout.read(max_bytes + 1)
            if len(response) > max_bytes:
                proc.kill()
                proc.wait()
                raise TailcatError("Tailcat response exceeds byte limit")
            status = proc.wait()
            writer.join(timeout=1)
            if timed_out.is_set():
                raise TailcatError("Tailcat stream timed out")
            if status != 0 or write_errors or writer.is_alive():
                raise TailcatError("Tailcat stream failed")
            return response
        except (OSError, ValueError, subprocess.SubprocessError):
            raise TailcatError("Tailcat stream failed") from None
        finally:
            if timer is not None:
                timer.cancel()
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
