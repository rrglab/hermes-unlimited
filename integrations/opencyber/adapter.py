"""Fail-closed OpenCyber MCP catalog and result adapter.

Based on mitkox/opencyber Apache-2.0 contracts, pinned upstream
daf274cb61996fd14b8a97df332457e2970b5b63.
This module does not execute tools, mint permits, or assert authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

KNOWN_EFFECTS = frozenset({"process", "filesystem", "network", "device", "secret", "mutation"})
KNOWN_SCOPES = frozenset({"none", "argv", "url", "device", "engagement"})
KNOWN_COVERAGE = frozenset({"complete", "partial", "unknown", "empty"})


class ContractError(ValueError):
    """Missing, malformed, or unsupported upstream contract."""


@dataclass(frozen=True)
class ToolCapability:
    name: str
    shape: str
    effects: frozenset[str]
    scope: str
    requires_engagement: bool
    returns_target_content: bool

    @property
    def requires_external_clearance(self) -> bool:
        # All OpenCyber execution remains operator-controlled. Even inspect
        # calls can spawn processes or access target-derived sensitive data.
        return bool(self.effects) or self.scope != "none"


def read_tool_capability(tool: Mapping[str, Any]) -> ToolCapability:
    """Read _meta.opencyber from an advertised MCP tool; reject unknown effects."""
    name = tool.get("name")
    meta = tool.get("_meta")
    oc = meta.get("opencyber") if isinstance(meta, dict) else None
    if not isinstance(name, str) or not name.startswith("oc_"):
        raise ContractError("invalid OpenCyber tool name")
    if not isinstance(oc, dict) or oc.get("contract_schema_version") != 1:
        raise ContractError("missing or unsupported OpenCyber tool contract")
    effects = oc.get("effects")
    if not isinstance(effects, list) or any(not isinstance(x, str) for x in effects):
        raise ContractError("effects must be a list of strings")
    effect_set = frozenset(effects)
    if not effect_set <= KNOWN_EFFECTS:
        raise ContractError("unknown effect requires contract review")
    scope = oc.get("scope")
    if scope not in KNOWN_SCOPES:
        raise ContractError("unknown scope requires contract review")
    if not isinstance(oc.get("requires_engagement"), bool):
        raise ContractError("requires_engagement must be boolean")
    if not isinstance(oc.get("returns_target_content"), bool):
        raise ContractError("returns_target_content must be boolean")
    shape = oc.get("shape")
    if shape not in {"inspect", "search", "trace", "compare", "workflow", "observe", "execute", "manage"}:
        raise ContractError("unknown tool shape")
    return ToolCapability(
        name=name, shape=shape, effects=effect_set, scope=scope,
        requires_engagement=oc["requires_engagement"],
        returns_target_content=oc["returns_target_content"],
    )


@dataclass(frozen=True)
class ResultAssessment:
    tool: str
    outcome: str
    coverage: str
    evidence_sha256: str | None
    untrusted_content: bool
    limitations: tuple[str, ...]
    error_code: str | None


def assess_result(result: Mapping[str, Any], *, expected_tool: str) -> ResultAssessment:
    """Preserve partial/unknown coverage and distinguish assertion from evidence."""
    contract = result.get("contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ContractError("missing or unsupported result envelope")
    tool = contract.get("tool")
    if tool != expected_tool or not isinstance(tool, str) or not tool.startswith("oc_"):
        raise ContractError("result is not bound to expected tool")
    ok = result.get("ok")
    if not isinstance(ok, bool):
        raise ContractError("ok must be boolean")
    coverage = result.get("coverage")
    status = coverage.get("status") if isinstance(coverage, dict) else None
    if status not in KNOWN_COVERAGE:
        raise ContractError("missing or unknown coverage")
    provenance = result.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("untrusted_content"), bool):
        raise ContractError("missing target-content trust marker")
    limitations = result.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(x, str) for x in limitations):
        raise ContractError("invalid limitations")
    evidence = result.get("evidence")
    digest = evidence.get("sha256") if isinstance(evidence, dict) else None
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ContractError("invalid evidence digest")
    error = result.get("error")
    if not ok and (not isinstance(error, dict) or not isinstance(error.get("code"), str)):
        raise ContractError("refusal must include error code")
    # A sha256 identifies returned data, not external validation of target state.
    # In particular, successful but partial coverage is never a verified success.
    outcome = "REFUSED" if not ok else ("OBSERVED_COMPLETE" if status in {"complete", "empty"} else "INCOMPLETE")
    return ResultAssessment(
        tool=tool, outcome=outcome, coverage=status,
        evidence_sha256=digest,
        untrusted_content=provenance["untrusted_content"],
        limitations=tuple(limitations),
        error_code=error["code"] if not ok else None,
    )


def offline_stdio_command(container: str = "opencyber-beta") -> tuple[str, ...]:
    """Client launch command; the container must be created separately offline."""
    if not container or not all(c.isalnum() or c in "._-" for c in container):
        raise ContractError("invalid container name")
    return ("docker", "exec", "-i", "-e", "OPENCYBER_MCP_MODE=compact", container, "opencyber-mcp")
