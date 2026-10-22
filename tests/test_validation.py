from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from bot.alpaca import ReadOnlyPaper, SafetyError
from bot.runner import account_hash
from bot.state import code_hash, atomic_json, load
from bot.validation import renew
from bot.provenance import payload_hash
from helpers import account


class RenewalTests(unittest.TestCase):
    @patch("bot.validation.subprocess.run")
    def test_renewal_requires_initial_evidence_and_keeps_research_unchanged(self, tests):
        client = Mock(spec=ReadOnlyPaper)
        client.account.return_value = account()
        client.positions.return_value = []
        client.asset.return_value = dict(tradable=True, fractionable=True, status="active")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            research = dict(schema=2, code_sha256=code_hash(), data_origin={"kind": "alpaca_iex_download"},
                            data_sha256="data", research_gate_passed=True)
            proof = dict(at="2026-10-22T12:00:00+00:00", code_sha256=code_hash(), connection_passed=True,
                         safety_tests_passed=True, account_hash=account_hash(account()), research_data_sha256="data",
                         research_sha256=payload_hash(research))
            atomic_json(path / "validation.json", proof)
            atomic_json(path / "research.json", research)
            atomic_json(path / "state.json", dict(account_hash=account_hash(account())))
            original = (path / "research.json").read_bytes()
            renewed = renew(client, path)
            self.assertEqual(renewed["initial_validated_at"], proof["at"])
            self.assertEqual((path / "research.json").read_bytes(), original)
            self.assertEqual(tests.call_count, 1)
            proof["code_sha256"] = "changed"
            atomic_json(path / "validation.json", proof)
            with self.assertRaises(SafetyError): renew(client, path)
            self.assertEqual(load(path / "validation.json")["code_sha256"], "changed")
        self.assertFalse(hasattr(client, "submit"))
