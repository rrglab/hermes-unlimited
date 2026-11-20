"""Actual Chromium smoke for the restricted A2UI v1.0 browser viewer.

Optional when Playwright/Chromium are absent. No real customer data is used.
"""
import functools
import http.server
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from unlimited.a2ui_adapter import company_surface, request_surface
from unlimited.runtime import ProviderStore

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]


class A2UIBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None or not shutil.which('chromium'):
            raise unittest.SkipTest('Playwright and Chromium required for browser smoke')
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/web/a2ui/'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProviderStore(Path(self.tmp.name) / 'db.sqlite', lambda p,t,i: p=='provider1' and t=='tenant1' and i=='valid')
        self.store.create_company('provider1', 'tenant1', 'acme', 'Synthetic company', 'valid')
        self.store.publish_service('provider1', 'tenant1', 'acme', 'review', 'Review', 0, 'NOK', 'valid')
        self.store.request_service('provider1', 'tenant1', 'acme', 'request1', 'review', {'secret':'NOT_FOR_UI'}, 'valid')
        self.page = self.browser.new_page()
        self.page.goto(self.url)

    def tearDown(self):
        self.page.close()
        self.tmp.cleanup()

    def show(self, message):
        self.page.locator('#payload').fill(json.dumps(message))
        self.page.get_by_role('button', name='Render surface').click()

    def test_company_native_tool_envelope_renders_in_real_browser(self):
        msg = company_surface(self.store,'provider1','tenant1','valid',surface_id='companies1')
        self.show(msg)
        self.assertEqual(self.page.locator('#surface h2').inner_text(), 'Hermes Unlimited · Companies')
        self.assertIn('Synthetic company', self.page.locator('#surface').inner_text())
        self.assertEqual(self.page.locator('[data-a2ui-surface-id="companies1"]').count(), 1)

    def test_request_native_tool_envelope_does_not_leak_payload(self):
        msg = request_surface(self.store,'provider1','tenant1','acme','valid',surface_id='requests1')
        self.show(msg)
        self.assertIn('request1 · review · queued', self.page.locator('#surface').inner_text())
        self.assertNotIn('NOT_FOR_UI', self.page.locator('#surface').inner_text())

    def test_malicious_html_is_plain_text_and_rejected_actions_do_not_mutate(self):
        msg = company_surface(self.store,'provider1','tenant1','valid',surface_id='safe')
        msg['createSurface']['components'][2]['text'] = '<img src=x onerror=alert(1)> & safe'
        self.show(msg)
        self.assertEqual(self.page.locator('#surface img').count(), 0)
        self.assertIn('<img src=x', self.page.locator('#surface').inner_text())
        msg['createSurface']['components'][2]['action'] = {'event':{'name':'deleteCompany'}}
        self.show(msg)
        self.assertIn('Rejected A2UI message', self.page.locator('#message').inner_text())
        self.assertEqual(self.page.locator('#surface img').count(), 0)
        self.assertEqual(self.page.locator('#surface').inner_text(), '')

    def test_cyclic_components_rejected_before_any_dom_change(self):
        msg = company_surface(self.store,'provider1','tenant1','valid',surface_id='safe')
        self.show(msg)
        msg['createSurface']['components'][0]['children'].append('root')
        self.show(msg)
        self.assertIn('CYCLIC_COMPONENTS', self.page.locator('#message').inner_text())
        self.assertEqual(self.page.locator('#surface').inner_text(), '')

    def test_rejects_oversized_pasted_input(self):
        self.page.locator('#payload').fill('x' * 70000)
        self.page.get_by_role('button', name='Render surface').click()
        self.assertIn('MESSAGE_TOO_LARGE', self.page.locator('#message').inner_text())


if __name__ == '__main__':
    unittest.main()
