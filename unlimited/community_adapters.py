"""Free community adapter discovery and contributor scaffolding.

Discovery is not activation. Never imports adapter code, loads credentials,
enables a tenant capability, or grants execution authority.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .integrations import integration_catalog

_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.-]{1,80}$")
_SPDX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
_KNOWN_STATES = {"catalog-only", "experimental", "verified"}
_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "adapters" / "community"


class CommunityAdapterError(ValueError):
    pass


def _https(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    url = urlsplit(value)
    return url.scheme == "https" and bool(url.hostname) and not (
        url.username or url.password or url.fragment
    )


def validate_manifest(value: object) -> dict:
    """Strict, inert metadata; no code loading or authority inferred."""
    if not isinstance(value, dict):
        raise CommunityAdapterError("MANIFEST_NOT_OBJECT")
    required = {
        "schema_version", "id", "name", "version", "description",
        "upstream_url", "documentation_url", "license", "interface",
        "capabilities", "state", "source_available", "community_free",
        "provider_charges_may_apply", "justyou_required",
    }
    if set(value) != required:
        raise CommunityAdapterError("MANIFEST_FIELDS_INVALID")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise CommunityAdapterError("SCHEMA_NOT_SUPPORTED")
    if not isinstance(value["id"], str) or not _ID.fullmatch(value["id"]):
        raise CommunityAdapterError("ADAPTER_ID_INVALID")
    if not isinstance(value["version"], str) or not _VERSION.fullmatch(value["version"]):
        raise CommunityAdapterError("VERSION_INVALID")
    if any(not isinstance(value[key], str) or not value[key].strip() or
           len(value[key]) > 240 for key in ("name", "description")):
        raise CommunityAdapterError("TEXT_INVALID")
    if not _https(value["upstream_url"]) or not _https(value["documentation_url"]):
        raise CommunityAdapterError("HTTPS_URL_REQUIRED")
    if not isinstance(value["license"], str) or not _SPDX.fullmatch(value["license"]):
        raise CommunityAdapterError("LICENSE_INVALID")
    if value["interface"] not in ("mcp", "api", "webhook", "cli", "plugin"):
        raise CommunityAdapterError("INTERFACE_INVALID")
    caps = value["capabilities"]
    if (not isinstance(caps, list) or not 1 <= len(caps) <= 32
            or any(not isinstance(c, str) or not _CAPABILITY.fullmatch(c) for c in caps)
            or len(set(caps)) != len(caps)):
        raise CommunityAdapterError("CAPABILITIES_INVALID")
    if not isinstance(value["state"], str) or value["state"] not in _KNOWN_STATES:
        raise CommunityAdapterError("STATE_INVALID")
    for key in ("source_available", "community_free", "provider_charges_may_apply", "justyou_required"):
        if type(value[key]) is not bool:
            raise CommunityAdapterError("BOOLEAN_FIELD_INVALID")
    if value["community_free"] is not True or value["justyou_required"] is not True:
        raise CommunityAdapterError("FREE_AND_JUSTYOU_REQUIRED")
    # A repository being mentioned is not evidence of a working implementation.
    if value["state"] == "verified":
        raise CommunityAdapterError("VERIFICATION_REQUIRES_SEPARATE_HOST_ADMISSION")
    return dict(value)


def list_adapters(root: Path = _DEFAULT_ROOT) -> list[dict]:
    """Combine legacy metadata entries and user-contributed manifests."""
    root = Path(root)
    records = []
    for item in integration_catalog():
        records.append({
            "id": item["key"], "name": item["key"], "upstream": item["upstream"],
            "interface": item["interface"], "state": "catalog-only",
            "community_free": True, "provider_charges_may_apply": True,
            "justyou_required": True, "can_execute": False,
            "source": "legacy-catalog",
        })
    if root.exists():
        for file in sorted(root.glob("*/adapter.json")):
            if file.is_symlink() or file.parent.is_symlink():
                raise CommunityAdapterError("SYMLINK_NOT_ALLOWED")
            try:
                data = validate_manifest(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError, UnicodeError) as exc:
                raise CommunityAdapterError(f"INVALID_MANIFEST:{file.parent.name}") from exc
            if file.parent.name != data["id"]:
                raise CommunityAdapterError("MANIFEST_DIRECTORY_MISMATCH")
            records.append({
                **data, "upstream": data["upstream_url"],
                "can_execute": False, "source": "community-manifest",
            })
    ids = [x["id"] for x in records]
    if len(ids) != len(set(ids)):
        raise CommunityAdapterError("DUPLICATE_ADAPTER_ID")
    return sorted(records, key=lambda x: x["id"])


def activation_check(adapter_id: str, *, justyou_verified: bool, tenant_id: str,
                     host_authorized: bool = False, root: Path = _DEFAULT_ROOT) -> dict:
    """Explain prerequisites without performing actions or accepting caller authority."""
    record = next((x for x in list_adapters(root) if x["id"] == adapter_id), None)
    if record is None:
        raise CommunityAdapterError("UNKNOWN_ADAPTER")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise CommunityAdapterError("TENANT_REQUIRED")
    # host_authorized is informational only; a boolean is not an admission permit.
    return {
        "adapter_id": adapter_id, "tenant": tenant_id, "enabled": False,
        "executable": False,
        "identity_ready": justyou_verified is True,
        "catalog_state": record["state"],
        "steps": [
            "Connect the upstream provider using its own documented API or CLI",
            "Verify JustYou identity through the trusted Hermes host",
            "Review adapter code and independent unit/contract/security/integration evidence",
            "Obtain exact-version pinned approval and tenant capability grant from the existing host adapter gate",
            "Run genuine end-to-end API readback before marking integration verified",
        ],
        "notice": "Catalog discovery is free. Provider API, hosting, or usage fees may apply.",
    }


def scaffold(adapter_id: str, dest: Path) -> Path:
    """Generate a contributor-owned manifest without touching existing adapters."""
    if not isinstance(adapter_id, str) or not _ID.fullmatch(adapter_id):
        raise CommunityAdapterError("ADAPTER_ID_INVALID")
    target = Path(dest) / adapter_id
    target.mkdir(parents=True, exist_ok=False)
    template = {
        "schema_version": 1, "id": adapter_id, "name": adapter_id,
        "version": "0.1.0", "description": "Describe one existing upstream capability",
        "upstream_url": "https://example.org/", "documentation_url": "https://example.org/docs",
        "license": "Apache-2.0", "interface": "api",
        "capabilities": ["service.read"], "state": "catalog-only",
        "source_available": False, "community_free": True,
        "provider_charges_may_apply": True, "justyou_required": True,
    }
    (target / "adapter.json").write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    (target / "README.md").write_text(
        "# " + adapter_id + "\n\n"
        "Replace placeholder metadata, link the upstream API, and implement a thin adapter "
        "using existing Hermes tools. Never bundle credentials or copy upstream code. "
        "Provide contract/security tests before requesting verification.\n",
        encoding="utf-8")
    (target / "adapter.py").write_text(
        '"""Optional adapter implementation template, not auto-loaded by the catalog."""\n'
        'def capabilities():\n'
        '    """Advertise capabilities only; no authority is granted here."""\n'
        '    return ("service.read",)\n\n'
        'def execute(*, request, trusted_host):\n'
        '    """Implement using documented upstream API; require host authorization."""\n'
        '    raise NotImplementedError("Implement and independently test before requesting approval")\n',
        encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hermes Unlimited community adapter discovery")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p = sub.add_parser("inspect")
    p.add_argument("id")
    p = sub.add_parser("validate")
    p.add_argument("--directory", default=str(_DEFAULT_ROOT))
    p = sub.add_parser("scaffold")
    p.add_argument("id")
    p.add_argument("--directory", default=".")
    args = parser.parse_args(argv)
    if args.command == "scaffold":
        print(scaffold(args.id, Path(args.directory)))
        return
    if args.command == "validate":
        directory = Path(args.directory)
        if not directory.is_dir():
            parser.error("Adapter directory does not exist")
        entries = list_adapters(directory)
        print(json.dumps({"valid": True, "count": len(entries)}, sort_keys=True))
        return
    items = list_adapters()
    if args.command == "inspect":
        items = [r for r in items if r["id"] == args.id]
        if not items:
            parser.error("Unknown adapter")
    print(json.dumps(items, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
