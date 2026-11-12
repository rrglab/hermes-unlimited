"""Trusted JustYou host adapter for the standalone Hermes plugin.

Only a loopback JustYou validator and signed authority bindings are accepted.
The bindings cache and session token do not independently grant authority.
"""
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
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
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
    mode = os.stat(path).st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise PermissionError("JUSTYOU_PRIVATE_FILE_REQUIRED")
    with open(path, "rb") as handle:
        data = handle.read(16385)
    if len(data) > 16384:
        raise ValueError("JUSTYOU_FILE_OVERSIZE")
    return data


def load_resolver(bindings_path, authority_key_id, authority_key_file, authority_kind="ed25519"):
    from .authoritative_binding import (AuthorityBinding, Ed25519Authority,
                                                VerifiedResolver,
                                                VersionAnnouncement)
    material = _private_bytes(authority_key_file).strip()
    if authority_kind == "ed25519":
        authority = Ed25519Authority.verifier(authority_key_id, material.decode("ascii"))
    else:
        raise ValueError("JUSTYOU_AUTHORITY_KIND_INVALID")
    resolver = VerifiedResolver([authority], source="justyou-authoritative")
    document = json.loads(_private_bytes(bindings_path))

    def dt(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    for item in document.get("bindings", []):
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

    resolver = getattr(ctx, "justyou_resolver", None)
    if resolver is None:
        bindings = scoped_secret("JUSTYOU_BINDINGS_FILE", "")
        key_id = scoped_secret("JUSTYOU_AUTHORITY_KEY_ID", "")
        key_file = scoped_secret("JUSTYOU_AUTHORITY_KEY_FILE", "")
        if bindings and key_id and key_file:
            resolver = load_resolver(bindings, key_id, key_file,
                                     scoped_secret("JUSTYOU_AUTHORITY_KIND", "ed25519"))
    return store, resolver, token
