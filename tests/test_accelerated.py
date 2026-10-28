import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bot.alpaca import ExecutionPaper, ReadOnlyPaper, SafetyError
from bot.audit import evaluate, run_locked_audit
from bot.canary import (CANARY_UPGRADE_PREDECESSORS, canary_cycle, canary_gate,
                        migrate_canary, validate_canary)
from bot.runner import account_hash
from bot.state import atomic_json, code_hash, load
from helpers import account, frames, raw_bars


class AcceleratedAuditTests(unittest.TestCase):
    def test_lock_is_durable_before_download_and_write_client_is_rejected(self):
        client = object.__new__(ReadOnlyPaper)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)

            def fail_after_lock(*_):
                self.assertTrue((path / "accelerated-audit-lock.json").exists())
                raise SafetyError("data unavailable")

            client.bars = Mock(side_effect=fail_after_lock)
            with self.assertRaisesRegex(SafetyError, "data unavailable"):
                run_locked_audit(client, path)
            self.assertEqual(load(path / "accelerated-audit-lock.json")["attempts"], 1)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(SafetyError, "read-only"):
            run_locked_audit(Mock(spec=ExecutionPaper), directory)

    def test_diagnostic_covers_all_candidates_and_cannot_promote(self):
        plan = json.loads(Path("accelerated-audit-plan.json").read_text())
        report = evaluate(frames(300), plan, {
            "locked_at": "2026-10-24T00:00:00+00:00",
            "plan_sha256": "plan", "code_sha256": code_hash(),
            "input_payload_sha256": "input",
        })
        self.assertEqual(set(report["leaderboard"]), set(plan["strategies"]))
        self.assertFalse(report["eligible_for_execution"])
        self.assertTrue(all("below_750_sessions" in item["blockers"]
                            for item in report["strategies"].values()))


