from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import numpy as np

from bot.alpaca import ExecutionPaper, SafetyError
from bot.shadow import advance, shadow_cycle
from bot.state import load
from helpers import frames


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = frames(20, constant=True)
        for frame in self.data.values():
            prices = 100 + np.arange(len(frame)) * .01
            frame.loc[:, "Open"] = prices
            frame.loc[:, "Close"] = prices
            frame.loc[:, "High"] = prices + .10
            frame.loc[:, "Low"] = prices - .10

    def slice(self, stop):
        return {symbol: frame.iloc[:stop].copy() for symbol, frame in self.data.items()}

    def test_starts_forward_only_then_fills_next_unseen_bar(self):
        first = advance(self.slice(-1), self.directory, "account")
        self.assertTrue(all(item["fills"] == 0 for item in first["strategies"].values()))
        self.assertEqual(first["strategies"]["trend_6_24"]["pending"]["side"], "buy")

        second = advance(self.data, self.directory, "account")
        trend = second["strategies"]["trend_6_24"]
        self.assertEqual(trend["fills"], 1)
        self.assertEqual(trend["positions"], ["SPY"])
        self.assertLess(trend["equity_usd"], 2000)  # modeled entry friction
        self.assertGreater(trend["modeled_cost_usd"], 0)
        self.assertEqual(load(self.directory / "shadow-state.json")["last_bar"],
                         str(self.data["SPY"].index[-1]))

        duplicate = advance(self.data, self.directory, "account")
        self.assertEqual(duplicate["strategies"]["trend_6_24"]["fills"], 1)

    def test_account_and_strategy_state_changes_fail_closed(self):
        advance(self.data, self.directory, "account")
        with self.assertRaisesRegex(SafetyError, "state/account"):
            advance(self.data, self.directory, "other")
        state = load(self.directory / "shadow-state.json")
        state["strategies"].pop("trend_24_72")
        from bot.state import atomic_json
        atomic_json(self.directory / "shadow-state.json", state)
        with self.assertRaisesRegex(SafetyError, "strategy set"):
            advance(self.data, self.directory, "account")

    def test_shadow_rejects_client_with_write_capability_before_network(self):
        client = Mock(spec=ExecutionPaper)
        with self.assertRaisesRegex(SafetyError, "read-only"):
            shadow_cycle(client, self.directory)
        client.account.assert_not_called()


if __name__ == "__main__":
    unittest.main()
