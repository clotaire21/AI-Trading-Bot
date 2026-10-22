from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd
from bot.alpaca import ExecutionPaper, SafetyError
from bot.runner import cycle, account_hash, execution_gate
from bot.state import atomic_json, code_hash, load
from helpers import frames, raw_bars, account


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.wall = datetime(2023, 1, 12, 18, 7, tzinfo=timezone.utc)
        self.clock = patch("bot.runner.datetime", wraps=datetime)
        self.mock_time = self.clock.start()
        self.mock_time.now.return_value = self.wall
        self.addCleanup(self.clock.stop)
        self.env = patch.dict(os.environ, {"PAPER_KILL_SWITCH": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = Mock(spec=ExecutionPaper)
        self.a = account()
        self.client.account.side_effect = lambda: self.a.copy()
        self.client.clock.side_effect = lambda: {"timestamp": self.wall.isoformat(), "is_open": True}
        self.client.positions.return_value = []
        self.client.orders.return_value = []
        data = frames(10, True)
        for f in data.values():
            f.loc[:, "Close"] = np.arange(len(f)) * .001 + 100
            f.loc[:, "High"] = f.Close + 1
        self.client.bars.return_value = raw_bars(data)
        self.client.submit.return_value = {"status": "accepted"}
        self.policy = {"orders_enabled": True, "strategy": "trend_6_24"}
        self.write_proof()

    def write_proof(self, **updates):
        proof = dict(at=self.wall.isoformat(), code_sha256=code_hash(), safety_tests_passed=True,
                     connection_passed=True, account_hash=account_hash(self.a), research_data_sha256="data")
        proof.update(updates)
        atomic_json(self.directory / "validation.json", proof)
        atomic_json(self.directory / "research.json", dict(research_gate_passed=True,
                    selected_on_validation="trend_6_24", data_sha256="data"))

    def test_only_one_order_and_no_duplicate_when_pending(self):
        cycle(self.client, self.directory, self.policy, True)
        self.assertEqual(self.client.submit.call_count, 1)
        state = load(self.directory / "state.json")
        self.assertIsNotNone(state["pending"])
        self.assertLessEqual(float(state["pending"]["qty"]) * float(state["pending"]["limit_price"]), 396)
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertEqual(self.client.submit.call_count, 1)

    def test_ambiguous_network_failure_never_retries(self):
        self.client.submit.side_effect = SafetyError("timeout")
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertEqual(self.client.submit.call_count, 1)
        self.assertIsNotNone(load(self.directory / "state.json")["pending"])

    def test_partial_fill_reconciled_before_next_order(self):
        cycle(self.client, self.directory, self.policy, True)
        intent = load(self.directory / "state.json")["pending"]
        self.a.update(cash="1900", equity="2000")
        self.client.positions.return_value = [dict(symbol="SPY", side="long", qty="1",
            market_value="100", avg_entry_price="100", current_price="100")]
        partial = dict(client_order_id=intent["client_id"], symbol="SPY", side="buy",
                       status="partially_filled", filled_qty="1", filled_avg_price="100")
        self.client.orders.side_effect = lambda status="open": [partial]
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertEqual(self.client.submit.call_count, 1)
        partial["status"] = "canceled"
        self.client.orders.side_effect = lambda status="open": [partial] if status == "all" else []
        cycle(self.client, self.directory, self.policy, True)
        self.assertEqual(self.client.submit.call_count, 1)  # same signal bar
        state = load(self.directory / "state.json")
        self.assertEqual(state["tracked_quantities"], {"SPY": "1"})
        self.assertAlmostEqual(state["modeled_cost"], .1)

    def test_stale_data_and_clock_and_pending_orders_fail_closed(self):
        old = frames(5, True)
        self.client.bars.return_value = raw_bars(old)
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertFalse(self.client.submit.called)
        self.client.clock.side_effect = lambda: {"timestamp": (self.wall - timedelta(hours=1)).isoformat(), "is_open": True}
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertFalse(self.client.submit.called)

    def test_100k_default_account_not_used(self):
        self.a.update(cash="100000", equity="100000")
        with self.assertRaises(SafetyError): cycle(self.client, self.directory, self.policy, True)
        self.assertFalse(self.client.submit.called)

    def test_kill_switch_code_change_expiry_and_failed_research(self):
        for changes in (dict(code_sha256="old"), dict(at="2022-01-01T00:00:00+00:00"),
                        dict(connection_passed=False), dict(safety_tests_passed=False), dict(account_hash="other")):
            self.write_proof(**changes)
            with self.assertRaises(SafetyError): execution_gate(self.directory, self.policy, self.a)
        self.write_proof()
        atomic_json(self.directory / "research.json", dict(research_gate_passed=False))
        with self.assertRaises(SafetyError): execution_gate(self.directory, self.policy, self.a)
        self.write_proof()
        with patch.dict(os.environ, {"PAPER_KILL_SWITCH": "true"}), self.assertRaises(SafetyError):
            execution_gate(self.directory, self.policy, self.a)

    def test_shadow_does_not_send_orders_even_when_policy_enabled(self):
        cycle(self.client, self.directory, self.policy, False)
        cycle(self.client, self.directory, self.policy, False)
        self.assertFalse(self.client.submit.called)
        self.assertEqual(load(self.directory / "state.json")["orders_today"], 0)


if __name__ == "__main__": unittest.main()
