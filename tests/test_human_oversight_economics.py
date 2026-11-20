import unittest
from decimal import Decimal

from human_oversight_economics import (
    DeliveryEconomics,
    OversightEntry,
    OversightPhase,
    evaluate,
)


class OversightEconomicsTests(unittest.TestCase):
    def test_verified_breakdown(self):
        d = DeliveryEconomics("task-1", Decimal(100), Decimal(10), Decimal(5), True)
        entries = [OversightEntry("task-1", OversightPhase.PRE_CONTROL, Decimal(30), Decimal(60)),
                   OversightEntry("task-1", OversightPhase.POST_REVIEW, Decimal(15), Decimal(60))]
        result = evaluate(d, entries)
        self.assertEqual(result["oversight_cost"], Decimal(45))
        self.assertEqual(result["net_value"], Decimal(40))
        self.assertEqual(result["oversight_cost_by_phase"]["live_monitoring"], 0)

    def test_unverified_has_no_net_claim(self):
        d = DeliveryEconomics("task-2", Decimal(100), Decimal(10), Decimal(0), False)
        self.assertIsNone(evaluate(d, [])["net_value"])

    def test_cross_delivery_rejected(self):
        d = DeliveryEconomics("task-2", Decimal(1), Decimal(0), Decimal(0), True)
        e = OversightEntry("task-3", OversightPhase.CO_PLANNING, Decimal(1), Decimal(1))
        with self.assertRaises(ValueError):
            evaluate(d, [e])

    def test_negative_cost_rejected(self):
        with self.assertRaises(ValueError):
            OversightEntry("task", OversightPhase.POST_REVIEW, Decimal(-1), Decimal(50))


if __name__ == "__main__":
    unittest.main()
