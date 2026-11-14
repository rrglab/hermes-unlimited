"""Consent-gated Hermes lifecycle observer.

Correlates events by (session_id, turn_id). Neither identifier, nor any tool
input, tool result, prompt, response, or customer reference is persisted.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading
from typing import Any

from .feedback import DEFAULT_HOME, consent_valid, record

MAX_PENDING_TURNS = 2048


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


def _key(kwargs: dict[str, Any]) -> tuple[str, str] | None:
    session = kwargs.get("session_id")
    turn = kwargs.get("turn_id")
    if (not isinstance(session, str) or not isinstance(turn, str)
            or not session or not turn or len(session) > 256 or len(turn) > 256):
        return None
    return session, turn


class FeedbackObserver:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DEFAULT_HOME
        self._lock = threading.RLock()
        self._pending: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def _active(self) -> bool:
        return consent_valid(self.data_dir)

    def _get(self, key: tuple[str, str]) -> dict[str, Any]:
        row = self._pending.get(key)
        if row is None:
            if len(self._pending) >= MAX_PENDING_TURNS:
                self._pending.popitem(last=False)
            row = {"family": "general", "in": 0, "out": 0, "ms": 0,
                   "calls": set(), "models": set()}
            self._pending[key] = row
        return row

    def post_api_request(self, **kwargs: Any) -> None:
        if not self._active():
            return
        key = _key(kwargs)
        if key is None:
            return
        usage = kwargs.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        request_id = kwargs.get("api_request_id")
        model = kwargs.get("model")
        duration = kwargs.get("api_duration")
        with self._lock:
            row = self._get(key)
            if isinstance(request_id, str) and request_id:
                if request_id in row["calls"]:
                    return
                row["calls"].add(request_id)
            if isinstance(model, str) and model:
                row["models"].add(model)
            row["in"] = min(100_000_000, row["in"] + token(usage.get("input_tokens")))
            row["out"] = min(100_000_000, row["out"] + token(usage.get("output_tokens")))
            if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                    and 0 <= duration <= 86_400):
                row["ms"] = min(86_400_000, row["ms"] + round(duration * 1000))

    def post_tool_call(self, **kwargs: Any) -> None:
        if not self._active():
            return
        key = _key(kwargs)
        name = kwargs.get("tool_name")
        if key is None or not isinstance(name, str):
            return
        category = family(name)
        if category == "general":
            return
        with self._lock:
            self._get(key)["family"] = category

    def on_session_end(self, **kwargs: Any) -> None:
        key = _key(kwargs)
        if key is None:
            return
        with self._lock:
            row = self._pending.pop(key, None)
        if not self._active() or row is None:
            return
        model = kwargs.get("model")
        if not isinstance(model, str) or not model:
            return
        if row["models"] and row["models"] != {model}:
            # Fail closed on mid-turn model changes/fallbacks. A single model
            # cannot be credited with a mixed-model outcome.
            return
        try:
            record(self.data_dir, {
                "task_family": row["family"], "model": model,
                "completed": kwargs.get("completed") is True and kwargs.get("failed") is False,
                "verified": False, "success": False,
                "latency_ms": row["ms"], "cost_usd": None,
                "input_tokens": row["in"], "output_tokens": row["out"],
            })
        except (ValueError, TypeError, OSError):
            return


def register_feedback_hooks(ctx: Any, data_dir: Path | None = None) -> FeedbackObserver:
    observer = FeedbackObserver(data_dir)
    ctx.register_hook("post_api_request", observer.post_api_request)
    ctx.register_hook("post_tool_call", observer.post_tool_call)
    ctx.register_hook("on_session_end", observer.on_session_end)
    return observer
