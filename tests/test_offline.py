from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from bot.alpaca import SafetyError
from bot.data import validate
from bot.offline import scenario, selfcheck, SCENARIOS
from bot.provenance import payload_hash, replay_origin, check_research_evidence
from bot.state import atomic_json, code_hash


class OfflineTests(unittest.TestCase):
    def test_scenarios_reproducible_and_valid(self):
        for name in SCENARIOS:
            a, b = scenario(name), scenario(name)
            for symbol in a:
                pd.testing.assert_frame_equal(a[symbol], b[symbol])
                validate(a[symbol])

    def test_non_hourly_bars_rejected(self):
        frame = scenario("flat")["SPY"]
        frame.index += pd.Timedelta(minutes=1)
        with self.assertRaises(ValueError): validate(frame)

    @patch("socket.socket", side_effect=AssertionError("network forbidden"))
    @patch("bot.alpaca.ReadOnlyPaper.__init__", side_effect=AssertionError("broker forbidden"))
    def test_full_selfcheck_works_offline_and_cannot_promote(self, broker, network):
        with tempfile.TemporaryDirectory() as directory:
            report = selfcheck(directory)
            self.assertEqual(len(report["cases"]), 15)
            self.assertEqual(report["orders_submitted"], 0)
            self.assertFalse(report["execution_authorized"])
            self.assertFalse(report["chronological_pipeline"]["research_gate_passed"])
            self.assertTrue((Path(directory) / "selfcheck.md").exists())
            self.assertTrue(any(c["halted"] for c in report["cases"] if c["scenario"] == "crash"))
        broker.assert_not_called()
        network.assert_not_called()

    def test_unverified_local_input_remains_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            origin = replay_origin({"SPY": []}, Path(directory) / "input.json")
            self.assertEqual(origin["kind"], "unverified_local")

    def test_modified_input_cannot_reuse_alpaca_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            raw = {"SPY": [{"c": 100}]}
            manifest = {"source": "alpaca_iex_download", "feed": "iex", "adjustment": "all",
                        "timeframe": "1Hour", "payload_sha256": payload_hash(raw),
                        "downloaded_at": "2026-10-22T00:00:00+00:00"}
            atomic_json(path / "research-manifest.json", manifest)
            self.assertEqual(replay_origin(raw, path / "input.json")["kind"], "alpaca_iex_replay")
            raw["SPY"][0]["c"] = 200
            with self.assertRaises(SafetyError): replay_origin(raw, path / "input.json")

    def test_synthetic_altered_or_old_report_rejected_by_execution(self):
        report = dict(schema=2, code_sha256=code_hash(), data_sha256="bars",
                      data_origin={"kind": "synthetic"}, research_gate_passed=True)
        proof = dict(research_data_sha256="bars", research_sha256=payload_hash(report))
        with self.assertRaises(SafetyError): check_research_evidence(report, proof)
        report["data_origin"]["kind"] = "alpaca_iex_download"
        proof["research_sha256"] = payload_hash(report)
        check_research_evidence(report, proof)
        report["research_gate_passed"] = False
        with self.assertRaises(SafetyError): check_research_evidence(report, proof)
