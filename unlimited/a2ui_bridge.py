"""Opt-in authenticated loopback HTTP transport for native Hermes A2UI surfaces.

This is not an identity provider. The injected native_tool is the already
registered, JustYou-bound ``unlimited_a2ui_surface`` handler. The native tool
re-evaluates host scope on every request. Browser authorization is independent:
operators supply an unlogged, unpredictable token out of band.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .a2ui_adapter import validate_envelope

_ROOT = Path(__file__).resolve().parents[1] / 'web' / 'a2ui'
_ID = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
_COMPANY = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
_FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/app.mjs': ('app.mjs', 'text/javascript; charset=utf-8'),
          '/renderer.mjs': ('renderer.mjs', 'text/javascript; charset=utf-8')}


def make_bridge(native_tool, *, token, host='127.0.0.1', port=0):
    """Create a non-public, no-CORS bridge; run serve_forever in host lifecycle.

    Both the native tool and the browser token are required. Neither the token
    nor a JustYou proof is supplied through an A2UI message or URL.
    """
    if not callable(native_tool):
        raise TypeError('TRUSTED_NATIVE_TOOL_REQUIRED')
    if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
        raise ValueError('STRONG_TOKEN_REQUIRED')
    if host != '127.0.0.1':
        raise ValueError('LOOPBACK_ONLY')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # No bearer tokens, query parameters or tenant data in access logs.
            return

        def _respond(self, status, body, mime='application/json; charset=utf-8'):
            payload = body if isinstance(body, bytes) else body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.end_headers()
            self.wfile.write(payload)

        def _error(self, status):
            self._respond(status, b'{"ok":false}')

        def do_GET(self):
            path = urlsplit(self.path)
            # Reject any attempt at path/query-based secret carriage.
            if path.path in _FILES and not path.query:
                name, mime = _FILES[path.path]
                self._respond(200, (_ROOT / name).read_bytes(), mime)
                return
            if path.path != '/api/surface':
                self._error(404)
                return
            origin = self.headers.get('Origin')
            expected_origin = f'http://127.0.0.1:{self.server.server_port}'
            if origin is not None and origin != expected_origin:
                self._error(403)
                return
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self._error(403)
                return
            bearer = self.headers.get('Authorization', '')
            if not hmac.compare_digest(bearer.encode(), ('Bearer ' + token).encode()):
                self._error(401)
                return
            try:
                query = parse_qs(path.query, strict_parsing=True, max_num_fields=4)
            except ValueError:
                self._error(400)
                return
            if any(len(v) != 1 for v in query.values()) or set(query) - {'view', 'company_id', 'surface_id'}:
                self._error(400)
                return
            view = query.get('view', [''])[0]
            surface_id = query.get('surface_id', [''])[0]
            company_id = query.get('company_id', [''])[0]
            if (view not in ('companies', 'requests', 'missions') or not _ID.fullmatch(surface_id)
                or (view == 'companies' and 'company_id' in query)
                or (view in ('requests', 'missions') and not _COMPANY.fullmatch(company_id))):
                self._error(400)
                return
            args = {'view': view, 'surface_id': surface_id}
            if view in ('requests', 'missions'):
                args['company_id'] = company_id
            try:
                result = native_tool(args)
                if not isinstance(result, str) or len(result.encode('utf-8')) > 65536:
                    raise ValueError('INVALID_NATIVE_RESULT')
                parsed = json.loads(result)
                if isinstance(parsed, dict) and parsed.get('ok') is False:
                    self._error(403)
                    return
                validate_envelope(parsed)
                self._respond(200, json.dumps(parsed, ensure_ascii=False))
            except (ValueError, TypeError, PermissionError, KeyError, RuntimeError):
                self._error(403)

        def do_POST(self):
            self._error(405)

        def do_OPTIONS(self):
            self._error(405)

    return ThreadingHTTPServer((host, port), Handler)


def new_transport_token():
    """Generate and deliver out of band; never include in a URL or model output."""
    return secrets.token_urlsafe(32)
