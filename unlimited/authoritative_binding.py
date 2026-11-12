"""Self-contained public JustYou signed-binding verifier.

Source: nsolland/justyou protocol/authoritative_binding.py
Pinned upstream: 8a42c29c4a8dc79ed9fa7af142f28486f0e7ae0c
Only verification keys may be provided at runtime; no private keys shipped.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
from typing import Dict, Iterable, Protocol, Tuple


class ProtocolError(ValueError):
    pass


class SignatureError(ProtocolError):
    pass


class AuthorityError(ProtocolError):
    pass


class FreshnessError(ProtocolError):
    pass


class ChainError(ProtocolError):
    pass


class ConflictError(ProtocolError):
    pass


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ProtocolError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AuthorityBinding:
    identity: str
    version: int
    carrier: str
    endpoint: str
    endpoint_key_id: str
    authority_key_id: str
    valid_from: datetime
    valid_until: datetime
    previous_digest: str | None = None
    policy_digest: str | None = None
    signature: str = ""

    def unsigned_payload(self) -> dict:
        return {
            "identity": self.identity,
            "version": self.version,
            "carrier": self.carrier,
            "endpoint": self.endpoint,
            "endpoint_key_id": self.endpoint_key_id,
            "authority_key_id": self.authority_key_id,
            "valid_from": _iso(self.valid_from),
            "valid_until": _iso(self.valid_until),
            "previous_digest": self.previous_digest,
            "policy_digest": self.policy_digest,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.unsigned_payload(), sort_keys=True, separators=(",", ":")).encode()

    def digest(self) -> str:
        envelope = {**self.unsigned_payload(), "signature": self.signature}
        return hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def active_at(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ProtocolError("now must be timezone-aware")
        return self.valid_from <= now < self.valid_until


@dataclass(frozen=True)
class CommitReceipt:
    identity: str
    version: int
    binding_digest: str
    previous_digest: str | None
    committed_at: datetime

    def digest(self) -> str:
        payload = {
            "identity": self.identity,
            "version": self.version,
            "binding_digest": self.binding_digest,
            "previous_digest": self.previous_digest,
            "committed_at": _iso(self.committed_at),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class VersionAnnouncement:
    identity: str
    version: int
    binding_digest: str
    announced_at: datetime
    authority_key_id: str
    signature: str = ""

    def unsigned_payload(self) -> dict:
        return {
            "identity": self.identity,
            "version": self.version,
            "binding_digest": self.binding_digest,
            "announced_at": _iso(self.announced_at),
            "authority_key_id": self.authority_key_id,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.unsigned_payload(), sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class ResolutionReceipt:
    identity: str
    requested_min_version: int | None
    resolved_version: int | None
    binding_digest: str | None
    status: ResolutionStatus
    resolved_at: datetime
    source: str


class Verifier(Protocol):
    key_id: str

    def verify_binding(self, binding: AuthorityBinding) -> bool: ...
    def verify_announcement(self, announcement: VersionAnnouncement) -> bool: ...


class HmacAuthority:
    """Prototype signer for deterministic tests; replace with public-key signatures in production."""

    def __init__(self, key_id: str, secret: bytes):
        if not key_id or not secret:
            raise ProtocolError("key_id and secret are required")
        self.key_id = key_id
        self._secret = secret

    def sign_binding(self, binding: AuthorityBinding) -> AuthorityBinding:
        if binding.authority_key_id != self.key_id:
            raise AuthorityError("binding authority key does not match signer")
        sig = hmac.new(self._secret, binding.canonical_bytes(), hashlib.sha256).hexdigest()
        return replace(binding, signature=sig)

    def verify_binding(self, binding: AuthorityBinding) -> bool:
        expected = hmac.new(self._secret, binding.canonical_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, binding.signature)

    def sign_announcement(self, announcement: VersionAnnouncement) -> VersionAnnouncement:
        if announcement.authority_key_id != self.key_id:
            raise AuthorityError("announcement authority key does not match signer")
        sig = hmac.new(self._secret, announcement.canonical_bytes(), hashlib.sha256).hexdigest()
        return replace(announcement, signature=sig)

    def verify_announcement(self, announcement: VersionAnnouncement) -> bool:
        expected = hmac.new(self._secret, announcement.canonical_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, announcement.signature)


class Ed25519Authority:
    """Public-key binding authority. Verifiers hold only the public key.

    Build a verifier with ``Ed25519Authority.verifier(key_id, public_key_b64)``;
    only the holder of the private key (``Ed25519Authority(key_id, private_key)``)
    can sign bindings and version announcements.
    """

    def __init__(self, key_id: str, private_key=None, *, public_key=None):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey, Ed25519PublicKey,
        )
        if not key_id:
            raise ProtocolError("key_id is required")
        if private_key is not None and not isinstance(private_key, Ed25519PrivateKey):
            raise ProtocolError("Ed25519 private key required")
        if private_key is None and not isinstance(public_key, Ed25519PublicKey):
            raise ProtocolError("Ed25519 public key required")
        self.key_id = key_id
        self._private = private_key
        self._public = private_key.public_key() if private_key is not None else public_key

    @classmethod
    def verifier(cls, key_id: str, public_key_b64: str) -> "Ed25519Authority":
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            raw = base64.b64decode(public_key_b64, validate=True)
            public = Ed25519PublicKey.from_public_bytes(raw)
        except Exception as exc:
            raise ProtocolError("invalid Ed25519 public key") from exc
        return cls(key_id, public_key=public)

    def public_key_b64(self) -> str:
        import base64
        from cryptography.hazmat.primitives import serialization
        raw = self._public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def _sign(self, data: bytes) -> str:
        if self._private is None:
            raise AuthorityError("verifier-only authority cannot sign")
        return self._private.sign(data).hex()

    def _verify(self, data: bytes, signature: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        try:
            self._public.verify(bytes.fromhex(signature), data)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def sign_binding(self, binding: AuthorityBinding) -> AuthorityBinding:
        if binding.authority_key_id != self.key_id:
            raise AuthorityError("binding authority key does not match signer")
        return replace(binding, signature=self._sign(binding.canonical_bytes()))

    def verify_binding(self, binding: AuthorityBinding) -> bool:
        return self._verify(binding.canonical_bytes(), binding.signature)

    def sign_announcement(self, announcement: VersionAnnouncement) -> VersionAnnouncement:
        if announcement.authority_key_id != self.key_id:
            raise AuthorityError("announcement authority key does not match signer")
        return replace(announcement, signature=self._sign(announcement.canonical_bytes()))

    def verify_announcement(self, announcement: VersionAnnouncement) -> bool:
        return self._verify(announcement.canonical_bytes(), announcement.signature)


class AuthoritativeRegistry:
    """Canonical authority state. Propagation is not authority."""

    def __init__(self, authorities: Iterable[Verifier]):
        self._authorities: Dict[str, Verifier] = {a.key_id: a for a in authorities}
        self._current: Dict[str, AuthorityBinding] = {}
        self._receipts: list[CommitReceipt] = []

    def _verify(self, binding: AuthorityBinding) -> None:
        authority = self._authorities.get(binding.authority_key_id)
        if authority is None:
            raise AuthorityError("unknown authority key")
        if not binding.signature or not authority.verify_binding(binding):
            raise SignatureError("invalid binding signature")

    def commit(self, binding: AuthorityBinding, *, now: datetime) -> CommitReceipt:
        if not binding.identity or not binding.carrier or not binding.endpoint:
            raise ProtocolError("identity, carrier and endpoint are required")
        if binding.version < 1:
            raise ChainError("version must be >= 1")
        if binding.valid_until <= binding.valid_from or not binding.active_at(now):
            raise FreshnessError("binding is not active at commit time")
        self._verify(binding)

        current = self._current.get(binding.identity)
        if current is None:
            if binding.version != 1 or binding.previous_digest is not None:
                raise ChainError("genesis must be version 1 with no predecessor")
        else:
            if binding.version != current.version + 1:
                raise ChainError("binding must advance exactly one version")
            if binding.previous_digest != current.digest():
                raise ChainError("binding does not extend current authoritative state")

        receipt = CommitReceipt(
            identity=binding.identity,
            version=binding.version,
            binding_digest=binding.digest(),
            previous_digest=binding.previous_digest,
            committed_at=now,
        )
        self._current[binding.identity] = binding
        self._receipts.append(receipt)
        return receipt

    def current(self, identity: str) -> AuthorityBinding | None:
        return self._current.get(identity)

    def receipts(self, identity: str | None = None) -> Tuple[CommitReceipt, ...]:
        if identity is None:
            return tuple(self._receipts)
        return tuple(r for r in self._receipts if r.identity == identity)


class VerifiedResolver:
    """Resolver that treats local state as a cache, never as authority by possession alone."""

    def __init__(self, authorities: Iterable[Verifier], *, source: str):
        self._authorities: Dict[str, Verifier] = {a.key_id: a for a in authorities}
        self._cache: Dict[str, AuthorityBinding] = {}
        self._known_authoritative_version: Dict[str, int] = {}
        self._announced_digests: Dict[tuple[str, int], str] = {}
        self.source = source

    def _verify_binding(self, binding: AuthorityBinding) -> None:
        authority = self._authorities.get(binding.authority_key_id)
        if authority is None or not authority.verify_binding(binding):
            raise SignatureError("binding cannot be verified")

    def accept_announcement(self, announcement: VersionAnnouncement) -> None:
        authority = self._authorities.get(announcement.authority_key_id)
        if authority is None or not authority.verify_announcement(announcement):
            raise SignatureError("announcement cannot be verified")
        key = (announcement.identity, announcement.version)
        existing_digest = self._announced_digests.get(key)
        if existing_digest is not None and existing_digest != announcement.binding_digest:
            raise ConflictError("conflicting signed announcement digest")
        known = self._known_authoritative_version.get(announcement.identity, 0)
        if announcement.version < known:
            return
        self._announced_digests[key] = announcement.binding_digest
        self._known_authoritative_version[announcement.identity] = announcement.version

    def cache_binding(self, binding: AuthorityBinding) -> None:
        self._verify_binding(binding)
        existing = self._cache.get(binding.identity)
        if existing is not None and binding.version == existing.version and binding.digest() != existing.digest():
            raise ConflictError("conflicting bindings for same identity/version")
        if existing is None or binding.version >= existing.version:
            self._cache[binding.identity] = binding

    def resolve(self, identity: str, *, now: datetime, minimum_version: int | None = None) -> tuple[AuthorityBinding, ResolutionReceipt]:
        binding = self._cache.get(identity)
        if binding is None:
            raise FreshnessError("no verified binding cached")
        self._verify_binding(binding)
        if not binding.active_at(now):
            raise FreshnessError("cached binding is expired or not yet valid")

        required = minimum_version or 0
        known = self._known_authoritative_version.get(identity, 0)
        required = max(required, known)
        if binding.version < required:
            raise FreshnessError(f"cached version {binding.version} is stale; version >= {required} required")
        announced = self._announced_digests.get((identity, binding.version))
        if announced is not None and announced != binding.digest():
            raise FreshnessError("cached signed binding conflicts with announced digest")

        receipt = ResolutionReceipt(
            identity=identity,
            requested_min_version=minimum_version,
            resolved_version=binding.version,
            binding_digest=binding.digest(),
            status=ResolutionStatus.RESOLVED,
            resolved_at=now,
            source=self.source,
        )
        return binding, receipt
