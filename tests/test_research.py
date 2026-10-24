from dataclasses import replace
import unittest
import numpy as np
import pandas as pd
from bot.backtest import run, benchmark
from bot.config import LIMITS, SYMBOLS
from bot.data import validate, align, align_research, fingerprint, frames_from_bars
from bot.research import compare
from bot.strategies import signals, SHADOW_STRATEGIES, STRATEGIES
from helpers import frames, raw_bars


class ResearchTests(unittest.TestCase):
    def test_input_replay_has_identical_fingerprint(self):
        original = frames(30)
        self.assertEqual(fingerprint(original), fingerprint(frames_from_bars(raw_bars(original))))

    def test_future_mutation_does_not_change_past_signals_or_fills(self):
        data = frames(50)
        changed = {s: f.copy() for s, f in data.items()}
        point = data["SPY"].index[180]
        for f in changed.values():
            f.loc[point:, ["Open", "High", "Low", "Close"]] *= 1.4
        for strategy in SHADOW_STRATEGIES:
            pd.testing.assert_frame_equal(signals(data["SPY"], strategy).loc[:point].iloc[:-1],
                                          signals(changed["SPY"], strategy).loc[:point].iloc[:-1])
            a, b = run(data, strategy), run(changed, strategy)
            self.assertEqual([t for t in a["trades"] if pd.Timestamp(t["timestamp"]) < point],
                             [t for t in b["trades"] if pd.Timestamp(t["timestamp"]) < point])

    def test_entry_uses_previous_bar_and_costs(self):
        data = frames(10, constant=True)
        for f in data.values():
            f.loc[:, "Close"] = np.arange(len(f)) * .1 + 100
            f.loc[:, "High"] = f.Close + 1
        result = run(data, "trend_6_24")
        self.assertTrue(result["trades"])
        for t in result["trades"]:
            if t["side"] == "buy":
                self.assertLess(pd.Timestamp(t["signal_timestamp"]), pd.Timestamp(t["timestamp"]))
                self.assertAlmostEqual(t["price"], 100 * (1 + LIMITS.slippage_bps / 10000))
                self.assertLessEqual(t["qty"] * t["price"], 400)
                self.assertGreater(t["cost"], 0)

    def test_gap_loss_is_not_filled_at_stop_price(self):
        data = frames(15, constant=True)
        for f in data.values():
            f.loc[:, "Close"] = np.arange(len(f)) * .01 + 100
            f.loc[:, "High"] = f.Close + 1
            f.iloc[40:, :4] *= .70
        result = run(data, "trend_6_24")
        exits = [t for t in result["trades"] if t["side"] == "sell" and t["reason"] == "drawdown_halt"]
        self.assertTrue(exits)
        self.assertLess(exits[0]["price"], 75)
        self.assertTrue(result["halted"])
        self.assertLess(result["metrics"]["max_drawdown_pct"], -8)

    def test_reject_corrupt_data(self):
        original = frames(10)["SPY"]
        for value in (float("nan"), float("inf"), -1, 0):
            f = original.copy()
            f.iloc[1, 0] = value
            with self.assertRaises(ValueError): validate(f)
        with self.assertRaises(ValueError): validate(original.iloc[::-1])
        with self.assertRaises(ValueError): validate(pd.concat([original, original]))
        data = frames(10)
        data["IWM"] = data["IWM"].iloc[:-1]
        with self.assertRaises(ValueError): align(data)

    def test_research_aligns_only_observed_small_missing_sample(self):
        original = frames(30)
        trimmed = {s: f.copy() for s, f in original.items()}
        missing = trimmed["IWM"].index[25]
        trimmed["IWM"] = trimmed["IWM"].drop(missing)
        with self.assertRaisesRegex(ValueError, "Missing or misaligned"):
            align(trimmed)
        fixed = align_research(trimmed)
        self.assertEqual(len(fixed["SPY"]), len(original["SPY"]) - 1)
        self.assertNotIn(missing, fixed["SPY"].index)
        for symbol in SYMBOLS:
            pd.testing.assert_frame_equal(fixed[symbol], original[symbol].drop(missing))
        self.assertEqual(fingerprint(fixed), fingerprint(align_research(trimmed)))

    def test_research_rejects_major_missing_data(self):
        data = frames(30)
        data["IWM"] = data["IWM"].iloc[40:]
        with self.assertRaisesRegex(ValueError, "threshold exceeded"):
            align_research(data)

    def test_research_rejects_no_overlapping_data(self):
        data = frames(30)
        data["IWM"] = data["IWM"].copy()
        data["IWM"].index += pd.Timedelta(days=365)
        with self.assertRaisesRegex(ValueError, "No common"):
            align_research(data)

    def test_constant_market_loses_cost_and_benchmark_charged(self):
        data = frames(20, constant=True)
        result = run(data, "trend_6_24")
        self.assertEqual(result["metrics"]["orders"], 0)
        b = benchmark(data["SPY"], data["SPY"].index[30], data["SPY"].index[-1])
        self.assertLess(b["return_pct"], 0)

    def test_higher_costs_not_profitable_on_fixed_constant_signal(self):
        data = frames(10, constant=True)
        for f in data.values():
            f.loc[:, "Close"] = np.arange(len(f)) * .001 + 100
            f.loc[:, "High"] = f.Close + 1
        a = run(data, "trend_6_24")
        b = run(data, "trend_6_24", limits=replace(LIMITS, slippage_bps=29))
        self.assertLess(b["metrics"]["final_capital_usd"], a["metrics"]["final_capital_usd"])

    def test_holdout_cannot_change_strategy_selection(self):
        # Keep runtime bounded; compare() split and selection exercised with
        # a mocked engine, while actual causal execution is tested above.
        from unittest.mock import patch
        data = frames(260)
        def fake_run(frames_, strategy, start=None, end=None, limits=LIMITS):
            m = dict(return_pct=1 if strategy == STRATEGIES[0] else 0, max_drawdown_pct=-1,
                     days=70, round_trips=35, orders=70, final_capital_usd=2020, modeled_cost_usd=1, sharpe_daily=1)
            return dict(metrics=m, halted=False, trades=[], decisions=[], equity={})
        with patch("bot.research.run", side_effect=fake_run):
            result = compare(data)
            changed = {s: f.copy() for s, f in data.items()}
            for f in changed.values(): f.loc[pd.Timestamp(result["split"]["holdout_start"]):, "Close"] *= 1.001
            self.assertEqual(result["selected_on_validation"], compare(changed)["selected_on_validation"])
        self.assertLess(pd.Timestamp(result["split"]["validation_start"]), pd.Timestamp(result["split"]["holdout_start"]))


if __name__ == "__main__":
    unittest.main()