class CanaryTests(unittest.TestCase):
    def client(self, identity="canary-paper-account"):
        client = object.__new__(ReadOnlyPaper)
        canary = account()
        canary["id"] = identity
        client.account = Mock(return_value=canary)
        client.positions = Mock(return_value=[])
        client.orders = Mock(return_value=[])
        client.clock = Mock(return_value={"is_open": True})
        client.asset = Mock(return_value=dict(tradable=True, fractionable=True, status="active"))
        client.bars = Mock(return_value=raw_bars(frames(15)))
        return client, canary

    def test_canary_requires_distinct_account_and_disabled_policy_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            main, canary = root / "runtime", root / "canary"
            atomic_json(main / "connection.json", {"account_hash": "a" * 64})
            client, account_data = self.client()
            proof = validate_canary(client, canary, main)
            self.assertFalse(proof["performance_evidence"])
            disabled = {"mode": "operational_canary_only", "orders_enabled": False,
                        "strategy": "trend_6_24"}
            with patch.dict(os.environ, {"CANARY_KILL_SWITCH": "false"}), \
                    self.assertRaisesRegex(SafetyError, "policy disabled"):
                canary_gate(canary, disabled, account_data)
            enabled = {**disabled, "orders_enabled": True}
            enabled["entries_enabled"] = True
            with patch.dict(os.environ, {"CANARY_KILL_SWITCH": "false"}):
                canary_gate(canary, enabled, account_data)
            drain = {**enabled, "entries_enabled": False}
            with patch.dict(os.environ, {"CANARY_KILL_SWITCH": "false"}):
                canary_gate(canary, drain, account_data)
            atomic_json(main / "connection.json", {"account_hash": proof["account_hash"]})
            with self.assertRaisesRegex(SafetyError, "must differ"):
                validate_canary(client, canary, main)

    def test_canary_execution_rejects_read_only_client(self):
        with self.assertRaisesRegex(SafetyError, "PAPER execution"):
            canary_cycle(Mock(spec=ReadOnlyPaper), "unused", {})

    def test_used_canary_migrates_only_from_reviewed_reconciled_predecessor(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            main, canary = root / "runtime", root / "canary"
            client, account_data = self.client()
            account_data.update(cash="1600", equity="2000")
            position = dict(symbol="IWM", side="long", qty="1.4", market_value="400",
                            avg_entry_price="285", current_price=str(400 / 1.4))
            client.positions.return_value = [position]
            identity = account_hash(account_data)
            main_hash = "a" * 64
            predecessor = next(iter(CANARY_UPGRADE_PREDECESSORS))
            atomic_json(main / "connection.json", {"account_hash": main_hash})
            atomic_json(canary / "state.json", {
                "account_hash": identity, "tracked_quantities": {"IWM": "1.4"},
                "tracked_cash": 1600, "pending": None,
            })
            atomic_json(canary / "canary-validation.json", {
                "schema": 1, "at": datetime.now(timezone.utc).isoformat(),
                "code_sha256": predecessor, "safety_tests_passed": True,
                "connection_passed": True, "account_hash": identity,
                "main_account_hash": main_hash, "mode": "operational_canary_only",
                "strategy": "trend_6_24", "performance_evidence": False,
            })
            migrated = migrate_canary(client, canary, main)
            self.assertEqual(migrated["code_sha256"], code_hash())
            self.assertEqual(migrated["migrated_from"], predecessor)
            migrated["code_sha256"] = "b" * 64
            atomic_json(canary / "canary-validation.json", migrated)
            with self.assertRaisesRegex(SafetyError, "predecessor mismatch"):
                migrate_canary(client, canary, main)

    def test_canary_migration_reconciles_terminal_pending_fill(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            main, canary = root / "runtime", root / "canary"
            client, account_data = self.client()
            account_data.update(cash="1500", equity="2000")
            client.positions.return_value = [
                dict(symbol="IWM", side="long", qty="1.4", market_value="400",
                     avg_entry_price="285", current_price=str(400 / 1.4)),
                dict(symbol="SPY", side="long", qty="1", market_value="100",
                     avg_entry_price="100", current_price="100"),
            ]
            pending = {"symbol": "SPY", "side": "buy", "qty": "1",
                       "limit_price": "101", "client_id": "lab-" + "1" * 32,
                       "bar": "2026-10-27 15:00:00+00:00"}
            filled = {"symbol": "SPY", "side": "buy", "status": "filled",
                      "client_order_id": pending["client_id"], "filled_qty": "1",
                      "filled_avg_price": "100"}
            client.orders.side_effect = lambda status="open": [] if status == "open" else [filled]
            identity = account_hash(account_data)
            main_hash = "a" * 64
            predecessor = next(iter(CANARY_UPGRADE_PREDECESSORS))
            atomic_json(main / "connection.json", {"account_hash": main_hash})
            atomic_json(canary / "state.json", {
                "account_hash": identity, "tracked_quantities": {"IWM": "1.4"},
                "tracked_cash": 1600, "pending": pending, "modeled_cost": 0,
                "entries": {"IWM": "2026-10-26 17:00:00+00:00"},
            })
            atomic_json(canary / "canary-validation.json", {
                "schema": 1, "at": datetime.now(timezone.utc).isoformat(),
                "code_sha256": predecessor, "safety_tests_passed": True,
                "connection_passed": True, "account_hash": identity,
                "main_account_hash": main_hash, "mode": "operational_canary_only",
                "strategy": "trend_6_24", "performance_evidence": False,
            })
            migrate_canary(client, canary, main)
            state = load(canary / "state.json")
            self.assertIsNone(state["pending"])
            self.assertEqual(state["tracked_quantities"], {"IWM": "1.4", "SPY": "1"})
            self.assertEqual(state["tracked_cash"], 1500)
            self.assertEqual(state["entries"]["SPY"], pending["bar"])
            self.assertAlmostEqual(state["modeled_cost"], .1)
            self.assertIn("canary_migration", (canary / "journal.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
