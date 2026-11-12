"""Opt-in real Hermes CLI integration; never dispatches a model worker.

Run only with HERMES_UNLIMITED_LIVE_KANBAN=1 and an isolated HERMES_HOME.
The identity evidence below is explicitly synthetic; real signed identity
acceptance is covered separately by test_live_justyou_customer.py.
"""
import os
import pathlib
import subprocess
import unittest
import uuid

from unlimited.hermes_kanban import HermesKanban, board_for


@unittest.skipUnless(
    os.environ.get("HERMES_UNLIMITED_LIVE_KANBAN") == "1",
    "opt-in real Hermes Kanban CLI acceptance",
)
class LiveNativeKanbanTests(unittest.TestCase):
    def test_isolated_enqueue_idempotency_and_status(self):
        home_value = os.environ.get("HERMES_HOME")
        self.assertTrue(home_value, "HERMES_HOME must be isolated")
        home = pathlib.Path(home_value).resolve()
        self.assertNotEqual(home, pathlib.Path.home() / ".hermes")
        self.assertTrue(home.is_dir(), "isolated Hermes home must exist")
        hermes = os.environ.get("HERMES_UNLIMITED_HERMES_CLI", "hermes")
        suffix = uuid.uuid4().hex[:8]
        tenant = "synthetic-" + suffix
        provider = "acceptance"
        profile = "acceptancepublic1111"
        board = board_for(provider, tenant)
        create = subprocess.run(
            [hermes, "kanban", "boards", "create", board],
            capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(create.returncode, 0, create.stderr + create.stdout)
        adapter = HermesKanban(hermes=hermes, board=board)
        evidence = {
            "verified": True, "authority_granted": False,
            "binding_digest": "SYNTHETIC_FIXTURE_NOT_AUTHORITY",
            "profile": profile,
        }
        kwargs = dict(
            tenant=tenant, assignee=profile, task_id="one-request",
            title="-leading-dash-title", body="--body-like-argument",
            identity_evidence=evidence,
        )
        result = adapter.enqueue(**kwargs)
        self.assertFalse(result["executed"])
        self.assertEqual(result["status"], "TASK_QUEUED")
        self.assertEqual(adapter.enqueue(**kwargs)["task_id"], result["task_id"])
        observed = adapter.result(
            tenant=tenant, assignee=profile, task_id=result["task_id"],
        )
        self.assertTrue(observed["found"], observed)
        self.assertFalse(observed["completed"], observed)
        self.assertFalse(observed["independently_verified"])
        with self.assertRaises(PermissionError):
            adapter.enqueue(**{**kwargs, "identity_evidence": {}})


if __name__ == "__main__":
    unittest.main()
