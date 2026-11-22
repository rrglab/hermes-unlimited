"""Trusted JustYou host adapter for the standalone Hermes plugin.

Only a loopback JustYou validator and signed authority bindings are accepted.
The bindings cache and session token do not independently grant authority.
"""
import errno
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class _Session:
    valid: bool
    address: str
    audience: str
    scopes: tuple
    authority: bool = False


class LoopbackSessionStore:
    def __init__(self, endpoint):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or not parsed.port or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("JUSTYOU_LOOPBACK_ONLY")
        self.url = endpoint.rstrip("/") + "/session/validate"

    def validate(self, token, audience, required_scope=None):
        if not isinstance(token, str) or not token:
            raise ValueError("SESSION_REQUIRED")
        body = json.dumps({"token": token, "audience": audience,
                           "required_scope": required_scope}).encode("utf-8")
        request = Request(self.url, data=body, method="POST",
                          headers={"Content-Type": "application/json"})
        # Never send an identity token through an inherited HTTP proxy.
        with build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=2) as response:
            if response.status != 200:
                raise ValueError("SESSION_INVALID")
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("SESSION_RESPONSE_OVERSIZE")
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get("valid") is not True
                or value.get("authority") is not False or value.get("audience") != audience
                or not isinstance(value.get("address"), str) or not value["address"]
                or not isinstance(value.get("scopes"), list)
                or not all(isinstance(s, str) for s in value["scopes"])
                or required_scope not in value["scopes"]):
            raise ValueError("SESSION_INVALID")
        return _Session(True, value["address"], audience, tuple(value["scopes"]))


def _private_bytes(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EPERM, errno.EACCES):
            raise PermissionError("JUSTYOU_PRIVATE_FILE_REQUIRED") from exc
        raise
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if (not stat.S_ISREG(st.st_mode)
                or st.st_mode & 0o077
                or st.st_nlink != 1
                or (hasattr(os, "geteuid") and st.st_uid not in (0, os.geteuid()))):
            raise PermissionError("JUSTYOU_PRIVATE_FILE_REQUIRED")
        data = handle.read(16385)
    if len(data) > 16384:
        raise ValueError("JUSTYOU_FILE_OVERSIZE")
    return data


def load_resolver_document(document, authority_key_id, authority_public_key, authority_kind="ed25519"):
    """Use a pinned PUBLIC verification key; the binding document remains untrusted."""
    from .authoritative_binding import (
        AuthorityBinding,
        Ed25519Authority,
        VerifiedResolver,
        VersionAnnouncement,
    )
    if authority_kind != "ed25519":
        raise ValueError("JUSTYOU_AUTHORITY_KIND_INVALID")
    if (not isinstance(document, dict)
            or not isinstance(document.get("bindings"), list)
            or not isinstance(document.get("announcements", []), list)):
        raise TypeError("JUSTYOU_BINDINGS_INVALID")
    if len(document["bindings"]) > 64 or len(document.get("announcements", [])) > 64:
        raise ValueError("JUSTYOU_BINDINGS_OVERSIZE")
    authority = Ed25519Authority.verifier(authority_key_id, authority_public_key)
    resolver = VerifiedResolver([authority], source="justyou-authoritative")

    def dt(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    for item in document["bindings"]:
        resolver.cache_binding(AuthorityBinding(
            identity=item["identity"], version=item["version"], carrier=item["carrier"],
            endpoint=item["endpoint"], endpoint_key_id=item["endpoint_key_id"],
            authority_key_id=item["authority_key_id"], valid_from=dt(item["valid_from"]),
            valid_until=dt(item["valid_until"]), previous_digest=item.get("previous_digest"),
            policy_digest=item.get("policy_digest"), signature=item["signature"]))
    for item in document.get("announcements", []):
        resolver.accept_announcement(VersionAnnouncement(
            identity=item["identity"], version=item["version"],
            binding_digest=item["binding_digest"], announced_at=dt(item["announced_at"]),
            authority_key_id=item["authority_key_id"], signature=item["signature"]))
    return resolver


def load_resolver(bindings_path, authority_key_id, authority_key_file, authority_kind="ed25519"):
    """Explicitly trusted host-side provisioning helper; not called by the plugin fallback."""
    document = json.loads(_private_bytes(bindings_path))
    return load_resolver_document(
        document, authority_key_id, _private_bytes(authority_key_file).strip().decode("ascii"),
        authority_kind)


def load_resolver_from_settings(ctx, scoped_secret):
    """Hermes profile settings contain only a PUBLIC key and signed, untrusted data.

    No filesystem paths, private signing keys or unauthenticated identity claims.
    Signing authority is verified by Ed25519 before a binding can resolve.
    """
    config = getattr(ctx, "get_config", None)
    if not callable(config):
        return None
    key_id = config("JUSTYOU_TRUSTED_AUTHORITY_KEY_ID", "")
    public_key = scoped_secret("HERMES_UNLIMITED_JUSTYOU_AUTHORITY_PUBLIC_KEY", "")
    signed_json = config("JUSTYOU_SIGNED_BINDINGS_JSON", "")
    if not any((key_id, public_key, signed_json)):
        return None
    if not all(isinstance(x, str) and x for x in (key_id, public_key, signed_json)):
        raise ValueError("JUSTYOU_TRUST_CONFIG_INCOMPLETE")
    if len(signed_json.encode("utf-8")) > 16384:
        raise ValueError("JUSTYOU_BINDINGS_OVERSIZE")
    return load_resolver_document(json.loads(signed_json), key_id, public_key)


def trusted_components(ctx, scoped_secret):
    """Prefer host injection; otherwise build from profile-scoped trusted settings."""
    store = getattr(ctx, "justyou_session_store", None)
    if store is None:
        endpoint = scoped_secret("HERMES_UNLIMITED_JUSTYOU_REGISTRY_URL", "")
        if endpoint:
            store = LoopbackSessionStore(endpoint)

    token = getattr(ctx, "justyou_session_token", None)
    if token is None:
        token = scoped_secret("HERMES_UNLIMITED_JUSTYOU_SESSION_TOKEN", "")

    # Trusted host injection wins. Otherwise only Ed25519-signed profile data may
    # provide a resolver; plugin-controlled file paths are never read.
    resolver = getattr(ctx, "justyou_resolver", None)
    if resolver is None:
        resolver = load_resolver_from_settings(ctx, scoped_secret)
    return store, resolver, token
