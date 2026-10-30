from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import hashlib
import numpy as np

from bot.alpaca import ExecutionPaper, ReadOnlyPaper, SafetyError
from bot.shadow import (SHADOW_CODE_PREDECESSORS, SHADOW_V2_PREDECESSOR,
                        advance, migrate_shadow, shadow_cycle)
from bot.state import atomic_json, code_hash, load
from bot.strategies import SHADOW_STRATEGIES, STRATEGIES
from helpers import account, frames


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
        self.assertEqual(first["schema"], 3)
        self.assertIn("rsi25_trend", first["strategies"])
        self.assertIn("trend_pullback_rsi_stoch", first["strategies"])
        self.assertTrue(all(item["fills"] == 0 for item in first["strategies"].values()))
        self.assertTrue(all(not item["forward_gate_passed"]
                            for item in first["strategies"].values()))
        self.assertTrue(all("below_60_sessions" in item["blockers"]
                            for item in first["strategies"].values()))
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
        atomic_json(self.directory / "shadow-state.json", state)
        with self.assertRaisesRegex(SafetyError, "strategy set"):
            advance(self.data, self.directory, "account")

    def test_shadow_rejects_client_with_write_capability_before_network(self):
        client = Mock(spec=ExecutionPaper)
        with self.assertRaisesRegex(SafetyError, "read-only"):
            shadow_cycle(client, self.directory)
        client.account.assert_not_called()
        with self.assertRaisesRegex(SafetyError, "read-only"):
            migrate_shadow(client, self.directory)

    def test_rsi_candidate_is_shadow_only_and_cannot_be_executed(self):
        self.assertIn("rsi25_trend", SHADOW_STRATEGIES)
        self.assertNotIn("rsi25_trend", STRATEGIES)
        self.assertIn("trend_pullback_rsi_stoch", SHADOW_STRATEGIES)
        self.assertNotIn("trend_pullback_rsi_stoch", STRATEGIES)

    def test_reviewed_shadow_migration_preserves_old_evidence_and_starts_v2_now(self):
        identity = hashlib.sha256(account()["id"].encode()).hexdigest()
        advance(self.data, self.directory, identity)
        state = load(self.directory / "shadow-state.json")
        state["schema"] = 2
        state["code_sha256"] = SHADOW_V2_PREDECESSOR
        state["spy_start"] = state["strategies"]["trend_6_24"]["spy_start"]
        state["strategies"].pop("trend_pullback_rsi_stoch")
        for portfolio in state["strategies"].values():
            portfolio.pop("spy_start")
        pending = state["strategies"]["trend_6_24"]["pending"]
        self.assertIsNotNone(pending)
        atomic_json(self.directory / "shadow-state.json", state)
        with patch.dict("os.environ", {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}), \
                patch("bot.shadow._shadow_inputs", return_value=(account(), self.data)):
            report = migrate_shadow(ReadOnlyPaper(), self.directory)
        migrated = load(self.directory / "shadow-state.json")
        self.assertEqual(migrated["schema"], 3)
        self.assertEqual(migrated["code_sha256"], code_hash())
        self.assertNotIn("spy_start", migrated)
        self.assertIsNone(migrated["strategies"]["trend_6_24"]["pending"])
        v2 = migrated["strategies"]["trend_pullback_rsi_stoch"]
        self.assertEqual(v2["started_at"], str(self.data["SPY"].index[-1]))
        self.assertEqual(v2["fills"], 0)
        self.assertIn("spy_60pct_return_pct", report["strategies"]["trend_6_24"])
        journal = (self.directory / "journal.jsonl").read_text()
        self.assertIn("shadow_migration", journal)
        self.assertIn(pending["symbol"], journal)

    def test_reviewed_code_only_migration_preserves_v2_state(self):
        identity = hashlib.sha256(account()["id"].encode()).hexdigest()
        advance(self.data, self.directory, identity)
        state = load(self.directory / "shadow-state.json")
        previous = next(iter(SHADOW_CODE_PREDECESSORS))
        state["code_sha256"] = previous
        expected_last = state["last_bar"]
        expected = {
            name: (portfolio["sessions"], portfolio["fills"],
                   portfolio["round_trips"], portfolio["pending"])
            for name, portfolio in state["strategies"].items()
        }
        atomic_json(self.directory / "shadow-state.json", state)
        with patch.dict("os.environ", {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}), \
                patch("bot.shadow._shadow_inputs", return_value=(account(), self.data)):
            report = migrate_shadow(ReadOnlyPaper(), self.directory)
        migrated = load(self.directory / "shadow-state.json")
        self.assertEqual(migrated["code_sha256"], code_hash())
        self.assertEqual(migrated["last_bar"], expected_last)
        self.assertEqual({
            name: (portfolio["sessions"], portfolio["fills"],
                   portfolio["round_trips"], portfolio["pending"])
            for name, portfolio in migrated["strategies"].items()
        }, expected)
        self.assertEqual(report["bar"], expected_last)
        journal = (self.directory / "journal.jsonl").read_text()
        self.assertIn('"code_only": true', journal)
        self.assertIn(previous, journal)


if __name__ == "__main__":
    unittest.main()
