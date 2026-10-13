import unittest
from mag7.signals import SignalConfig, signal_at


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.config = SignalConfig(trend_window=4, vol_window=3)

    def test_future_observations_cannot_change_past_signal(self):
        past = [100, 101, 100, 104, 106]
        expected = signal_at(past, 4, self.config)
        self.assertEqual(expected, signal_at(past + [1, 99999], 4, self.config))

    def test_warmup_has_no_signal(self):
        self.assertIsNone(signal_at([100, 101, 102], 2, self.config))

    def test_downtrend_exits_qld(self):
        result = signal_at([100, 98, 96, 94], 3, self.config)
        self.assertFalse(result.trend_up)
        self.assertEqual(result.qld_target, 0)

    def test_high_vol_reduces_allocation(self):
        result = signal_at([100, 150, 90, 180], 3, self.config)
        self.assertEqual(result.state, "up_high_vol")
        self.assertGreater(result.qld_target, 0)
        self.assertLess(result.qld_target, self.config.qld_cap)

    def test_constant_positive_returns_hit_cap(self):
        result = signal_at([100, 200, 400, 800], 3, self.config)
        self.assertEqual(result.annual_vol, 0)
        self.assertEqual(result.qld_target, self.config.qld_cap)

    def test_flat_prices_are_not_positive_trend(self):
        result = signal_at([100] * 4, 3, self.config)
        self.assertEqual(result.qld_target, 0)

    def test_invalid_prices_fail(self):
        for bad in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                signal_at([100, 101, bad, 103], 3, self.config)


if __name__ == "__main__":
    unittest.main()
