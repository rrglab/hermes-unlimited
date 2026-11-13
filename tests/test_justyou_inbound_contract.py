"""Public inbound bridge contract: no private JustYou package required."""
import unittest
from types import SimpleNamespace

from unlimited.justyou_inbound import JustYouInboundBridge


class FrontDoor:
    def accept(self, *, origin, recipient_address, message_id, text):
        if not isinstance(origin, dict) or not origin.get("verified"):
            raise PermissionError("UNVERIFIED_ORIGIN")
        if recipient_address != "@operator":
            raise KeyError("UNKNOWN_RECIPIENT")
        if not message_id:
            raise ValueError("MESSAGE_ID_REQUIRED")
        return SimpleNamespace(
            sender_address="@supplier",
            recipient_address=recipient_address,
            provenance={
                "message_id": message_id,
                "proof_ref": origin["proof"],
                "verified_channel": origin["channel"],
                "verified_endpoint": origin["endpoint"],
            },
            payload={"text": text},
        )


class InboundBridgeContract(unittest.TestCase):
    def setUp(self):
        self.delivered = []
        self.bridge = JustYouInboundBridge(FrontDoor(), self.delivered.append)
        self.origin = {
            "verified": True, "channel": "test-channel",
            "endpoint": "sender-1", "proof": "signed-proof",
        }

    def receive(self, **kwargs):
        args = dict(origin=self.origin, recipient_address="@operator",
                    message_id="m-1", text="Message")
        args.update(kwargs)
        return self.bridge.receive(**args)

    def test_delivers_once(self):
        first = self.receive()
        self.assertEqual((first.sender, first.recipient), ("@supplier", "@operator"))
        self.assertEqual(first.proof_ref, "signed-proof")
        self.assertIs(first, self.receive())
        self.assertEqual(self.delivered, [first])

    def test_fails_closed_on_invalid_origin_or_recipient(self):
        with self.assertRaises(PermissionError):
            self.receive(origin=None)
        with self.assertRaises(KeyError):
            self.receive(recipient_address="@missing")
        self.assertFalse(self.delivered)

    def test_conflicting_replay_rejected(self):
        self.receive()
        with self.assertRaises(ValueError):
            self.receive(text="Different")
        self.assertEqual(len(self.delivered), 1)

    def test_failed_delivery_not_acknowledged(self):
        attempts = []
        def fail_once(message):
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("temporary failure")
        self.bridge._deliver = fail_once
        with self.assertRaises(RuntimeError):
            self.receive()
        self.receive()
        self.assertEqual(len(attempts), 2)

    def test_invalid_dependencies_rejected(self):
        with self.assertRaises(TypeError):
            JustYouInboundBridge(object(), self.delivered.append)
        with self.assertRaises(TypeError):
            JustYouInboundBridge(FrontDoor(), None)


if __name__ == "__main__":
    unittest.main()
