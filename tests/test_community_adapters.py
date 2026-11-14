import json
import tempfile
import unittest
from pathlib import Path

from unlimited.community_adapters import (
    CommunityAdapterError, activation_check, list_adapters, scaffold,
    validate_manifest, main,
)


class CommunityAdaptersTests(unittest.TestCase):
    def test_existing_and_community_catalog_in_one_place(self):
        catalog = list_adapters()
        ids = [a["id"] for a in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        for name in ("ember", "slack", "github", "cloudflare", "matrix", "ghost",
                     "postiz", "comfyui", "mattermost", "outlook", "zulip"):
            self.assertIn(name, ids)
        self.assertTrue(all(a["community_free"] and not a["can_execute"] for a in catalog))
        self.assertTrue(all(a["justyou_required"] for a in catalog))

    def test_discovery_does_not_grant_execution_even_if_host_boolean_claimed(self):
        proposal = activation_check("ember", tenant_id="customer-a",
                                    justyou_verified=True, host_authorized=True)
        self.assertFalse(proposal["enabled"])
        self.assertFalse(proposal["executable"])
        self.assertTrue(proposal["identity_ready"])

    def test_missing_justyou_not_ready(self):
        proposal = activation_check("slack", tenant_id="customer-a", justyou_verified=False)
        self.assertFalse(proposal["identity_ready"])
        self.assertFalse(proposal["enabled"])

    def test_reject_unknown_adapter_and_empty_tenant(self):
        with self.assertRaises(CommunityAdapterError):
            activation_check("unknown", tenant_id="customer-a", justyou_verified=True)
        with self.assertRaises(CommunityAdapterError):
            activation_check("ember", tenant_id="", justyou_verified=True)

    def test_contributor_scaffold_validates_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = scaffold("my-adapter", Path(directory))
            self.assertTrue((target / "README.md").is_file())
            self.assertTrue((target / "adapter.py").is_file())
            self.assertIn("NotImplementedError", (target / "adapter.py").read_text())
            manifest = json.loads((target / "adapter.json").read_text())
            self.assertEqual(validate_manifest(manifest)["id"], "my-adapter")
            self.assertEqual(len(list_adapters(Path(directory))), 7)
            with self.assertRaises(FileExistsError):
                scaffold("my-adapter", Path(directory))

    def test_bad_manifest_and_claimed_approval_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = scaffold("made-up", Path(directory))
            path = target / "adapter.json"
            good = json.loads(path.read_text())
            for edits in ({"community_free": False}, {"justyou_required": False},
                          {"state": "verified"}, {"state": []},
                          {"state": {}},
                          {"capabilities": ["unsafe;rm -rf"]}, {"upstream_url": "http://localhost:8080"},
                          {"id": "../invalid"}, {"extra": "data"}):
                with self.subTest(edits=edits):
                    bad = {**good, **edits}
                    with self.assertRaises(CommunityAdapterError):
                        validate_manifest(bad)
            path.write_text(json.dumps({**good, "id": "other"}))
            with self.assertRaises(CommunityAdapterError):
                list_adapters(Path(directory))

    def test_contributors_can_share_code_without_claiming_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            target = scaffold("shared-example", Path(directory))
            p = target / "adapter.json"
            manifest = json.loads(p.read_text())
            manifest["source_available"] = True
            p.write_text(json.dumps(manifest))
            entries = list_adapters(Path(directory))
            self.assertTrue(next(x for x in entries if x["id"] == "shared-example")["source_available"])
            self.assertFalse(next(x for x in entries if x["id"] == "shared-example")["can_execute"])

    def test_cli_validation_rejects_missing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as error:
                main(["validate", "--directory", str(Path(directory) / "not-a-folder")])
            self.assertEqual(error.exception.code, 2)

    def test_symlink_manifest_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            a = scaffold("example", p)
            file = a / "adapter.json"
            copy = p / "copy.json"
            copy.write_bytes(file.read_bytes())
            file.unlink()
            file.symlink_to(copy)
            with self.assertRaises(CommunityAdapterError):
                list_adapters(p)
