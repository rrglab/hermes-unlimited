# VIA — Hermes Unlimited service offer

VIA is a human-first assistant **offered through Hermes Unlimited** and a potential
conversation-based discovery/distribution channel to other eligible services.
Hermes Unlimited owns the user experience, customer administration and delivery
infrastructure. VIA does not create a separate account, billing or agent runtime.

The discoverable offer lives in `unlimited/offer_catalog.py` and is exposed by
`unlimited_offer_catalog` through a trusted JustYou-scoped Hermes tool.
The offer includes Personal, Family, Business, Enterprise, Public and Partner
audiences as candidate packages—not launched subscriptions.

**Current delivery state:** catalog only. `customer_available=false`,
`offerable=false`, `production_verified=false`, `price=null`. It cannot
be ordered from this offer listing. The existing `unlimited_service_publish`
is a tenant-owned company service registry; it is **not** proof of a fulfilled
VIA product or a validated price.

Before activating VIA for any customer: connect a real conversation channel,
authenticate identity and scopes through JustYou, authorize external effects,
prove a complete Hermes request/fulfillment/result flow, connect optional
continuity and expert referrals with tenant isolation, establish pricing and
billing, and verify customer UX. Listing or dispatching work alone is not
evidence of completed delivery.
