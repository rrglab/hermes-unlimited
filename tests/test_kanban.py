import json
import unittest
from types import SimpleNamespace
from unlimited.hermes_kanban import HermesKanban, board_for


class KanbanTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def runner(args, **kwargs):
            self.calls.append(args)
            if args[4] == "create":
                return SimpleNamespace(returncode=0, stdout='{"id":"actual-task"}')
            return SimpleNamespace(returncode=0, stdout=json.dumps([
                {"id":"actual-task","tenant":"tenant-a","assignee":"role-a",
                 "created_by":"hermes-unlimited","status":"done"}]))
        self.adapter = HermesKanban(run=runner, board=board_for("provider", "tenant-a"))
        self.evidence = {"verified": True, "authority_granted": False,
                         "binding_digest": "signed", "profile": "role-a"}

    def test_queues_native_hermes(self):
        result = self.adapter.enqueue(tenant="tenant-a", assignee="role-a",
                                      task_id="request-1", title="Task", body="Body",
                                      identity_evidence=self.evidence)
        self.assertFalse(result["executed"])
        self.assertIn("--idempotency-key", self.calls[0])

    def test_leading_dash_title_and_body_are_data_not_flags(self):
        self.adapter.enqueue(tenant="tenant-a", assignee="role-a",
                             task_id="request-2", title="-not-an-option",
                             body="--malicious-flag", identity_evidence=self.evidence)
        args = self.calls[0]
        self.assertEqual(args[-2:], ["--", "-not-an-option"])
        self.assertIn("--body=--malicious-flag", args)

    def test_requires_verified_identity(self):
        with self.assertRaises(PermissionError):
            self.adapter.enqueue(tenant="tenant-a", assignee="role-a",
                                 task_id="request-1", title="Task", body="Body",
                                 identity_evidence={"verified": True})
        self.assertFalse(self.calls)

    def test_reads_real_scoped_result(self):
        result = self.adapter.result(tenant="tenant-a", assignee="role-a", task_id="actual-task")
        self.assertTrue(result["completed"])
        self.assertFalse(result["independently_verified"])

    def test_mismatched_tenant_not_completion(self):
        result = self.adapter.result(tenant="tenant-b", assignee="role-a", task_id="actual-task")
        self.assertFalse(result["found"])

    def test_mismatched_assignee_not_completion(self):
        result = self.adapter.result(tenant="tenant-a", assignee="role-b", task_id="actual-task")
        self.assertFalse(result["found"])


if __name__ == "__main__":
    unittest.main()
