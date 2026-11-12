import unittest
import subprocess
import sys

from unlimited.authoritative_binding import (
    AuthorityBinding, Ed25519Authority, HmacAuthority,
    VerifiedResolver, VersionAnnouncement,
)


class StandaloneVerifierTests(unittest.TestCase):
    def test_bundled_verifier_imports_without_protocol_package(self):
        self.assertTrue(callable(VerifiedResolver))
        self.assertTrue(callable(AuthorityBinding))
        self.assertTrue(callable(VersionAnnouncement))
        isolated = subprocess.run(
            [sys.executable, "-c",
             "import builtins; old=builtins.__import__; "
             "builtins.__import__=lambda name,*a,**k: "
             "(_ for _ in ()).throw(ImportError('protocol denied')) "
             "if name=='protocol' or name.startswith('protocol.') else old(name,*a,**k); "
             "from unlimited.authoritative_binding import VerifiedResolver; "
             "assert callable(VerifiedResolver)"],
            capture_output=True, text=True, check=False)
        self.assertEqual(isolated.returncode, 0, isolated.stderr)

    def test_signed_ed25519_announcement_digest_mismatch_fails_closed(self):
        from dataclasses import replace
        from datetime import datetime, timedelta, timezone
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from unlimited.authoritative_binding import FreshnessError, ConflictError
        now = datetime.now(timezone.utc)
        signer = Ed25519Authority("test-key", Ed25519PrivateKey.generate())
        verifier = VerifiedResolver([Ed25519Authority.verifier(
            "test-key", signer.public_key_b64())], source="unit")
        binding = signer.sign_binding(AuthorityBinding(
            identity="@test", version=1, carrier="hermes-profile",
            endpoint="hermes-profile:agent", endpoint_key_id="agent",
            authority_key_id="test-key", valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(hours=1)))
        verifier.cache_binding(binding)
        valid = signer.sign_announcement(VersionAnnouncement(
            identity="@test", version=1, binding_digest=binding.digest(),
            announced_at=now, authority_key_id="test-key"))
        verifier.accept_announcement(valid)
        self.assertEqual(verifier.resolve("@test", now=now)[0], binding)
        mismatch = signer.sign_announcement(replace(valid, binding_digest="bad-digest", signature=""))
        with self.assertRaises(ConflictError):
            verifier.accept_announcement(mismatch)
        isolated = VerifiedResolver([Ed25519Authority.verifier(
            "test-key", signer.public_key_b64())], source="unit")
        isolated.cache_binding(binding)
        isolated.accept_announcement(mismatch)
        with self.assertRaises(FreshnessError):
            isolated.resolve("@test", now=now)

    def test_hmac_signature_rejects_altered_binding(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        authority = HmacAuthority("test", b"unit-test-only")
        original = AuthorityBinding(identity="@test", version=1, carrier="hermes-profile",
                                    endpoint="hermes-profile:agent", endpoint_key_id="agent",
                                    authority_key_id="test", valid_from=now,
                                    valid_until=now + timedelta(hours=1))
        signed = authority.sign_binding(original)
        self.assertTrue(authority.verify_binding(signed))
        from dataclasses import replace
        self.assertFalse(authority.verify_binding(replace(signed, endpoint="changed")))


if __name__ == "__main__":
    unittest.main()
