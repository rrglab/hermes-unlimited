"""Offline procurement mandate tests. No payment or supplier effects."""
import unittest
from unlimited.commerce_policy import CommercePolicyError, evaluate_purchase

M = dict(tenant_id="acme", principal_id="buyer", agent_id="procurement", mandate_id="m-1",
         currency="NOK", max_amount_minor=100000, approved_suppliers=["supplier-a"],
         allowed_categories=["office"], expires_at="2026-12-01T00:00:00Z")
P = dict(tenant_id="acme", principal_id="buyer", agent_id="procurement", order_id="o-1",
         currency="NOK", amount_minor=10000, supplier_id="supplier-a", category="office",
         created_at="2026-11-15T10:00:00Z")

class PurchasePolicyTests(unittest.TestCase):
    def check(self, verdict, *, mandate=None, proposal=None):
        d = evaluate_purchase(mandate=M if mandate is None else mandate,
                              proposal=P if proposal is None else proposal)
        self.assertEqual(d.verdict, verdict)
        self.assertFalse(d.as_dict()["execution_authorized"])
        return d

    def test_valid_proposal_remains_unapproved(self):
        self.assertEqual(self.check("ELIGIBLE_FOR_HOST_REVIEW").reasons, ())

    def test_scope_mismatch(self):
        for key in ("tenant_id", "principal_id", "agent_id", "currency"):
            with self.subTest(key=key):
                self.assertIn(key.upper()+"_MISMATCH", self.check("DENY",proposal={**P,key:"other"}).reasons)

    def test_supplier_category_and_amount(self):
        for key, value in (("supplier_id","rogue"),("category","devices"),("amount_minor",100001)):
            with self.subTest(key=key):
                self.check("DENY",proposal={**P,key:value})

    def test_expiry_and_timezones(self):
        self.assertIn("MANDATE_EXPIRED",self.check("DENY",proposal={**P,"created_at":"2026-12-01T00:00:00Z"}).reasons)
        self.check("DENY",proposal={**P,"created_at":"2026-11-15T10:00:00"})
        self.check("ELIGIBLE_FOR_HOST_REVIEW",proposal={**P,"created_at":"2026-11-15T11:00:00+01:00"})

    def test_missing_and_invalid_fields(self):
        for p in ({**P,"amount_minor":True},{**P,"amount_minor":-1},{k:v for k,v in P.items() if k!="order_id"}):
            self.check("DENY",proposal=p)
        for m in ({**M,"approved_suppliers":[]},{**M,"max_amount_minor":0}):
            self.check("DENY",mandate=m)
        with self.assertRaises(CommercePolicyError):
            evaluate_purchase(mandate=M,proposal={**P,"untrusted":float("nan")})

    def test_proposal_digest_prevents_payload_substitution(self):
        a=self.check("ELIGIBLE_FOR_HOST_REVIEW")
        b=self.check("ELIGIBLE_FOR_HOST_REVIEW",proposal={**P,"order_id":"o-2"})
        self.assertNotEqual(a.proposal_digest,b.proposal_digest)

if __name__ == "__main__":
    unittest.main()
