"""Hermes-native Socratic councillors: actual calls with injected subprocess runner."""
import asyncio
import json
from subprocess import CompletedProcess

import pytest

from unlimited.council_hermes import CouncilUnavailable, _invoke, configure_council, parse_seats, ROLES
from unlimited.socratic_council import QUESTIONS, SocraticCouncil

SEATS = {role: {"provider": "test-provider", "model": "test/model-" + role} for role in ROLES}


def test_five_seats_required_and_no_secrets_in_config():
    assert set(parse_seats(json.dumps(SEATS))) == set(ROLES)
    with pytest.raises(CouncilUnavailable):
        parse_seats(json.dumps({k: v for k, v in SEATS.items() if k != "chair"}))
    bad = dict(SEATS)
    bad["chair"] = {"provider": "test-provider", "model": "x", "api_key": "leak"}
    with pytest.raises(CouncilUnavailable):
        parse_seats(json.dumps(bad))


def test_hermes_call_is_safe_bounded_and_without_shell():
    seen = []
    def fake_runner(args, **kwargs):
        seen.append((args, kwargs))
        return CompletedProcess(args, 0, "Factual analysis", "")
    result = _invoke("hermes", SEATS["skeptic"], "Strict review", "case text",
                     runner=fake_runner)
    assert result == "Factual analysis"
    args, options = seen[0]
    assert args[:3] == ["hermes", "chat", "--query-file"]
    assert args[3] == "-"
    assert options["input"].endswith("case text")
    assert options["timeout"] <= 100
    assert "--toolsets" in args and args[args.index("--toolsets") + 1] == ""
    assert not any("case text" in arg for arg in args)
    assert options["check"] is False


def test_fails_closed_on_unavailable_model():
    def fail(args, **kwargs):
        return CompletedProcess(args, 1, "", "private provider errors")
    with pytest.raises(CouncilUnavailable, match="COUNCIL_MODEL_UNAVAILABLE"):
        _invoke("hermes", SEATS["chair"], "chair", "case", runner=fail)


def test_unconfigured_council_never_fabricates():
    class Ctx:
        def get_config(self, key, default=""):
            return default
    assert configure_council(Ctx(), lambda k, d="": d) is None


@pytest.mark.asyncio
async def test_real_pipeline_calls_all_five_seats_with_two_blind_rounds():
    seen = []
    def fake_runner(args, **kwargs):
        model = args[args.index("--model") + 1]
        prompt = kwargs["input"]
        seen.append((model, prompt))
        if model.endswith("chair"):
            return CompletedProcess(args, 0, json.dumps({
                "status": "DISSENT", "synthesis": "Evidence insufficient for unconditional go",
                "dissent": ["Unknown effect size"], "uncertainty": ["Missing base rates"]
            }), "")
        return CompletedProcess(args, 0, "Model evaluation of the stated evidence", "")

    class Ctx: pass
    callables = configure_council(
        Ctx(), lambda name, default="": json.dumps(SEATS) if name.endswith("COUNCIL_MODELS") else default,
        runner=fake_runner)
    assert callables is not None
    members, chair = callables
    record = await SocraticCouncil(members, chair).run(
        "Should the company launch?", {k: "Current evidence is incomplete" for k, _ in QUESTIONS})
    assert len(seen) == 9  # four independent + four blind critiques + chair
    assert len(set(model for model, _ in seen)) == 5
    assert record.status == "DISSENT"
    assert record.execution_authority is False
    assert "candidate-1" not in seen[0][1]
    assert "candidate-1" in seen[4][1]
