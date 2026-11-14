"""Hermes-native Socratic councillors: actual calls with injected subprocess runner."""
import asyncio
import json
from subprocess import CompletedProcess
import unittest

from unlimited.council_hermes import CouncilUnavailable, _invoke, configure_council, parse_seats, ROLES
from unlimited.socratic_council import QUESTIONS, SocraticCouncil

SEATS = {role: {"provider": "test-provider", "model": "test/model-" + role} for role in ROLES}


class HermesCouncilTests(unittest.TestCase):
    def test_five_seats_required_and_no_secrets_in_config(self):
        self.assertEqual(set(parse_seats(json.dumps(SEATS))), set(ROLES))
        with self.assertRaises(CouncilUnavailable):
            parse_seats(json.dumps({k: v for k, v in SEATS.items() if k != "chair"}))
        bad = dict(SEATS)
        bad["chair"] = {"provider": "test-provider", "model": "x", "api_key": "leak"}
        with self.assertRaises(CouncilUnavailable):
            parse_seats(json.dumps(bad))

    def test_hermes_call_is_safe_bounded_and_without_shell(self):
        seen = []
        def fake_runner(args, **kwargs):
            seen.append((args, kwargs))
            return CompletedProcess(args, 0, "Factual analysis", "")
        result = _invoke("hermes", SEATS["skeptic"], "Strict review", "case text",
                         runner=fake_runner)
        self.assertEqual(result, "Factual analysis")
        args, options = seen[0]
        self.assertEqual(args[:3], ["hermes", "chat", "--query-file"])
        self.assertEqual(args[3], "-")
        self.assertTrue(options["input"].endswith("case text"))
        self.assertLessEqual(options["timeout"], 100)
        self.assertIn("--safe-mode", args)
        self.assertNotIn("--toolsets", args)
        self.assertFalse(any("case text" in arg for arg in args))
        self.assertIs(options["check"], False)

    def test_fails_closed_on_unavailable_model(self):
        def fail(args, **kwargs):
            return CompletedProcess(args, 1, "", "private provider errors")
        with self.assertRaisesRegex(CouncilUnavailable, "COUNCIL_MODEL_UNAVAILABLE"):
            _invoke("hermes", SEATS["chair"], "chair", "case", runner=fail)

    def test_unconfigured_council_never_fabricates(self):
        class Ctx:
            def get_config(self, key, default=""):
                return default
        self.assertIsNone(configure_council(Ctx(), lambda k, d="": d))

    def test_real_pipeline_calls_all_five_seats_with_two_blind_rounds(self):
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
        self.assertIsNotNone(callables)
        members, chair = callables
        record = asyncio.run(SocraticCouncil(members, chair).run(
            "Should the company launch?", {k: "Current evidence is incomplete" for k, _ in QUESTIONS}))
        self.assertEqual(len(seen), 9)
        self.assertEqual(len(set(model for model, _ in seen)), 5)
        self.assertEqual(record.status, "DISSENT")
        self.assertIs(record.execution_authority, False)
        self.assertNotIn("candidate-1", seen[0][1])
        self.assertIn("candidate-1", seen[4][1])


if __name__ == "__main__":
    unittest.main()
