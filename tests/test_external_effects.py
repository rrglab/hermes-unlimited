import unittest
from unittest.mock import Mock
from unlimited.external_effects import SMTPDeliveryAdapter, StripePaymentAdapter, verify_stripe_webhook


class ExternalEffectTests(unittest.TestCase):
    def setUp(self):
        self.verify = lambda tenant, identity: (tenant, identity) == ("tenant-a", "captain")
        self.approve = lambda tenant, identity, effect: effect == "effect-1"
        self.scope = dict(tenant_id="tenant-a", identity="captain", effect_id="effect-1",
                          verify_identity=self.verify, approve_effect=self.approve)

    def test_email_requires_approval_and_records_acceptance_not_delivery(self):
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        smtp.send_message.return_value = {}
        factory = Mock(return_value=smtp)
        adapter = SMTPDeliveryAdapter(host="mail.example", username="user", password="secret",
                                      sender="sender@example.org", smtp_factory=factory)
        params = dict(self.scope, recipient="user@example.org", subject="Report", body="Done")
        with self.assertRaises(PermissionError):
            adapter.send(**params)
        factory.assert_not_called()
        receipt = adapter.send(**params, authorized=True)
        self.assertEqual(receipt.state, "provider_accepted")
        self.assertFalse(receipt.externally_delivered)
        self.assertEqual(smtp.send_message.call_count, 1)

    def test_payment_requires_approval_and_never_auto_captures(self):
        client = Mock()
        client.PaymentIntent.create.return_value = {"id": "pi_test", "status": "requires_payment_method"}
        adapter = StripePaymentAdapter(api_key="sk_test_placeholder", stripe_client=client)
        params = dict(self.scope, amount_minor=1200, currency="NOK", customer_id="cus_test")
        with self.assertRaises(PermissionError):
            adapter.create_payment_intent(**params)
        client.PaymentIntent.create.assert_not_called()
        receipt = adapter.create_payment_intent(**params, authorized=True)
        self.assertEqual(receipt.state, "requires_action")
        self.assertFalse(receipt.externally_delivered)
        kwargs = client.PaymentIntent.create.call_args.kwargs
        self.assertFalse(kwargs["confirm"])
        self.assertEqual(kwargs["capture_method"], "manual")
        self.assertEqual(kwargs["idempotency_key"], "hermes:tenant-a:effect-1")

    def test_webhook_requires_signature_and_never_infers_settlement(self):
        client = Mock()
        client.Webhook.construct_event.return_value = {
            "id": "evt_test", "type": "payment_intent.processing",
            "data": {"object": {"id": "pi_test", "status": "processing"}}}
        with self.assertRaises(PermissionError):
            verify_stripe_webhook(payload=b"{}", signature="", webhook_secret="secret", stripe_client=client)
        result = verify_stripe_webhook(payload=b"{}", signature="sig", webhook_secret="secret", stripe_client=client)
        self.assertFalse(result["settled"])

if __name__ == "__main__":
    unittest.main()

class CompanyOSDispatchTests(unittest.TestCase):
    def test_outbox_dispatch_is_approval_gated_and_idempotent(self):
        import json
        import sqlite3
        import tempfile
        from pathlib import Path
        from unlimited.company_os import AuthorizedCustomerDeliveryChannel, CustomerDeliveryReceipt
        from unlimited.external_effects import ExternalEffectReceipt
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "outbox.sqlite")
            channel = AuthorizedCustomerDeliveryChannel(
                db_path, lambda provider, tenant, identity: (provider, tenant, identity) == ("owner", "t", "captain"),
                verifier=Mock())
            receipt = CustomerDeliveryReceipt(
                delivery_id="dlv-1", provider_id="owner", tenant_id="t", company_id="co",
                objective_id="obj", service_id="svc", customer_id="customer",
                channel="transactional_outbox", authorized_by_identity="captain",
                external_effect_authorized=True, deliverable_digest="digest", verifier_seal="seal",
                message_subject="Report", message_body="Verified", receipt_digest="hash", created_at=1.0)
            with sqlite3.connect(db_path) as db:
                db.execute("INSERT INTO customer_delivery_outbox VALUES (?,?,?,?,?,?,?,?)",
                           ("key", "dlv-1", "owner", "t", "co", "obj", "customer", json.dumps(receipt.as_dict())))
            adapter = Mock()
            adapter.send.return_value = ExternalEffectReceipt("email", "t", "dlv-1", "provider_accepted", "dlv-1", "digest")
            kwargs = dict(provider_id="owner", tenant_id="t", company_id="co", identity="captain",
                          delivery_id="dlv-1", recipient="customer@example.org", email_adapter=adapter,
                          approve_effect=lambda t, i, e: e == "dlv-1")
            with self.assertRaises(PermissionError):
                channel.dispatch_queued_email(**kwargs)
            adapter.send.assert_not_called()
            first = channel.dispatch_queued_email(**kwargs, authorize_external_effect=True)
            second = channel.dispatch_queued_email(**kwargs, authorize_external_effect=True)
            self.assertEqual(first, second)
            adapter.send.assert_called_once()
            self.assertFalse(first.externally_delivered)
            with self.assertRaises(PermissionError):
                channel.dispatch_queued_email(**{**kwargs, "tenant_id": "other"}, authorize_external_effect=True)
