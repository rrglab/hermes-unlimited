import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unlimited.customer_connections import CustomerConnectionRegistry


class CustomerConnectionTests(unittest.TestCase):
    def test_tenant_self_connect_dispatch_disconnect_and_no_secret_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'connections.sqlite')
            registry = CustomerConnectionRegistry(db, lambda t, i: i == 'owner' and t == 'tenant-1')
            args = dict(tenant_id='tenant-1', identity='owner', connection_id='mail',
                provider='smtp', secret_ref='vault://tenant-1/mail',
                config={'host':'smtp.example.org', 'sender':'sender@example.org'})
            with self.assertRaises(PermissionError):
                registry.connect(**args)
            registry.connect(**args, authorized=True)
            with self.assertRaises(PermissionError):
                registry.get(tenant_id='tenant-1', identity='intruder', connection_id='mail')
            smtp = Mock()
            smtp.__enter__ = Mock(return_value=smtp)
            smtp.__exit__ = Mock(return_value=False)
            smtp.send_message.return_value = {}
            adapter = registry.resolve_adapter(tenant_id='tenant-1', identity='owner', connection_id='mail',
                secret_resolver=lambda t, ref: {'username':'user', 'password':'test-only-secret'},
                smtp_factory=Mock(return_value=smtp))
            receipt = adapter.send(tenant_id='tenant-1', identity='owner', effect_id='effect-1',
                recipient='recipient@example.org', subject='Test', body='Hello',
                verify_identity=lambda t,i: True, approve_effect=lambda t,i,e: True, authorized=True)
            self.assertEqual(receipt.state, 'provider_accepted')
            self.assertFalse(receipt.externally_delivered)
            self.assertNotIn(b'test-only-secret', Path(db).read_bytes())
            registry.disconnect(tenant_id='tenant-1', identity='owner', connection_id='mail', authorized=True)
            with self.assertRaises(LookupError):
                registry.get(tenant_id='tenant-1', identity='owner', connection_id='mail')

    def test_stripe_customer_connection_is_isolated_and_does_not_charge(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CustomerConnectionRegistry(str(Path(folder)/'connections.sqlite'), lambda t,i: i == 'owner')
            registry.connect(tenant_id='tenant-a', identity='owner', connection_id='pay',
                provider='stripe', secret_ref='vault://tenant-a/stripe', config={}, authorized=True)
            with self.assertRaises(LookupError):
                registry.get(tenant_id='tenant-b', identity='owner', connection_id='pay')
            stripe = Mock()
            stripe.PaymentIntent.create.return_value = {'id':'pi_test_1'}
            adapter = registry.resolve_adapter(tenant_id='tenant-a', identity='owner', connection_id='pay',
                secret_resolver=lambda t,r: {'api_key':'sk_test_local'}, stripe_client=stripe)
            receipt = adapter.create_payment_intent(tenant_id='tenant-a', identity='owner', effect_id='effect-2',
                amount_minor=1000, currency='NOK', customer_id='cus_test',
                verify_identity=lambda t,i: True, approve_effect=lambda t,i,e: True, authorized=True)
            self.assertEqual(receipt.state,'requires_action')
            self.assertFalse(receipt.externally_delivered)
            self.assertFalse(stripe.PaymentIntent.create.call_args.kwargs['confirm'])

    def test_credentials_cannot_be_inserted_as_config(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CustomerConnectionRegistry(str(Path(folder)/'db'), lambda t,i: True)
            with self.assertRaises(ValueError):
                registry.connect(tenant_id='t', identity='i', connection_id='x', provider='stripe',
                    secret_ref='vault://t/key', config={'api_key':'sk_test_secret'}, authorized=True)

if __name__ == '__main__': unittest.main()
