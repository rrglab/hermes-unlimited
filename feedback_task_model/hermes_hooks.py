"""Consent-gated Hermes lifecycle observer; never stores tool arguments or results."""
from __future__ import annotations
from pathlib import Path
import threading
from typing import Any
from .feedback import DEFAULT_HOME, consent_valid, record


def family(tool_name: str) -> str:
    name = tool_name.lower()
    if name in ("read_file", "search_files"):
        return "file_lookup"
    if name.startswith(("gmail_", "outlook_", "email_")):
        return "email_draft" if any(x in name for x in ("draft", "compose", "send")) else "email_read"
    if "dns" in name:
        return "dns_lookup"
    if "test" in name or "verify" in name:
        return "test_execution"
    if "review" in name or "diff" in name:
        return "code_review"
    return "general"


def token(value: Any) -> int:
    return min(value, 100_000_000) if type(value) is int and value >= 0 else 0


class FeedbackObserver:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DEFAULT_HOME
        self._lock = threading.RLock()
        self._pending: dict[str, dict] = {}

    def _active(self) -> bool:
        return consent_valid(self.data_dir)

    def post_api_request(self, **kwargs: Any):
        if not self._active():
            return
        sid = kwargs.get("session_id")
        if not isinstance(sid, str) or not sid:
            return
        usage = kwargs.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        duration = kwargs.get("api_duration")
        with self._lock:
            state = self._pending.setdefault(sid, {"family": "general", "in": 0, "out": 0, "ms": 0})
            state["in"] += token(usage.get("input_tokens"))
            state["out"] += token(usage.get("output_tokens"))
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 <= duration <= 86400:
                state["ms"] += round(duration * 1000)

    def post_tool_call(self, **kwargs: Any):
        if not self._active():
            return
        sid, name = kwargs.get("session_id"), kwargs.get("tool_name")
        if not isinstance(sid, str) or not sid or not isinstance(name, str):
            return
        category = family(name)
        if category == "general":
            return
        with self._lock:
            self._pending.setdefault(sid, {"family": "general", "in": 0, "out": 0, "ms": 0})["family"] = category

    def on_session_end(self, **kwargs: Any):
        sid = kwargs.get("session_id")
        if not isinstance(sid, str) or not sid:
            return
        with self._lock:
            state = self._pending.pop(sid, None)
        if not self._active() or state is None:
            return
        model = kwargs.get("model")
        if not isinstance(model, str):
            return
        try:
            record(self.data_dir, {
                "task_family": state["family"], "model": model,
                "completed": kwargs.get("completed") is True and kwargs.get("failed") is False,
                "verified": False, "success": False,
                "latency_ms": min(state["ms"], 86_400_000),
                "cost_usd": None,
                "input_tokens": min(state["in"], 100_000_000),
                "output_tokens": min(state["out"], 100_000_000),
            })
        except (ValueError, TypeError, OSError):
            pass


def register_feedback_hooks(ctx: Any, data_dir: Path | None = None) -> FeedbackObserver:
    observer = FeedbackObserver(data_dir)
    ctx.register_hook("post_api_request", observer.post_api_request)
    ctx.register_hook("post_tool_call", observer.post_tool_call)
    ctx.register_hook("on_session_end", observer.on_session_end)
    return observer
