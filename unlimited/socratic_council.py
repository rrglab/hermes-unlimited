"""Socratic Council: provider-neutral deliberation, no execution authority.

Existing canonical counterparts:
- valo-platform decision_governance/socratic.py and council.py
- research-factory factory_runtime/llm_council.py

This Hermes-facing adapter uses injected model callables. It deliberately does
not depend on internal platform libraries or permit external effects.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable, Mapping

ModelCall = Callable[[str, str], Awaitable[str]]
QUESTIONS = (
    ("clarification", "What exactly is the problem, rather than its proposed solution?"),
    ("purpose", "What outcome matters, and to whom?"),
    ("assumptions", "Which assumptions would invalidate the proposal if false?"),
    ("evidence", "What supports the claim, and what is missing?"),
    ("alternatives", "Which materially different options, including doing nothing, exist?"),
    ("consequences", "Who bears costs, risks and second-order effects?"),
    ("falsification", "What observable result would prove this recommendation wrong?"),
)
DEFAULT_LENSES = ("explorer", "builder", "economist", "skeptic")


@dataclass(frozen=True)
class CouncilRecord:
    question: str
    answers: Mapping[str, str]
    independent: Mapping[str, str]
    anonymous_critiques: Mapping[str, str]
    synthesis: str
    dissent: tuple[str, ...]
    uncertainty: tuple[str, ...]
    status: str
    digest: str
    execution_authority: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class CouncilError(ValueError):
    pass


def _json_object(raw: str) -> dict:
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        raise CouncilError("Chair must return a JSON object") from None
    if not isinstance(result, dict):
        raise CouncilError("Chair must return a JSON object")
    return result


class SocraticCouncil:
    """Blind first opinions, anonymous challenge, and dissent-preserving synthesis.

    Callers must supply independently configured member functions. Multiple
    roles using the same model do not establish model-family independence.
    """

    def __init__(self, members: Mapping[str, ModelCall], chair: ModelCall):
        if len(members) < 2 or len(set(members)) != len(members):
            raise CouncilError("At least two unique expert roles are required")
        if not all(role and callable(fn) for role, fn in members.items()):
            raise CouncilError("Every expert needs an identity and a model callable")
        if not callable(chair):
            raise CouncilError("Chair model callable required")
        self.members = dict(members)
        self.chair = chair

    async def run(self, question: str, answers: Mapping[str, str]) -> CouncilRecord:
        if not isinstance(question, str) or not question.strip():
            raise CouncilError("Question is required")
        if not isinstance(answers, Mapping):
            raise CouncilError("Socratic answers are required")
        # Snapshot answers immediately so later mutation cannot change the reviewed case.
        snapshot = {key: str(answers.get(key, "")).strip() for key, _ in QUESTIONS}
        missing = [key for key, val in snapshot.items() if not val]
        if missing:
            raise CouncilError("Missing Socratic answers: " + ", ".join(missing))

        case = json.dumps({"question": question, "socratic_answers": snapshot}, sort_keys=True)
        roles = tuple(self.members)
        async def opinion(role: str) -> str:
            return await self.members[role](
                "You are the " + role + " expert. Answer independently. Distinguish "
                "evidence, inference, uncertainty and values. State the strongest "
                "counterargument and a falsification test. Never invent sources.",
                case)
        # No expert sees other outputs in this phase.
        drafts = await asyncio.gather(*(opinion(role) for role in roles))
        if any(not isinstance(s, str) or not s.strip() for s in drafts):
            raise CouncilError("Every expert must return a substantive opinion")
        independent = dict(zip(roles, drafts))
        # Stable anonymous labels. Do not disclose peer role/model identities.
        anonymized = {f"candidate-{i+1}": draft for i, draft in enumerate(drafts)}
        challenge_case = json.dumps({"case": case, "candidates": anonymized},
                                    sort_keys=True)
        async def challenge(role: str) -> str:
            return await self.members[role](
                "Blind peer review. Critique specific assertions, omissions, "
                "assumptions, causal leaps and falsification tests. Never vote "
                "merely for consensus; identify what could change your mind.",
                challenge_case)
        reviews = await asyncio.gather(*(challenge(role) for role in roles))
        if any(not isinstance(s, str) or not s.strip() for s in reviews):
            raise CouncilError("Every expert must provide a critique")
        critiques = dict(zip(roles, reviews))
        chair_input = json.dumps({"case": case, "candidates": anonymized,
                                  "blind_reviews": tuple(reviews)}, sort_keys=True)
        chair_output = await self.chair(
            "Socratic chair. Preserve unresolved dissent and uncertainty. "
            "Return ONLY JSON with keys synthesis (string), dissent (array "
            "of strings), uncertainty (array of strings), status "
            "(CONSENSUS, DISSENT, or INSUFFICIENT_EVIDENCE). "
            "Never claim execution authority or fabricate citations.", chair_input)
        decision = _json_object(chair_output)
        status = decision.get("status")
        if status not in ("CONSENSUS", "DISSENT", "INSUFFICIENT_EVIDENCE"):
            raise CouncilError("Invalid chair status")
        synthesis = decision.get("synthesis")
        dissent = decision.get("dissent")
        uncertainty = decision.get("uncertainty")
        if not isinstance(synthesis, str) or not synthesis.strip():
            raise CouncilError("Chair synthesis required")
        if not isinstance(dissent, list) or not all(isinstance(x, str) and x.strip() for x in dissent):
            raise CouncilError("Chair dissent must be a list of non-empty strings")
        if not isinstance(uncertainty, list) or not all(isinstance(x, str) and x.strip() for x in uncertainty):
            raise CouncilError("Chair uncertainty must be a list of non-empty strings")
        if status == "DISSENT" and not dissent:
            raise CouncilError("Dissent outcome requires recorded objections")
        payload = {"question": question, "answers": snapshot,
                   "independent": independent, "anonymous_critiques": critiques,
                   "synthesis": synthesis, "dissent": dissent,
                   "uncertainty": uncertainty, "status": status}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
        return CouncilRecord(question, snapshot, independent, critiques,
                             synthesis, tuple(dissent), tuple(uncertainty),
                             status, digest)
