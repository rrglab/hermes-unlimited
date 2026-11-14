"""Offline signed mandate acceptance tests; no payments."""
import unittest
from datetime import datetime, timezone
from unlimited.commerce_mandate import MandateRejected, sign_test_mandate, preflight_signed_purchase
from test_commerce_policy import M, P

KEY = b"f"*32
NOW = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)

class SignedMandateTests(unittest.TestCase):
    def check(self, *, mandate=None, proposal=None, signature=None, key=KEY, now=NOW, revoked=lambda _:False):
        mandate = M if mandate is None else mandate
        return preflight_signed_purchase(
            mandate=mandate, proposal=P if proposal is None else proposal,
            signature=sign_test_mandate(mandate, secret=KEY) if signature is None else signature,
            trusted_secret=key, trusted_now=now, is_revoked=revoked)

    def test_good_signed_mandate_remains_advisory(self):
        d=self.check()
        self.assertEqual(d.verdict, "ELIGIBLE_FOR_HOST_REVIEW")
        self.assertFalse(d.execution_authorized)

    def test_tampered_mandate_rejected(self):
        signature=sign_test_mandate(M, secret=KEY)
        self.assertEqual(self.check(mandate={**M,"max_amount_minor":999999}, signature=signature).reason,"SIGNATURE_MISMATCH")

    def test_different_key_rejected(self):
        self.assertEqual(self.check(key=b"z"*32).reason,"SIGNATURE_MISMATCH")

    def test_revoked_and_expired(self):
        self.assertEqual(self.check(revoked=lambda _:True).reason,"MANDATE_REVOKED")
        self.assertEqual(self.check(now=datetime(2026,12,1,tzinfo=timezone.utc)).reason,"MANDATE_EXPIRED")

    def test_missing_trust_dependencies_fail_closed(self):
        with self.assertRaises(MandateRejected): self.check(revoked=None)
        with self.assertRaises(MandateRejected): self.check(now=datetime(2026,11,15))
        with self.assertRaises(MandateRejected): self.check(key=b"short")

    def test_proposal_policy_rejection_survives_valid_signature(self):
        d=self.check(proposal={**P,"supplier_id":"not-allowed"})
        self.assertEqual(d.verdict,"DENY")
        self.assertIn("SUPPLIER_NOT_APPROVED",d.reason)

if __name__ == "__main__":
    unittest.main()
