"""Hermes Unlimited service-offer catalog. Discovery is not activation or sale.

VIA is a human-facing service AND a channel to other tenant-authorized services.
All availability and prices must come from validated provider configuration;
this public catalog deliberately advertises neither production readiness nor prices.
"""
from copy import deepcopy

_VIA = {
    "service_id": "via",
    "name": "VIA",
    "description": "Human-first AI assistance through familiar conversations and channels.",
    "roles": ["service", "distribution_channel", "partner_offering"],
    "audiences": ["personal", "family", "business", "enterprise", "public", "partner"],
    "capabilities": ["conversation", "needs_intake", "guided_help",
                     "service_discovery", "expert_referral", "continuity"],
    "depends_on": ["justyou", "hermes_unlimited", "ai_bridge",
                   "the_thread_optional", "service_factory_optional",
                   "principal_network_optional"],
    "customer_available": False,
    "offerable": False,
    "production_verified": False,
    "price": None,
    "currency": None,
    "fulfillment": "not_connected",
    "ui_owner": "hermes_unlimited",
    "integration_status": "catalog_only",
}


def service_offer_catalog():
    """Return an isolated, immutable-by-caller snapshot of public offers."""
    return [deepcopy(_VIA)]
