"""Authenticated loopback bridge exercising native Hermes tool identity scope."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from unlimited.a2ui_adapter import company_surface, request_surface
from unlimited.a2ui_bridge import make_bridge, new_transport_token
from unlimited.runtime import ProviderStore


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tenant = 'tenant1'
        self.store = ProviderStore(Path(self.tmp.name)/'db', lambda p,t,i: p=='provider1' and t=='tenant1' and i=='valid')
        self.store.create_company('provider1','tenant1','acme','Acme', 'valid')
        self.store.publish_service('provider1','tenant1','acme','review','Review',0,'NOK','valid')
        self.store.request_service('provider1','tenant1','acme','r1','review',{'private':'NEVER_EXPORT'},'valid')
        self.calls = []
        def native_tool(args):
            self.calls.append(args)
            if self.tenant != 'tenant1':
                return json.dumps({'ok':False,'reason':'PermissionError'})
            try:
                if args['view']=='companies':
                    data = company_surface(self.store,'provider1',self.tenant,'valid',surface_id=args['surface_id'])
                else:
                    data = request_surface(self.store,'provider1',self.tenant,args['company_id'],'valid',surface_id=args['surface_id'])
                return json.dumps(data)
            except PermissionError:
                return json.dumps({'ok':False})
        self.token = new_transport_token()
        self.server = make_bridge(native_tool,token=self.token)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self,path,token=None,method='GET',headers=None):
        h={'Authorization':'Bearer '+token} if token is not None else {}
        h.update(headers or {})
        request=urllib.request.Request(self.url+path,headers=h,method=method)
        try:
            with urllib.request.urlopen(request,timeout=3) as response:
                return response.status,response.read().decode(),response.headers
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read().decode(),exc.headers

    def test_live_companies_native_tool_and_security_headers(self):
        status, body, hdr = self.request('/api/surface?view=companies&surface_id=companies_live',self.token)
        self.assertEqual(status,200)
        self.assertIn('Acme',body)
        self.assertEqual(hdr['Cache-Control'],'no-store, no-cache, must-revalidate')
        self.assertIn('frame-ancestors',hdr['Content-Security-Policy'])
        self.assertEqual(self.calls,[{'view':'companies','surface_id':'companies_live'}])

    def test_requests_do_not_export_payload(self):
        status,body,_=self.request('/api/surface?view=requests&company_id=acme&surface_id=req_live',self.token)
        self.assertEqual(status,200)
        self.assertIn('r1',body)
        self.assertNotIn('NEVER_EXPORT',body)

    def test_auth_denied_without_native_call(self):
        self.assertEqual(self.request('/api/surface?view=companies&surface_id=companies_live')[0],401)
        self.assertEqual(self.request('/api/surface?view=companies&surface_id=companies_live','wrong')[0],401)
        self.assertEqual(self.calls,[])

    def test_invalid_scope_and_cross_origin_denied(self):
        self.assertEqual(self.request('/api/surface?view=requests&company_id=../other&surface_id=ok',self.token)[0],400)
        self.assertEqual(self.request('/api/surface?view=companies&surface_id=ok',self.token,headers={'Origin':'https://untrusted.example'})[0],403)
        self.assertEqual(self.request('/api/surface?view=companies&surface_id=ok',self.token,headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.calls,[])

    def test_denial_if_hermes_identity_context_changes(self):
        self.tenant='tenant2'
        status,body,_=self.request('/api/surface?view=companies&surface_id=ok',self.token)
        self.assertEqual(status,403)
        self.assertEqual(json.loads(body),{'ok':False})

    def test_post_and_options_not_available(self):
        self.assertEqual(self.request('/api/surface',self.token,method='POST')[0],405)
        self.assertEqual(self.request('/api/surface',self.token,method='OPTIONS')[0],405)

    def test_static_viewer_only_and_no_query_secrets(self):
        status,body,_=self.request('/')
        self.assertEqual(status,200)
        self.assertIn('Hermes Unlimited',body)
        self.assertEqual(self.request('/?token=leak')[0],404)
        self.assertEqual(self.request('/../../unlimited/runtime.py')[0],404)

    def test_rejects_external_host_and_weak_token(self):
        with self.assertRaises(ValueError): make_bridge(lambda x:x, token='short')
        with self.assertRaises(ValueError): make_bridge(lambda x:x,token=self.token,host='0.0.0.0')


if __name__=='__main__':unittest.main()
