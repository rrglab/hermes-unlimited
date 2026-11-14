import json
import time
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from unlimited.webhook_delivery import (
    WebhookDeliveryError, WebhookDestination, post_chat_message, send_with_trusted_host,
)


class Receiver(BaseHTTPRequestHandler):
    received = []
    status_code = 200
    redirected_requests = []
    body_delay_seconds = 0

    def do_GET(self):
        self.redirected_requests.append(("GET", self.path))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"redirected")

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.received.append((self.path, json.loads(data)))
        if self.path == "/redirected":
            self.redirected_requests.append(("POST", self.path))
        self.send_response(self.status_code)
        if self.status_code == 302:
            self.send_header("Location", "/redirected")
        self.end_headers()
        if self.body_delay_seconds:
            time.sleep(self.body_delay_seconds)
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class WebhookDeliveryTests(unittest.TestCase):
    def setUp(self):
        Receiver.received = []
        Receiver.status_code = 200
        Receiver.redirected_requests = []
        Receiver.body_delay_seconds = 0
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.dest = WebhookDestination(
            f"http://127.0.0.1:{self.http.server_port}/rooms/one/key/slack", True)

    def tearDown(self):
        self.http.shutdown()
        self.thread.join(timeout=2)
        self.http.server_close()

    def test_real_http_post_to_local_slack_compatible_endpoint(self):
        result = post_chat_message(self.dest, "Agent says hello")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["delivery_verified"])
        self.assertEqual(Receiver.received, [(
            "/rooms/one/key/slack", {"text": "Agent says hello"})])

    def test_upstream_rejection_is_not_success(self):
        Receiver.status_code = 403
        with self.assertRaises(WebhookDeliveryError):
            post_chat_message(self.dest, "Try this")
        self.assertEqual(len(Receiver.received), 1)

    def test_upstream_redirect_not_followed(self):
        Receiver.status_code = 302
        with self.assertRaises(WebhookDeliveryError):
            post_chat_message(self.dest, "Don't forward")
        self.assertEqual(len(Receiver.received), 1)
        self.assertEqual(Receiver.redirected_requests, [])

    def test_upstream_2xx_does_not_wait_for_unused_response_body(self):
        Receiver.body_delay_seconds = 2
        start = time.monotonic()
        result = post_chat_message(self.dest, "Do not wait", timeout=1)
        self.assertTrue(result["accepted"])
        self.assertLess(time.monotonic() - start, 1.8)

    def test_no_retry_on_server_failure(self):
        Receiver.status_code = 503
        with self.assertRaises(WebhookDeliveryError):
            post_chat_message(self.dest, "Once only")
        self.assertEqual(len(Receiver.received), 1)

    def test_reject_user_supplied_insecure_or_internal_urls(self):
        for url in ("http://example.com/x", "https://user:password@example.com/h",
                    "https://example.com/h#fragment", "https://example.com/h?secret=abc",
                    "ftp://example.com/file"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                WebhookDestination(url)
        with self.assertRaises(PermissionError):
            send_with_trusted_host(
                tenant="a", identity="@a", adapter_id="ember", connection_id="c",
                text="Hi", registry=Mock(),
                approve_effect=lambda *_: True,
                resolve_destination=lambda *_: self.dest)

    def test_failed_tenant_grant_blocks_network_effect(self):
        registry = Mock()
        registry.authorize_tenant_capability.side_effect = PermissionError("DENIED")
        with self.assertRaises(PermissionError):
            send_with_trusted_host(
                tenant="tenant-a", identity="@owner", adapter_id="ember",
                connection_id="chat", text="no", registry=registry,
                approve_effect=lambda *_: True,
                resolve_destination=lambda *_: WebhookDestination("https://example.com/h"))
        self.assertFalse(Receiver.received)

    def test_denied_host_effect_blocks_before_destination_resolution(self):
        registry = Mock()
        resolver = Mock()
        with self.assertRaises(PermissionError):
            send_with_trusted_host(
                tenant="tenant-a", identity="@owner", adapter_id="slack",
                connection_id="chat", text="no", registry=registry,
                approve_effect=lambda *_: False, resolve_destination=resolver)
        resolver.assert_not_called()

    def test_input_validation(self):
        for text in ("", "x" * 4097, None):
            with self.subTest(text=str(text)[:5]), self.assertRaises(ValueError):
                post_chat_message(self.dest, text)
        with self.assertRaises(ValueError):
            post_chat_message(self.dest, "OK", timeout=99)
