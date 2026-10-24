import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bot.alpaca import ExecutionPaper, ReadOnlyPaper, SafetyError
from bot.audit import evaluate, run_locked_audit
from bot.canary import canary_cycle, canary_gate, validate_canary
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
            with patch.dict(os.environ, {"CANARY_KILL_SWITCH": "false"}):
                canary_gate(canary, enabled, account_data)
            atomic_json(main / "connection.json", {"account_hash": proof["account_hash"]})
            with self.assertRaisesRegex(SafetyError, "must differ"):
                validate_canary(client, canary, main)

    def test_canary_execution_rejects_read_only_client(self):
        with self.assertRaisesRegex(SafetyError, "PAPER execution"):
            canary_cycle(Mock(spec=ReadOnlyPaper), "unused", {})


if __name__ == "__main__":
    unittest.main()
