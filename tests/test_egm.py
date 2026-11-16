import pytest

from unlimited.egm import request_egm_review


def test_egm_dispatch_uses_existing_t3_scope():
    calls = []
    def dispatch(operation, **payload):
        calls.append((operation, payload))
        return {"review_type": "egm", "project_id": "p1", "thread_id": "t1",
                "completed": True, "review_verified": True}
    result = request_egm_review(dispatch, tenant="tenant", project_id="p1",
                                document="docs/spec.md", mode="feature_spec")
    assert calls == [("t3.egm_review", {"tenant": "tenant", "project_id": "p1",
                                        "document": "docs/spec.md", "mode": "feature_spec"})]
    assert result["completed"] is False
    assert result["review_verified"] is False


@pytest.mark.parametrize("path", ["../secret.md", "/absolute.md", "a/../b.md",
                                  "a//b.md", "a.md\nignored", "code.py"])
def test_bad_review_path_cannot_dispatch(path):
    called = []
    with pytest.raises(ValueError):
        request_egm_review(lambda *args, **kwargs: called.append(args),
                           tenant="tenant", project_id="p", document=path)
    assert not called


def test_untrusted_dispatch_and_malformed_response_rejected():
    with pytest.raises(PermissionError):
        request_egm_review(None, tenant="tenant", project_id="p", document="spec.md")
    with pytest.raises(RuntimeError, match="scope mismatch"):
        request_egm_review(lambda *a, **k: {"review_type": "egm", "project_id": "other",
                                             "thread_id": "t"},
                           tenant="tenant", project_id="p", document="spec.md")
