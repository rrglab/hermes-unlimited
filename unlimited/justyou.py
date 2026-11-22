"""JustYou session + signed profile binding verification for native Hermes.

The session_store and resolver must be provided by the trusted Hermes host.
An environment variable, token file or request payload cannot substitute.
"""
from datetime import datetime, timezone


class JustYouVerifier:
    def __init__(self, session_store, resolver, profile_name, session_token,
                 audience="hermes-unlimited", minimum_version=None):
        self.session_store = session_store
        self.resolver = resolver
        self.profile_name = profile_name
        self.session_token = session_token
        self.audience = audience
        self.minimum_version = minimum_version

    def verify(self):
        if self.audience != "hermes-unlimited":
            return {"verified": False, "reason": "AUDIENCE_INVALID"}
        if not isinstance(self.session_token, str) or not self.session_token.strip():
            return {"verified": False, "reason": "SESSION_REQUIRED"}
        if not isinstance(self.profile_name, str) or not self.profile_name.strip():
            return {"verified": False, "reason": "PROFILE_REQUIRED"}
        if not callable(getattr(self.session_store, "validate", None)):
            return {"verified": False, "reason": "SESSION_STORE_UNAVAILABLE"}
        if not callable(getattr(self.resolver, "resolve", None)):
            return {"verified": False, "reason": "RESOLVER_UNAVAILABLE"}
        try:
            session = self.session_store.validate(
                self.session_token, self.audience, required_scope="read-profile")
            if (getattr(session, "valid", None) is not True
                    or getattr(session, "authority", None) is not False
                    or getattr(session, "audience", None) != self.audience
                    or "read-profile" not in tuple(getattr(session, "scopes", ()) or ())):
                raise ValueError("invalid session")
            identity = getattr(session, "address", None)
            if not isinstance(identity, str) or not identity:
                raise ValueError("invalid identity")
            binding, receipt = self.resolver.resolve(
                identity, now=datetime.now(timezone.utc),
                minimum_version=self.minimum_version)
            if (binding.identity != identity or binding.carrier != "hermes-profile"
                    or binding.endpoint != f"hermes-profile:{self.profile_name}"
                    or receipt.identity != identity
                    or receipt.binding_digest != binding.digest()
                    or receipt.resolved_version != binding.version
                    or getattr(receipt.status, "value", receipt.status) != "RESOLVED"):
                raise ValueError("profile binding mismatch")
        except Exception:  # noqa: BLE001 - identity boundary must fail closed on any provider error
            return {"verified": False, "reason": "JUSTYOU_UNVERIFIED"}
        return {
            "verified": True,
            "identity": identity,
            "profile": self.profile_name,
            "binding_digest": receipt.binding_digest,
            "binding_version": binding.version,
            "authority_granted": False,
        }

    def authorize_provider_tenant(self, provider, tenant, expected_identity):
        evidence = self.verify()
        # Profile and provider/tenant scope are separate. Host must bind scope
        # and identity explicitly; no tenant can be asserted by a chat payload.
        return evidence.get("verified") is True and evidence["identity"] == expected_identity
