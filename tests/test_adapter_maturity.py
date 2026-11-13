import unittest
from unlimited.adapter_maturity import (
    AdapterDescriptor, AdapterEvidence, AdapterPolicyDenied, TenantAdapterPolicy,
)


class AdapterMaturityTests(unittest.TestCase):
    def setUp(self):
        self.policy = TenantAdapterPolicy((
            AdapterDescriptor("justyou", "CORE", ("identity.verify",), mandatory=True),
            AdapterDescriptor("memory", "VERIFIED", ("memory.read", "memory.write")),
            AdapterDescriptor("smtp", "EXPERIMENTAL", ("email.send",)),
        ))
        self.good = AdapterEvidence(
            "1.0.0", "a" * 64, "a" * 64,
            {k: "passed" for k in ("unit", "contract", "security", "integration")}, True,
        )

    def test_mandatory_justyou(self):
        with self.assertRaises(ValueError):
            TenantAdapterPolicy((AdapterDescriptor("memory", "CORE", ("read",)),))

    def test_no_baked_in_approvals(self):
        with self.assertRaises(AdapterPolicyDenied):
            self.policy.configure("tenant-a", {}, {})

    def test_verified_capability_and_tenant_isolation(self):
        self.policy.configure("tenant-a", {"memory": ("memory.read",)},
                              {"justyou": self.good, "memory": self.good})
        self.assertTrue(self.policy.check("tenant-a", "memory", "memory.read"))
        for tenant, adapter, cap in (
            ("tenant-b", "memory", "memory.read"),
            ("tenant-a", "memory", "memory.write"),
            ("tenant-a", "smtp", "email.send"),
        ):
            with self.assertRaises(AdapterPolicyDenied):
                self.policy.check(tenant, adapter, cap)

    def test_experimental_cannot_be_claimed_as_verified(self):
        with self.assertRaises(AdapterPolicyDenied):
            self.policy.configure("t", {"smtp": ("email.send",)},
                                  {"justyou": self.good, "smtp": self.good})

    def test_missing_and_stale_evidence_fail_closed(self):
        for bad in (
            AdapterEvidence("1.0.0", "a"*64, "b"*64, self.good.checks, True),
            AdapterEvidence("1.0.0", "a"*64, "a"*64, {}, True),
            AdapterEvidence("1.0.0", "a"*64, "a"*64, self.good.checks, False),
        ):
            with self.assertRaises(AdapterPolicyDenied):
                self.policy.configure("t", {}, {"justyou": bad})

    def test_invalid_capability_and_duplicate_registration(self):
        with self.assertRaises(AdapterPolicyDenied):
            self.policy.configure("t", {"memory": ("memory.delete",)},
                                  {"justyou": self.good, "memory": self.good})
        with self.assertRaises(ValueError):
            TenantAdapterPolicy((
                AdapterDescriptor("justyou", "CORE", ("identity.verify",), mandatory=True),
                AdapterDescriptor("justyou", "CORE", ("identity.verify",), mandatory=True),
            ))

    def test_no_execution_authority(self):
        self.assertFalse(hasattr(self.policy, "execute"))
        self.assertFalse(hasattr(self.policy, "authorize_effect"))
        self.assertFalse(hasattr(self.policy, "issue_permit"))


if __name__ == "__main__":
    unittest.main()
