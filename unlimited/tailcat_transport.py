"""Optional Tailcat transport for JustYou-resolved Hermes endpoints.

JustYou identifies the principal. AI Bridge resolves authorized endpoints.
Tailcat only transports bytes; peer addresses contain bearer secrets.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

_ADDRESS = re.compile(r"^tc[A-Za-z0-9_-]{20,4096}$")


class TailcatError(RuntimeError):
    """Transport error, never an identity or authorization verdict."""


@dataclass(frozen=True)
class TailcatTransport:
    executable: str = "tailcat"
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        if not isinstance(self.executable, str) or not self.executable:
            raise ValueError("executable must be nonempty")

    def _binary(self) -> str:
        binary = shutil.which(self.executable)
        if binary is None:
            raise TailcatError("Tailcat CLI is not installed")
        return binary

    @staticmethod
    def _address(address: str) -> str:
        # Intentionally accept only opaque direct tc addresses, never DNS resolution.
        if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
            raise ValueError("invalid Tailcat address")
        return address

    @staticmethod
    def _port(port: int) -> int:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        return port

    def ping(self, address: str, *, require_direct: bool = False) -> bool:
        address = self._address(address)
        cmd = [self._binary(), "ping", "--timeout", f"{self.timeout_seconds}s"]
        if require_direct:
            cmd.append("--until-direct")
        cmd.append(address)
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds + 2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailcatError("Tailcat connectivity probe failed") from exc
        return result.returncode == 0

    def exchange(self, address: str, port: int, payload: bytes, *, max_bytes: int = 1024 * 1024) -> bytes:
        """One request/reply over a verified, preauthorized peer service.

        Caller must independently verify JustYou binding, peer and service
        authorization. This transport cannot establish any such permission.
        """
        address = self._address(address)
        port = self._port(port)
        if type(max_bytes) is not int or max_bytes < 1 or max_bytes > 16 * 1024 * 1024:
            raise ValueError("max_bytes out of bounds")
        if not isinstance(payload, bytes) or len(payload) > max_bytes:
            raise ValueError("invalid or oversized payload")
        try:
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(
                    [self._binary(), address, str(port)],
                    input=payload, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=self.timeout_seconds, check=False,
                )
                if result.returncode != 0:
                    raise TailcatError("Tailcat stream returned nonzero exit status")
                output.seek(0)
                response = output.read(max_bytes + 1)
                if len(response) > max_bytes:
                    raise TailcatError("Tailcat response exceeds byte limit")
                return response
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailcatError("Tailcat stream failed") from exc
