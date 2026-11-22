"""Runtime behavior checks for a pinned upstream Hermes hosted-room fast path.

Run with HERMES_AGENT_SOURCE pointing at the patched checkout.
No network, production files, services or credentials are accessed.
"""
import ast
import asyncio
import contextlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def load_function(source: Path, owner_scope, service_type):
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    target = next(
        obj for obj in module.body
        if isinstance(obj, ast.AsyncFunctionDef) and obj.name == "_ensure_hosted_service"
    )
    local = {
        "asyncio": asyncio,
        "Path": Path,
        "owner_scope": owner_scope,
        "CanonicalHostedRoomService": service_type,
    }
    code = compile(ast.fix_missing_locations(ast.Module(body=[target], type_ignores=[])),
                   str(source), "exec")
    exec(code, local)
    return local["_ensure_hosted_service"]


def modules_for_install(calls):
    gateway = types.ModuleType("gateway")
    gateway.__path__ = []
    transport = types.ModuleType("gateway.session_hosted_transport")
    def install(*args, **kwargs):
        calls.append(("transport", len(args), set(kwargs)))
    transport.install_hosted_transport = install
    imports = types.ModuleType("gateway.hosted_rooms_gateway_import")
    def import_standalone_rooms(*args, **kwargs):
        calls.append(("room_import", len(args), set(kwargs)))
    imports.import_standalone_rooms = import_standalone_rooms
    return {
        "gateway": gateway,
        "gateway.session_hosted_transport": transport,
        "gateway.hosted_rooms_gateway_import": imports,
    }


class HostedFastPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(os.environ["HERMES_AGENT_SOURCE"]).resolve()
        self.source = root / "gateway" / "session_hosted_service.py"
        self.assertTrue(self.source.is_file())
        self.calls = []
        @contextlib.contextmanager
        def scope(authority):
            self.calls.append(("scope", id(authority)))
            yield
        self.scope = scope

        class Service:
            def __init__(self, authority, loop):
                self._transport_installed = False
                self.attest = object()
                self.authority = authority
        self.Service = Service
        self.fn = load_function(self.source, scope, Service)
        self.runner = types.SimpleNamespace(session_control_server=object())
        self.modules = modules_for_install(self.calls)

    async def test_ready_service_avoids_scope_and_effects(self):
        service = types.SimpleNamespace(_transport_installed=True)
        authority = types.SimpleNamespace(hosted_room_service=service)
        with patch.dict(sys.modules, self.modules):
            await self.fn(self.runner, authority)
        self.assertEqual(self.calls, [])
        self.assertIs(authority.hosted_room_service, service)

    async def test_uninstalled_transport_still_uses_owner_scope(self):
        service = types.SimpleNamespace(_transport_installed=False, attest=object())
        authority = types.SimpleNamespace(hosted_room_service=service)
        with patch.dict(sys.modules, self.modules):
            await self.fn(self.runner, authority)
        self.assertTrue(service._transport_installed)
        self.assertEqual([kind for kind,*_ in self.calls], ["scope", "transport"])

    async def test_missing_service_still_uses_owner_scope_and_installs(self):
        authority = types.SimpleNamespace(hosted_room_service=None,
                                          db=types.SimpleNamespace(db_path="/virtual/room.db"),
                                          epoch=7)
        with patch.dict(sys.modules, self.modules):
            await self.fn(self.runner, authority)
        self.assertIsInstance(authority.hosted_room_service, self.Service)
        self.assertTrue(authority.hosted_room_service._transport_installed)
        self.assertEqual([kind for kind,*_ in self.calls],
                         ["scope", "room_import", "transport"])


if __name__ == "__main__":
    unittest.main()
