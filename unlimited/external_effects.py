"""Opt-in external email and payment adapters; provider acknowledgements are not delivery proof.

No credentials are persisted. Network calls are impossible without explicit authorization,
trusted tenant identity, and a host-supplied approval for this exact effect.
"""
from __future__ import annotations

import hashlib
import json
import smtplib
import ssl
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from typing import Callable, Literal


@dataclass(frozen=True)
class ExternalEffectReceipt:
    kind: Literal["email", "payment"]
    tenant_id: str
    effect_id: str
    state: Literal["provider_accepted", "requires_action", "settled"]
    provider_reference: str
    evidence_digest: str
    # Provider acceptance is not mailbox delivery, nor financial settlement.
    externally_delivered: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _authorize(*, tenant_id: str, identity: str, effect_id: str,
               verify_identity: Callable[[str, str], bool],
               approve_effect: Callable[[str, str, str], bool], authorized: bool) -> None:
    if not tenant_id or not identity or not effect_id:
        raise PermissionError("EXTERNAL_EFFECT_SCOPE_REQUIRED")
    if authorized is not True or verify_identity(tenant_id, identity) is not True:
        raise PermissionError("EXTERNAL_EFFECT_IDENTITY_OR_AUTHORIZATION_DENIED")
    if approve_effect(tenant_id, identity, effect_id) is not True:
        raise PermissionError("EXTERNAL_EFFECT_APPROVAL_REQUIRED")


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class SMTPDeliveryAdapter:
    """Send only with explicit effect approval; SMTP 250 is acceptance, not delivery."""

    def __init__(self, *, host: str, port: int = 465, username: str, password: str,
                 sender: str, smtp_factory=None):
        if not host or not username or not password or not sender or port != 465:
            raise ValueError("SMTP_TLS_CONFIGURATION_REQUIRED")
        self.host, self.port = host, port
        self.username, self.password, self.sender = username, password, sender
        self.smtp_factory = smtp_factory or smtplib.SMTP_SSL

    def send(self, *, tenant_id: str, identity: str, effect_id: str, recipient: str,
             subject: str, body: str, verify_identity, approve_effect,
             authorized: bool = False) -> ExternalEffectReceipt:
        _authorize(tenant_id=tenant_id, identity=identity, effect_id=effect_id,
                   verify_identity=verify_identity, approve_effect=approve_effect,
                   authorized=authorized)
        if not recipient or "\n" in recipient or "\r" in recipient or "@" not in recipient:
            raise ValueError("EMAIL_RECIPIENT_INVALID")
        if not subject or "\n" in subject or "\r" in subject:
            raise ValueError("EMAIL_SUBJECT_INVALID")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, recipient, subject
        msg["X-Hermes-Effect-ID"] = effect_id
        msg.set_content(body)
        with self.smtp_factory(self.host, self.port, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(self.username, self.password)
            rejected = smtp.send_message(msg)
        if rejected:
            raise RuntimeError("SMTP_RECIPIENT_REJECTED")
        return ExternalEffectReceipt("email", tenant_id, effect_id, "provider_accepted",
                                     effect_id, _digest({"effect_id": effect_id, "to": recipient,
                                                         "subject": subject, "body_sha256": hashlib.sha256(body.encode()).hexdigest()}))


class StripePaymentAdapter:
    """Create a bounded PaymentIntent; no implicit charge, capture or settlement claim."""

    def __init__(self, *, api_key: str, stripe_client=None):
        if not api_key:
            raise ValueError("STRIPE_API_KEY_REQUIRED")
        if stripe_client is None:
            import stripe
            stripe_client = stripe
        self.api_key = api_key
        self.client = stripe_client

    def create_payment_intent(self, *, tenant_id: str, identity: str, effect_id: str,
                              amount_minor: int, currency: str, customer_id: str,
                              verify_identity, approve_effect,
                              authorized: bool = False) -> ExternalEffectReceipt:
        _authorize(tenant_id=tenant_id, identity=identity, effect_id=effect_id,
                   verify_identity=verify_identity, approve_effect=approve_effect,
                   authorized=authorized)
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            raise ValueError("PAYMENT_AMOUNT_INVALID")
        if not currency or len(currency) != 3 or not currency.isalpha() or not customer_id:
            raise ValueError("PAYMENT_SCOPE_INVALID")
        # Stripe idempotency prevents duplicate intents on retry; automatic capture
        # and confirmation are disabled pending explicit payment-method consent.
        intent = self.client.PaymentIntent.create(
            amount=amount_minor, currency=currency.lower(), customer=customer_id,
            confirm=False, capture_method="manual",
            metadata={"tenant_id": tenant_id, "effect_id": effect_id},
            idempotency_key=f"hermes:{tenant_id}:{effect_id}", api_key=self.api_key,
        )
        intent_id = str(intent.get("id", ""))
        if not intent_id:
            raise RuntimeError("STRIPE_MISSING_PROVIDER_REFERENCE")
        return ExternalEffectReceipt("payment", tenant_id, effect_id, "requires_action",
                                     intent_id, _digest({"tenant_id": tenant_id, "effect_id": effect_id,
                                                         "payment_intent": intent_id, "amount_minor": amount_minor,
                                                         "currency": currency.lower()}))


def verify_stripe_webhook(*, payload: bytes, signature: str, webhook_secret: str,
                          stripe_client=None) -> dict:
    """Validate signed Stripe event; only captured/paid events may prove settlement."""
    if not signature or not webhook_secret:
        raise PermissionError("PAYMENT_WEBHOOK_SIGNATURE_REQUIRED")
    if stripe_client is None:
        import stripe
        stripe_client = stripe
    event = stripe_client.Webhook.construct_event(payload, signature, webhook_secret)
    kind = str(event.get("type", ""))
    obj = event.get("data", {}).get("object", {})
    return {"event_id": str(event.get("id", "")), "kind": kind,
            "payment_intent": str(obj.get("id", "")),
            "settled": kind == "payment_intent.succeeded" and obj.get("status") == "succeeded"}
