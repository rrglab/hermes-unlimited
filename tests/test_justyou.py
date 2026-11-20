import unittest
from types import SimpleNamespace

from unlimited.justyou import JustYouVerifier


class Binding:
    identity = "@owner"
    carrier = "hermes-profile"
    endpoint = "hermes-profile:owner-test"
    version = 2

    def digest(self):
        return "binding-digest"


class Resolver:
    def resolve(self, identity, **kwargs):
        return Binding(), SimpleNamespace(
            identity=identity, binding_digest="binding-digest",
            resolved_version=2, status="RESOLVED")


class SessionStore:
    def validate(self, token, audience, required_scope):
        return SimpleNamespace(valid=True, authority=False, audience=audience,
                               scopes=("read-profile",), address="@owner")


class JustYouVerifierTests(unittest.TestCase):
    def verifier(self, **changes):
        params = {"session_store": SessionStore(), "resolver": Resolver(),
                  "profile_name": "owner-test", "session_token": "session"}
        params.update(changes)
        return JustYouVerifier(**params)

    def test_valid_signed_binding(self):
        evidence = self.verifier().verify()
        self.assertTrue(evidence["verified"])
        self.assertFalse(evidence["authority_granted"])

    def test_missing_token_fails(self):
        self.assertFalse(self.verifier(session_token="").verify()["verified"])

    def test_wrong_profile_fails(self):
        self.assertFalse(self.verifier(profile_name="other-profile").verify()["verified"])

    def test_untrusted_session_fails(self):
        class InvalidSession(SessionStore):
            def validate(self, *args, **kwargs):
                session = super().validate(*args, **kwargs)
                session.authority = True
                return session
        self.assertFalse(self.verifier(session_store=InvalidSession()).verify()["verified"])

    def test_missing_resolver_fails(self):
        self.assertFalse(self.verifier(resolver=None).verify()["verified"])


if __name__ == "__main__":
    unittest.main()
