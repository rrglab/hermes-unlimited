"""Optional Tailcat transport for bounded Hermes peer connectivity.

Transport does not grant identity, authorization, or execution permission.
Tailcat addresses contain sensitive bearer capability material.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

_ADDRESS = re.compile(r"^tc[A-Za-z0-9_-]{20,4096}$")


class TailcatError(RuntimeError):
    """Transport failure; never an authority decision."""


@dataclass(frozen=True)
class TailcatTransport:
    executable: str = "tailcat"
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        if not isinstance(self.executable, str) or not self.executable:
            raise ValueError("executable must be a nonempty string")

    def _binary(self) -> str:
        binary = shutil.which(self.executable)
        if binary is None:
            raise TailcatError("Tailcat CLI is not installed")
        return binary

    @staticmethod
    def _validate_address(address: str) -> str:
        if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
            raise ValueError("invalid Tailcat address")
        return address

    def ping(self, address: str, *, require_direct: bool = False) -> bool:
        """Probe connectivity only; failure does not imply access denial."""
        address = self._validate_address(address)
        cmd = [self._binary(), "ping", "--timeout", f"{self.timeout_seconds}s"]
        if require_direct:
            cmd.append("--until-direct")
        cmd.append(address)
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=self.timeout_seconds + 2, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailcatError("Tailcat connection probe failed") from exc
        return result.returncode == 0

    def exchange(self, address: str, payload: bytes, *, max_bytes: int = 1024 * 1024) -> bytes:
        """Exchange bytes through peer stdin/stdout, without invoking a shell.

        Must be called only after independent tenant/peer authorization.
        """
        address = self._validate_address(address)
        if not isinstance(payload, bytes) or max_bytes < 1 or len(payload) > max_bytes:
            raise ValueError("payload exceeds configured byte limit or is not bytes")
        try:
            result = subprocess.run(
                [self._binary(), address], input=payload, capture_output=True,
                timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailcatError("Tailcat stream failed") from exc
        if result.returncode != 0:
            raise TailcatError("Tailcat stream returned nonzero exit status")
        if len(result.stdout) > max_bytes:
            raise TailcatError("Tailcat peer response exceeds byte limit")
        return result.stdout
