import unittest
import pandas as pd
from simulate import backtest


class LegacyTests(unittest.TestCase):
    def test_v1_flat_market_regression(self):
        data = pd.DataFrame(dict(Open=[100.] * 60, Close=[100.] * 60), index=pd.date_range("2023-01-01", periods=60))
        result = backtest(data)
        self.assertEqual(result["final_capital_usd"], 2000)
        self.assertEqual(result["benchmark_buy_hold_usd"], 2000)
        self.assertEqual(result["trades"], [])

    def test_v1_next_open_and_cost_regression(self):
        data = pd.DataFrame(dict(Open=[100.] * 60, Close=list(range(100, 160))), index=pd.date_range("2023-01-01", periods=60))
        result = backtest(data)
        self.assertEqual(result["trades"][0]["date"], "2023-01-31")
        self.assertEqual(result["final_capital_usd"], round(2000 / 100.1 * 159, 2))
