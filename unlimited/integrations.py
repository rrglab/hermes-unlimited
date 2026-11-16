"""Optional, independently deployed integrations for Unlimited service offerings.

This registry describes verified upstream interfaces; it does not imply that a
customer has configured credentials or that an external action has succeeded.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Integration:
    key: str
    upstream: str
    role: str
    interface: str
    license: str
    state: str = "available_for_configuration"
    can_execute: bool = False


INTEGRATIONS = (
    Integration("open-seo", "every-app/open-seo", "seo_research", "mcp", "MIT"),
    Integration("postiz", "gitroomhq/postiz-app", "social_publishing", "api_cli", "AGPL-3.0"),
    Integration("videolingo", "Huanshere/VideoLingo", "video_localization", "local_worker", "Apache-2.0"),
    Integration("ghost", "TryGhost/Ghost", "publishing_memberships", "admin_api", "MIT"),
    Integration("rea", "morluto/rea", "authorized_software_interoperability", "mcp_cli", "MIT"),
    Integration("comfyui", "comfyanonymous/ComfyUI", "creative_image_video_workflows", "http_api", "GPL-3.0"),
    Integration("nvidia-openshell", "NVIDIA/OpenShell", "technical_sandbox_enforcement", "valo_gateway_runtime_adapter", "Apache-2.0"),
    Integration("nebius", "Nebius", "optional_compute_host", "deployment_provider", "proprietary"),
    Integration("egm", "google/elephant-goldfish-model", "isolated_spec_review", "plugin_via_t3", "Apache-2.0"),
)


def integration_catalog():
    """Return metadata only, never credentials, inferred authority or live state."""
    return [vars(item).copy() for item in INTEGRATIONS]


def integration_for(key):
    return next((item for item in INTEGRATIONS if item.key == key), None)
