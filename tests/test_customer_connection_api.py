import tempfile
import unittest
from pathlib import Path
from unlimited.customer_connections import CustomerConnectionRegistry
from unlimited.customer_connection_api import CustomerConnectionController


class ConnectionAPITests(unittest.TestCase):
    def test_authenticated_self_service_and_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CustomerConnectionRegistry(str(Path(folder)/'db'),
                                                  lambda tenant, actor: actor == 'captain')
            def auth(session):
                if session == 'a': return 'tenant-a','captain'
                if session == 'b': return 'tenant-b','captain'
                raise PermissionError('NO_SESSION')
            api = CustomerConnectionController(registry, auth)
            payload = {'provider':'smtp','connection_id':'mail',
                'secret_ref':'vault://tenant-a/mail',
                'config':{'host':'smtp.example.org','sender':'sender@example.org'}}
            with self.assertRaises(PermissionError): api.connect('invalid',payload)
            with self.assertRaises(PermissionError): api.connect('b',payload)
            self.assertTrue(api.connect('a',payload)['enabled'])
            self.assertEqual(api.get('a','mail')['provider'],'smtp')
            with self.assertRaises(LookupError): api.get('b','mail')
            api.disconnect('a','mail')
            with self.assertRaises(LookupError): api.get('a','mail')

if __name__ == '__main__': unittest.main()
