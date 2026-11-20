"""Real Chromium browser fetch through authenticated loopback A2UI bridge."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from unlimited.a2ui_adapter import company_surface, request_surface
from unlimited.a2ui_bridge import make_bridge, new_transport_token
from unlimited.runtime import ProviderStore

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class BrowserBridgeAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None or not shutil.which('chromium'):
            raise unittest.SkipTest('Chromium and Playwright required')
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ProviderStore(Path(self.tmp.name)/'db',lambda p,t,i:p=='provider1' and t=='tenant1' and i=='ok')
        self.store.create_company('provider1','tenant1','acme','Live synthetic company','ok')
        self.store.publish_service('provider1','tenant1','acme','review','Review',0,'NOK','ok')
        self.store.request_service('provider1','tenant1','acme','req1','review',{'secret':'SECRET_PAYLOAD'},'ok')
        self.allowed=True
        def native(args):
            if not self.allowed:return json.dumps({'ok':False})
            if args['view']=='companies': msg=company_surface(self.store,'provider1','tenant1','ok',surface_id=args['surface_id'])
            else:msg=request_surface(self.store,'provider1','tenant1',args['company_id'],'ok',surface_id=args['surface_id'])
            return json.dumps(msg)
        self.token=new_transport_token()
        self.server=make_bridge(native,token=self.token)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.page=self.browser.new_page()
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/')

    def tearDown(self):
        self.page.close();self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.tmp.cleanup()

    def test_authentication_and_tenant_recheck(self):
        self.page.get_by_role('button',name='Load companies').click()
        self.page.locator('#message').get_by_text('Bridge rejected: TOKEN_REQUIRED').wait_for(timeout=5000)
        self.assertEqual(self.page.locator('#surface').inner_text(),'')
        self.page.locator('#bearer').fill('x'*40)
        self.page.get_by_role('button',name='Load companies').click()
        self.page.locator('#message').get_by_text('Bridge rejected: ACCESS_DENIED_OR_UNAVAILABLE').wait_for(timeout=5000)
        self.page.locator('#bearer').fill(self.token)
        self.page.get_by_role('button',name='Load companies').click()
        self.page.get_by_text('Live synthetic company').wait_for(timeout=5000)
        self.allowed=False
        self.page.get_by_role('button',name='Load companies').click()
        self.page.locator('#message').get_by_text('Bridge rejected: ACCESS_DENIED_OR_UNAVAILABLE').wait_for(timeout=5000)
        self.assertEqual(self.page.locator('#surface').inner_text(),'')

    def test_requests_render_without_private_payload(self):
        self.page.locator('#bearer').fill(self.token)
        self.page.locator('#company').fill('acme')
        self.page.get_by_role('button',name='Load requests').click()
        self.page.get_by_text('req1 · review · queued').wait_for(timeout=5000)
        self.assertNotIn('SECRET_PAYLOAD',self.page.locator('#surface').inner_text())


if __name__=='__main__':unittest.main()
