"""JustYou to optional Tailcat transport adapter contract (offline)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from unlimited.justyou_endpoint_bridge import EndpointBinding, EndpointDenied, JustYouEndpointBridge
from unlimited.tailcat_transport import TailcatTransport

ADDRESS = "tc" + "A" * 40


class EndpointBridgeTests(unittest.TestCase):
    def setUp(self):
        self.binding = EndpointBinding(
            "@owner", "provider-a", "tenant-a", "research", ADDRESS, 8080,
            datetime.now(timezone.utc) + timedelta(minutes=5))
        self.verify = Mock(return_value={
            "verified": True, "identity": "@owner", "binding_digest": "signed-profile",
            "authority_granted": False,
        })
        self.resolve = Mock(return_value=self.binding)
        self.authorize = Mock(return_value=True)
        self.transport = Mock(spec=TailcatTransport)
        self.transport.exchange.return_value = b"response"
        self.bridge = JustYouEndpointBridge(
            self.verify, self.resolve, self.authorize, self.transport)

    def exchange(self):
        return self.bridge.exchange(
            provider="provider-a", tenant="tenant-a",
            service="research", payload=b"request", max_bytes=16)

    def test_resolved_scoped_transport(self):
        self.assertEqual(self.exchange(), b"response")
        self.resolve.assert_called_once_with("@owner", "provider-a", "tenant-a", "research")
        self.authorize.assert_called_once_with(self.binding)
        self.transport.exchange.assert_called_once_with(ADDRESS, 8080, b"request", max_bytes=16)

    def test_identity_unverified_fails_closed(self):
        self.verify.return_value = {"verified": False}
        with self.assertRaises(EndpointDenied):
            self.exchange()
        self.resolve.assert_not_called()
        self.transport.exchange.assert_not_called()

    def test_profile_evidence_not_an_execution_permit(self):
        self.verify.return_value["authority_granted"] = True
        with self.assertRaises(EndpointDenied):
            self.exchange()
        self.transport.exchange.assert_not_called()

    def test_mismatched_tenant_fails_closed(self):
        self.binding = EndpointBinding(
            "@owner", "provider-a", "other-tenant", "research", ADDRESS, 8080,
            datetime.now(timezone.utc) + timedelta(minutes=5))
        self.resolve.return_value = self.binding
        with self.assertRaisesRegex(EndpointDenied, "SCOPE_MISMATCH"):
            self.exchange()
        self.transport.exchange.assert_not_called()

    def test_expired_binding_fails_closed(self):
        self.resolve.return_value = EndpointBinding(
            "@owner", "provider-a", "tenant-a", "research", ADDRESS, 8080,
            datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaisesRegex(EndpointDenied, "ENDPOINT_EXPIRED"):
            self.exchange()
        self.transport.exchange.assert_not_called()

    def test_host_denial_fails_closed(self):
        self.authorize.return_value = False
        with self.assertRaisesRegex(EndpointDenied, "ENDPOINT_NOT_AUTHORIZED"):
            self.exchange()
        self.transport.exchange.assert_not_called()

    def test_host_failure_does_not_expose_secret(self):
        self.resolve.side_effect = RuntimeError(ADDRESS)
        with self.assertRaises(EndpointDenied) as error:
            self.exchange()
        self.assertNotIn(ADDRESS, str(error.exception))
        self.assertIsNone(error.exception.__cause__)
        self.transport.exchange.assert_not_called()

    def test_invalid_binding_fails(self):
        with self.assertRaises(ValueError):
            EndpointBinding("@owner", "provider-a", "tenant-a", "research",
                            ADDRESS, 8080, datetime.now())


if __name__ == "__main__":
    unittest.main()
