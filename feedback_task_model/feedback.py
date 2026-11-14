"""Opt-in, no-LLM community feedback collector and publisher.

No prompt bodies, file contents, identities or credentials are accepted in
records. Submission requires an explicit, unexpired local consent record.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

TARGET = "rrglab/hermes-unlimited"
SCHEMA_VERSION = 1
FAMILIES = frozenset({"file_lookup", "email_read", "email_draft", "dns_lookup",
                      "code_review", "test_execution", "general", "other"})
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,95}$")
ALLOWED = frozenset({"task_family", "model", "verified", "success",
                     "latency_ms", "cost_usd", "input_tokens", "output_tokens", "completed"})
DEFAULT_HOME = Path.home() / ".hermes" / "feedback_task_model"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value: str) -> datetime:
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_HAVE_TIMEZONE")
    return date.astimezone(timezone.utc)


def validate_trial(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != ALLOWED:
        raise ValueError("ONLY_EIGHT_ALLOWLISTED_FIELDS_ACCEPTED")
    family, model = raw["task_family"], raw["model"]
    if family not in FAMILIES or not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        raise ValueError("INVALID_TASK_FAMILY_OR_MODEL")
    if type(raw["verified"]) is not bool or type(raw["success"]) is not bool:
        raise ValueError("BOOLEAN_REQUIRED")
    if type(raw["completed"]) is not bool:
        raise ValueError("COMPLETION_BOOLEAN_REQUIRED")
    if raw["success"] and (not raw["verified"] or not raw["completed"]):
        raise ValueError("SUCCESS_REQUIRES_VERIFIED_COMPLETED_RESULT")
    import math
    if not isinstance(raw["latency_ms"], (int, float)) or isinstance(raw["latency_ms"], bool) or not math.isfinite(raw["latency_ms"]) or raw["latency_ms"] < 0:
        raise ValueError("INVALID_NONNEGATIVE_MEASUREMENT")
    if raw["cost_usd"] is not None and (not isinstance(raw["cost_usd"], (int, float)) or isinstance(raw["cost_usd"], bool) or not math.isfinite(raw["cost_usd"]) or raw["cost_usd"] < 0):
        raise ValueError("INVALID_NONNEGATIVE_COST")
    for key in ("input_tokens", "output_tokens"):
        if type(raw[key]) is not int or raw[key] < 0:
            raise ValueError("INVALID_TOKEN_COUNT")
    if raw["latency_ms"] > 86_400_000 or (raw["cost_usd"] is not None and raw["cost_usd"] > 100000) or raw["input_tokens"] > 100000000 or raw["output_tokens"] > 100000000:
        raise ValueError("MEASUREMENT_OUT_OF_RANGE")
    return dict(raw)


def record(data_dir: Path, trial: dict[str, Any], *, now: datetime | None = None) -> None:
    trial = validate_trial(trial)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "events.jsonl"
    # Only validated fields written; no prompt, tenant or filename metadata.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": _stamp(now or utcnow()), **trial}, sort_keys=True) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_consent(data_dir: Path, *, agree: bool, days: int = 30, now: datetime | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "consent.json"
    if not agree:
        path.unlink(missing_ok=True)
        return
    if not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("CONSENT_DURATION_INVALID")
    now = now or utcnow()
    consent = {"schema_version": SCHEMA_VERSION, "enabled": True, "target": TARGET,
               "consented_at": _stamp(now), "expires_at": _stamp(now + timedelta(days=days)),
               "aggregate_only": True}
    path.write_text(json.dumps(consent, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def consent_valid(data_dir: Path, *, now: datetime | None = None) -> bool:
    try:
        c = json.loads((data_dir / "consent.json").read_text(encoding="utf-8"))
        return (c.get("schema_version") == SCHEMA_VERSION and c.get("enabled") is True
                and c.get("target") == TARGET and c.get("aggregate_only") is True
                and _date(c["consented_at"]) <= (now or utcnow()) < _date(c["expires_at"]))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def build_batch(data_dir: Path, *, start: datetime, end: datetime, min_group: int = 3) -> dict[str, Any]:
    if not 3 <= min_group <= 100 or not start < end or end - start > timedelta(hours=13):
        raise ValueError("INVALID_AGGREGATION_WINDOW")
    path = data_dir / "events.jsonl"
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                moment = _date(raw.pop("timestamp"))
                event = validate_trial(raw)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if start <= moment < end:
                buckets[event["task_family"], event["model"]].append(event)
    result = []
    for (family, model), rows in sorted(buckets.items()):
        if len(rows) < min_group:
            continue
        verified = [r for r in rows if r["verified"]]
        result.append({"task_family": family, "model": model, "samples": len(rows),
                       "completed_samples": sum(r["completed"] for r in rows),
                       "verified_samples": len(verified), "verified_successes": sum(r["success"] for r in verified),
                       "mean_latency_ms": round(sum(r["latency_ms"] for r in rows) / len(rows)),
                       "mean_cost_usd_estimate": (round(sum(r["cost_usd"] for r in rows) / len(rows), 6)
                                                  if all(r["cost_usd"] is not None for r in rows) else None),
                       "total_input_tokens": sum(r["input_tokens"] for r in rows),
                       "total_output_tokens": sum(r["output_tokens"] for r in rows)})
    return {"schema_version": SCHEMA_VERSION, "window_start": _stamp(start),
            "window_end": _stamp(end), "aggregation_minimum": min_group,
            "groups": result, "suppressed_groups": sum(len(rows) < min_group for rows in buckets.values()),
            "evidence": "SELF_REPORTED_UNVERIFIED"}


def _slot(now: datetime) -> tuple[datetime, datetime]:
    at = now.astimezone(timezone.utc)
    hour = 12 if at.hour >= 12 else 0
    end = at.replace(hour=hour, minute=0, second=0, microsecond=0)
    return end - timedelta(hours=12), end


def preview(data_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
    start, end = _slot(now or utcnow())
    return build_batch(data_dir, start=start, end=end)


def publish(data_dir: Path, *, now: datetime | None = None,
            runner=subprocess.run) -> str:
    now = now or utcnow()
    if not consent_valid(data_dir, now=now):
        return "NOT_SENT_NO_VALID_CONSENT"
    batch = preview(data_dir, now=now)
    if not batch["groups"]:
        return "NOT_SENT_NO_ELIGIBLE_AGGREGATES"
    slot_id = batch["window_end"].replace(":", "-")
    receipt = data_dir / "receipts" / (slot_id + ".json")
    if receipt.exists():
        return "NOT_SENT_ALREADY_RECORDED"
    # The repo must explicitly provide a public Issues inbox. Never fall back
    # to creating PRs, arbitrary repository writes or uploading raw event logs.
    check = runner(["gh", "api", "repos/" + TARGET, "--jq", ".has_issues"],
                   capture_output=True, text=True, timeout=20, check=False)
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "NOT_SENT_TARGET_ISSUES_DISABLED"
    body = ("Voluntary, aggregate-only Hermes Unlimited task/model feedback.\n"
            "No task contents, prompts, identities, source paths, credentials, or raw traces.\n"
            "Numbers are contributed observations, NOT independently verified benchmarks.\n\n"
            "```json\n" + json.dumps(batch, sort_keys=True, indent=2) + "\n```\n")
    title = "Task/model feedback aggregate " + batch["window_end"]
    # --body-file avoids shell interpolation of submitted content.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        body_path = Path(tmp) / "body.md"
        body_path.write_text(body, encoding="utf-8")
        result = runner(["gh", "issue", "create", "--repo", TARGET, "--title", title,
                         "--body-file", str(body_path)], capture_output=True, text=True,
                        timeout=30, check=False)
    if result.returncode != 0 or not result.stdout.strip().startswith("https://github.com/" + TARGET + "/issues/"):
        return "NOT_SENT_PUBLISH_FAILED"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"target": TARGET, "slot": slot_id,
                                   "issue_url": result.stdout.strip()}) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    return "SENT_AGGREGATES " + result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in aggregate-only Hermes community feedback")
    parser.add_argument("command", choices=("record", "preview", "publish", "consent", "revoke", "status"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("HERMES_FEEDBACK_HOME", DEFAULT_HOME)))
    parser.add_argument("--agree", action="store_true", help="Explicitly permit public aggregate submissions")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            record(args.data_dir, json.load(sys.stdin))
            print("RECORDED_LOCAL_ONLY")
        elif args.command == "consent":
            if not args.agree:
                parser.error("Consent requires explicit --agree")
            set_consent(args.data_dir, agree=True, days=args.days)
            print("CONSENT_GRANTED_FOR_AGGREGATES_ONLY")
        elif args.command == "revoke":
            set_consent(args.data_dir, agree=False)
            print("CONSENT_REVOKED")
        elif args.command == "status":
            print(json.dumps({"consent_active": consent_valid(args.data_dir), "target": TARGET}))
        elif args.command == "preview":
            print(json.dumps(preview(args.data_dir), indent=2))
        else:
            print(publish(args.data_dir))
        return 0
    except (ValueError, OSError, TypeError) as error:
        print("FAILED " + type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
