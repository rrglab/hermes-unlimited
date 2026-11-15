"""Offline contract tests: no model keys, network, or external effects."""
import asyncio
import json
import unittest

from unlimited.socratic_council import CouncilError, QUESTIONS, SocraticCouncil


class CouncilTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        async def expert(system, prompt):
            self.calls.append((system, prompt))
            return "Reasoned objection with falsification criteria"
        async def chair(system, prompt):
            self.calls.append((system, prompt))
            return json.dumps({"status": "DISSENT", "synthesis": "Conditional proposal",
                               "dissent": ["Missing causal evidence"],
                               "uncertainty": ["Unknown base rate"]})
        self.council = SocraticCouncil({"explorer": expert, "skeptic": expert}, chair)
        self.answers = {key: "An answer" for key, _ in QUESTIONS}

    async def test_complete_round_preserves_dissent_and_no_authority(self):
        record = await self.council.run("Should we launch?", self.answers)
        self.assertEqual(record.status, "DISSENT")
        self.assertEqual(record.dissent, ("Missing causal evidence",))
        self.assertFalse(record.execution_authority)
        self.assertEqual(len(record.digest), 64)
        self.assertEqual(len(self.calls), 5)
        # Independent first round never receives another candidate.
        for _, prompt in self.calls[:2]:
            self.assertNotIn("candidate-1", prompt)
            self.assertNotIn("candidate-2", prompt)
        for _, prompt in self.calls[2:4]:
            self.assertIn("candidate-1", prompt)
            self.assertIn("candidate-2", prompt)
            self.assertNotIn('"explorer":', prompt)

    async def test_missing_socratic_answers_fails_closed(self):
        del self.answers["falsification"]
        with self.assertRaisesRegex(CouncilError, "falsification"):
            await self.council.run("Launch?", self.answers)
        self.assertEqual(self.calls, [])

    async def test_empty_question_rejected(self):
        with self.assertRaises(CouncilError):
            await self.council.run(" ", self.answers)

    async def test_missing_dissent_in_dissent_outcome_fails(self):
        async def chair(system, prompt):
            return json.dumps({"status": "DISSENT", "synthesis": "x",
                               "dissent": [], "uncertainty": []})
        council = SocraticCouncil(self.council.members, chair)
        with self.assertRaisesRegex(CouncilError, "recorded objections"):
            await council.run("Launch?", self.answers)

    async def test_bad_chair_json_fails(self):
        async def chair(system, prompt):
            return "Definitely yes"
        council = SocraticCouncil(self.council.members, chair)
        with self.assertRaises(CouncilError):
            await council.run("Launch?", self.answers)


    async def test_blank_dissent_rejected(self):
        async def chair(system, prompt):
            return json.dumps({"status": "DISSENT", "synthesis": "x",
                               "dissent": [" "], "uncertainty": []})
        council = SocraticCouncil(self.council.members, chair)
        with self.assertRaisesRegex(CouncilError, "non-empty"):
            await council.run("Launch?", self.answers)

    def test_one_expert_rejected(self):
        with self.assertRaises(CouncilError):
            SocraticCouncil({"only": lambda a, b: None}, lambda a, b: None)


if __name__ == "__main__":
    unittest.main()
