import unittest

from tests import _bootstrap  # noqa: F401  (sets up sys.path)
import scoring


def m(net=None, dd=None, pf=None, trades=None):
    d = {}
    if net is not None:
        d["total_net_profit"] = net
    if dd is not None:
        d["relative_drawdown_pct"] = dd
    if pf is not None:
        d["profit_factor"] = pf
    if trades is not None:
        d["total_trades"] = trades
    return d


class TestScoring(unittest.TestCase):
    def test_over_ceiling_always_below_compliant(self):
        # A hugely profitable but over-ceiling candidate must score below a
        # barely-profitable compliant one.
        over = m(net=1_000_000.0, dd=15.01, pf=5.0, trades=500)
        compliant = m(net=1.0, dd=15.0, pf=1.0, trades=500)
        self.assertLess(scoring.score(over), scoring.score(compliant))

    def test_over_ceiling_below_worst_compliant(self):
        over = m(net=999999.0, dd=99.0, pf=3.0, trades=500)
        # Even a losing but compliant candidate ranks above the over-ceiling one.
        compliant_loss = m(net=-500.0, dd=10.0, pf=0.5, trades=500)
        self.assertLess(scoring.score(over), scoring.score(compliant_loss))

    def test_net_profit_ordering_among_compliant(self):
        low = m(net=100.0, dd=10.0, pf=1.2, trades=500)
        high = m(net=200.0, dd=10.0, pf=1.2, trades=500)
        self.assertLess(scoring.score(low), scoring.score(high))

    def test_pf_tiebreaker(self):
        a = m(net=100.0, dd=10.0, pf=1.1, trades=500)
        b = m(net=100.0, dd=10.0, pf=2.5, trades=500)
        self.assertLess(scoring.score(a), scoring.score(b))
        # But PF must not override a real net-profit difference.
        rich_lowpf = m(net=100.5, dd=10.0, pf=1.0, trades=500)
        poor_highpf = m(net=100.0, dd=10.0, pf=9.0, trades=500)
        self.assertGreater(scoring.score(rich_lowpf), scoring.score(poor_highpf))

    def test_pf_tiebreaker_smallest_delta_headroom(self):
        # Regression guard on float headroom. The PF tiebreaker sits on top of
        # TIER_A_OFFSET (~1e9); at that magnitude float64 resolution is ~1.2e-7.
        # Two compliant candidates with IDENTICAL net profit and trade count but
        # a PF gap of 0.001 (the smallest meaningful delta) must still produce
        # strictly distinguishable scores, with the higher-PF one scoring higher.
        # If a future edit raises TIER_A_OFFSET or lowers PF_TIEBREAK_WEIGHT
        # enough to collapse the tiebreaker to float noise, this test fails.
        lower_pf = m(net=1234.0, dd=10.0, pf=1.500, trades=500)
        higher_pf = m(net=1234.0, dd=10.0, pf=1.501, trades=500)
        s_low = scoring.score(lower_pf)
        s_high = scoring.score(higher_pf)
        self.assertLess(s_low, s_high)
        self.assertNotEqual(s_low, s_high)

    def test_low_trade_penalty(self):
        many = m(net=100.0, dd=10.0, pf=1.2, trades=100)
        few = m(net=100.0, dd=10.0, pf=1.2, trades=10)
        self.assertLess(scoring.score(few), scoring.score(many))

    def test_over_ceiling_ordering_by_overage(self):
        small_over = m(net=100.0, dd=16.0, pf=1.2, trades=500)
        big_over = m(net=100.0, dd=40.0, pf=1.2, trades=500)
        self.assertGreater(scoring.score(small_over), scoring.score(big_over))

    def test_missing_metrics_are_worst_case(self):
        empty = scoring.score({})
        none_metrics = scoring.score(None)
        good = scoring.score(m(net=100.0, dd=5.0, pf=1.5, trades=500))
        self.assertLess(empty, good)
        self.assertLess(none_metrics, good)

    def test_none_dd_treated_as_over_ceiling(self):
        # Missing DD -> worst-case DD -> must be in the lower tier.
        no_dd = m(net=1000.0, pf=2.0, trades=500)
        compliant = m(net=1.0, dd=1.0, pf=1.0, trades=500)
        self.assertLess(scoring.score(no_dd), scoring.score(compliant))


if __name__ == "__main__":
    unittest.main()
