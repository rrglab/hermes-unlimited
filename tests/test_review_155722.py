"""Regression tests for NousResearch catalog review #155722."""
import sys
import types
from pathlib import Path
from unittest.mock import patch

from unlimited.tools import _default_council_callables, _host_capability_ready, register_company_tools
from feedback_task_model.feedback import _default_home


class DummyContext:
    def __init__(self):
        self.tools = {}
        self.profile_name = "test"

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs


def test_unavailable_host_operations_are_hidden():
    ctx = DummyContext()
    register_company_tools(ctx, lambda *_: "", lambda: ("tenant", {}))
    for name in (
        "unlimited_mission_run", "unlimited_company_cycle",
        "unlimited_service_factory", "unlimited_connection_manage",
    ):
        assert ctx.tools[name]["check_fn"]() is False
    assert ctx.tools["unlimited_company_list"]["check_fn"]() is True


def test_partial_host_seams_do_not_expose_tools():
    ctx = DummyContext()
    ctx.authorize_mission = lambda *_: True
    ctx.mission_worker = lambda *_: {}
    ctx.approve_customer_connection = lambda *_: True
    assert not _host_capability_ready(ctx, "unlimited_mission_run")
    assert not _host_capability_ready(ctx, "unlimited_connection_manage")


def test_council_never_fabricates_review():
    ctx = DummyContext()
    assert _default_council_callables(ctx) is None
    ctx.socratic_council_members = {"explorer": lambda *_: ""}
    ctx.socratic_council_chair = lambda *_: ""
    assert _default_council_callables(ctx) is None


def test_feedback_home_follows_active_profile():
    fake_constants = types.SimpleNamespace(get_hermes_home=lambda: "/tmp/hermes-profile-isolated")
    with patch.dict(sys.modules, {"hermes_constants": fake_constants}):
        assert _default_home() == Path("/tmp/hermes-profile-isolated/feedback_task_model")
