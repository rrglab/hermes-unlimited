"""Optional EGM review dispatch through a trusted, tenant-scoped T3 adapter.

Discovery is not activation. A thread creation result is not a completed review.
The caller must supply the actual trusted scoped dispatcher; this module
cannot infer host identity, grants, or plugin installation from metadata.
"""
import re
from collections.abc import Callable

_SAFE_PATH = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]{0,255}$")
_MODES = {"uninterrupted", "feature_spec", "implementation"}


def request_egm_review(dispatch: Callable, *, tenant: str, project_id: str,
                       document: str, mode: str = "uninterrupted") -> dict:
    if not callable(dispatch):
        raise PermissionError("trusted T3 dispatcher required")
    if not isinstance(tenant, str) or not tenant.strip():
        raise PermissionError("trusted tenant required")
    if not isinstance(project_id, str) or not project_id.strip():
        raise PermissionError("trusted project required")
    if (not isinstance(document, str) or not _SAFE_PATH.fullmatch(document)
            or document.startswith(("/", "-")) or not document.endswith(".md")
            or any(x in ("", ".", "..") for x in document.split("/"))):
        raise ValueError("unsafe EGM target path")
    if mode not in _MODES:
        raise ValueError("unsupported EGM review mode")
    result = dispatch("t3.egm_review", tenant=tenant, project_id=project_id,
                      document=document, mode=mode)
    if not isinstance(result, dict) or result.get("review_type") != "egm":
        raise RuntimeError("T3 returned an invalid EGM review response")
    if result.get("project_id") != project_id or not isinstance(result.get("thread_id"), str):
        raise RuntimeError("T3 review thread scope mismatch")
    # Never promote a T3 thread creation to a verified design or implementation.
    return {"thread_id": result["thread_id"], "project_id": project_id,
            "review_type": "egm", "review_verified": False,
            "completed": False, "evidence_ref": result.get("evidence_ref")}
