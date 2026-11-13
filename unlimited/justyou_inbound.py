"""Development-only, receive-only JustYou -> Hermes Unlimited handoff.

The trusted channel adapter must authenticate the sender before invoking this
bridge. This module never constructs VerifiedOrigin from untrusted input,
executes an agent, or grants authority.
"""
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Any


@dataclass(frozen=True)
class AcceptedInbound:
    sender: str
    recipient: str
    message_id: str
    proof_ref: str
    text: str


class JustYouInboundBridge:
    """Use the real JustYou InboundFrontDoor and an injected trusted sink."""

    def __init__(self, frontdoor: Any, deliver: Callable[[AcceptedInbound], None]):
        if not callable(getattr(frontdoor, "accept", None)):
            raise TypeError("JustYou InboundFrontDoor required")
        if not callable(deliver):
            raise TypeError("trusted delivery callback required")
        self._frontdoor = frontdoor
        self._deliver = deliver
        self._delivered: dict[tuple[str, str, str], AcceptedInbound] = {}
        self._lock = RLock()

    def receive(self, *, origin: Any, recipient_address: str,
                message_id: str, text: str) -> AcceptedInbound:
        # The real JustYou frontdoor rejects unverified origins, unknown
        # bindings, conflicting replays and invalid addresses.
        envelope = self._frontdoor.accept(
            origin=origin, recipient_address=recipient_address,
            message_id=message_id, text=text,
        )
        provenance = envelope.provenance
        accepted = AcceptedInbound(
            sender=envelope.sender_address,
            recipient=envelope.recipient_address,
            message_id=provenance["message_id"],
            proof_ref=provenance["proof_ref"],
            text=envelope.payload["text"],
        )
        key = (provenance["verified_channel"],
               provenance["verified_endpoint"], accepted.message_id)
        with self._lock:
            previous = self._delivered.get(key)
            if previous is not None:
                if previous != accepted:
                    raise ValueError("conflicting delivery replay")
                return previous
            # Callback failures are not acknowledged; caller retries.
            # Production requires durable inbox/outbox for crash-safe delivery.
            self._deliver(accepted)
            self._delivered[key] = accepted
            return accepted
