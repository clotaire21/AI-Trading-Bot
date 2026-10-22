from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock, MagicMock
from bot.alpaca import ReadOnlyPaper, ExecutionPaper, SafetyError, NoRedirect
from bot.config import PAPER_URL, DATA_URL
from bot.risk import account_values, make_order, Order
from bot.runner import probe, execution_gate, cycle
from bot.state import append_event, code_hash, atomic_json
from helpers import account, frames, raw_bars


class TransportSafety(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_secrets(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SafetyError):
            ReadOnlyPaper()

    def test_live_and_alternative_endpoints_rejected(self):
        for url in ("https://api.alpaca.markets", "http://paper-api.alpaca.markets", "https://evil.test"):
            with patch.dict(os.environ, {"APCA_API_BASE_URL": url}), self.assertRaises(SafetyError):
                ReadOnlyPaper()
        client = ReadOnlyPaper()
        with self.assertRaises(SafetyError):
            client._request("GET", "https://api.alpaca.markets", "/v2/account")

    def test_read_only_cannot_submit_or_delete(self):
        client = ReadOnlyPaper()
        self.assertFalse(hasattr(client, "submit"))
        for method in ("POST", "DELETE", "PATCH"):
            with self.assertRaises(SafetyError):
                client._request(method, PAPER_URL, "/v2/orders")

    def test_paid_data_forbidden(self):
        with self.assertRaises(SafetyError):
            ReadOnlyPaper()._request("GET", DATA_URL, "/v2/stocks/bars", {"feed": "sip"})

    def test_redirect_refused(self):
        with self.assertRaises(SafetyError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://api.alpaca.markets")

    def test_limit_payload_paper_only(self):
        client = ExecutionPaper()
        client._opener = MagicMock()
        client._opener.open.return_value.__enter__.return_value.read.return_value = b'{"status":"accepted"}'
        order = make_order("SPY", "buy", 550, 396, "bar", "account", "trend_6_24")
        client.submit(order)
        request = client._opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, PAPER_URL + "/v2/orders")
        self.assertEqual(body["type"], "limit")
        self.assertFalse(body["extended_hours"])
        self.assertLessEqual(Decimal(body["qty"]) * Decimal(body["limit_price"]), 396)

    def test_cli_safe_valueerror_diagnostics(self):
        from unittest.mock import patch
        from bot.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            for message, expected in (
                ("Missing or misaligned cross-symbol bars", "Missing or misaligned cross-symbol bars"),
                ("private credential data", "Unclassified data validation error"),
            ):
                with patch("sys.argv", ["bot", "research", "--state-dir", directory]), \
                     patch("bot.__main__.ReadOnlyPaper") as client_factory, \
                     patch("bot.__main__.append_event") as append, \
                     patch("bot.__main__.datetime") as dt:
                    dt.now.return_value = __import__("datetime").datetime(2026, 10, 22, tzinfo=__import__("datetime").timezone.utc)
                    client_factory.return_value.bars.side_effect = ValueError(message)
                    self.assertEqual(main(), 1)
                    self.assertEqual(append.call_args.args[1]["reason"], expected)

    def test_pagination(self):
        client = ReadOnlyPaper()
        client._request = Mock(side_effect=[{"bars": {"SPY": [{"t": "2026-01-05T15:00:00Z", "x": 1}]}, "next_page_token": "a"},
                                           {"bars": {"QQQ": [{"t": "2026-01-05T15:00:00Z", "x": 2}]}, "next_page_token": None}])
        bars = client.bars("2026-01-01T00:00:00Z", "2026-01-10T00:00:00Z")
        self.assertEqual(len(bars["SPY"]), 1)
        self.assertEqual(len(bars["QQQ"]), 1)
        self.assertEqual(client._request.call_args.args[3]["page_token"], "a")

    def test_long_history_uses_complete_bounded_windows(self):
        client = ReadOnlyPaper()
        calls = []
        def pages(method, base, path, params):
            calls.append(params.copy())
            if params["start"].startswith("2026-01-01"):
                return {"bars": {"SPY": [{"t": "2026-01-15T15:00:00Z", "x": 1}]},
                        "next_page_token": "another"} if "page_token" not in params else {
                        "bars": {"QQQ": [{"t": "2026-01-16T15:00:00Z", "x": 2}]}}
            return {"bars": {"IWM": [{"t": "2026-02-05T15:00:00Z", "x": 3}]}}
        client._request = Mock(side_effect=pages)
        bars = client.bars("2026-01-01T00:00:00Z", "2026-02-10T00:00:00Z")
        self.assertEqual([len(bars[s]) for s in ("SPY", "QQQ", "IWM")], [1, 1, 1])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["end"], calls[2]["start"])
        self.assertEqual(calls[1]["page_token"], "another")
        self.assertNotIn("page_token", calls[2])

    def test_boundary_duplicates_are_not_double_counted(self):
        client = ReadOnlyPaper()
        row = {"t": "2026-01-31T00:00:00Z", "c": 1}
        client._request = Mock(return_value={"bars": {"SPY": [row]}})
        bars = client.bars("2026-01-01T00:00:00Z", "2026-02-10T00:00:00Z")
        self.assertEqual(bars["SPY"], [row])
        client._request = Mock(side_effect=[
            {"bars": {"SPY": [row]}},
            {"bars": {"SPY": [{**row, "c": 2}]}}])
        with self.assertRaisesRegex(SafetyError, "Conflicting duplicate"):
            client.bars("2026-01-01T00:00:00Z", "2026-02-10T00:00:00Z")

    def test_repeated_page_token_fails_closed(self):
        client = ReadOnlyPaper()
        client._request = Mock(return_value={"bars": {}, "next_page_token": "same"})
        with self.assertRaisesRegex(SafetyError, "repeated data pagination"):
            client.bars("2026-01-01T00:00:00Z", "2026-01-10T00:00:00Z")
        self.assertEqual(client._request.call_count, 2)

    def test_pagination_cap_does_not_return_partial_history(self):
        client = ReadOnlyPaper()
        n = iter(range(200))
        client._request = Mock(side_effect=lambda *args: {
            "bars": {}, "next_page_token": str(next(n))})
        with self.assertRaisesRegex(SafetyError, "limit reached within 30-day window"):
            client.bars("2026-01-01T00:00:00Z", "2026-01-10T00:00:00Z")
        self.assertEqual(client._request.call_count, 100)


class RiskSafety(unittest.TestCase):
    def test_borrowing_blocked_even_if_buying_power_large(self):
        a = account()
        a.update(cash="-1", buying_power="100000")
        with self.assertRaises(SafetyError): account_values(a, [])

    def test_nan_and_account_mismatch(self):
        for value in ("NaN", "Infinity", "-10"):
            a = account()
            a["equity"] = value
            with self.assertRaises(SafetyError): account_values(a, [])
        a = account()
        a["equity"] = "3000"
        with self.assertRaises(SafetyError): account_values(a, [])

    def test_short_unknown_positions_blocked(self):
        for p in (dict(symbol="SPY", side="short"), dict(symbol="AAPL", side="long")):
            with self.assertRaises(SafetyError): account_values(account(), [p])

    def test_order_id_deterministic_and_size_capped(self):
        o = make_order("SPY", "buy", 600, 396, "bar", "acct", "trend_6_24")
        self.assertEqual(o, make_order("SPY", "buy", 600, 396, "bar", "acct", "trend_6_24"))
        self.assertNotEqual(o.client_id, make_order("SPY", "buy", 600, 396, "next", "acct", "trend_6_24").client_id)
        with self.assertRaises(SafetyError): make_order("SPY", "buy", 600, 1000, "bar", "acct", "trend_6_24")

    def test_exit_keeps_fractional_fill_precision(self):
        order = make_order("SPY", "sell", 600, "0.000000123", "bar", "acct", "trend_6_24")
        self.assertEqual(order.qty, Decimal("0.000000123"))

    def test_execution_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SafetyError): execution_gate(directory, {"orders_enabled": False}, account())
            with patch.dict(os.environ, {"PAPER_KILL_SWITCH": "false"}), self.assertRaises(SafetyError):
                execution_gate(directory, {"orders_enabled": True, "strategy": "trend_6_24"}, account())

    def test_journal_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            append_event(directory, {"event": "first"})
            append_event(directory, {"event": "second"})
            path = Path(directory) / "journal.jsonl"
            path.write_text(path.read_text().replace("first", "fake"))
            with self.assertRaises(SafetyError): append_event(directory, {"event": "third"})

    def test_probe_only_reads_and_hides_identity(self):
        client = Mock(spec=ReadOnlyPaper)
        client.account.return_value = account()
        client.positions.return_value = []
        client.orders.return_value = []
        client.clock.return_value = {"is_open": True}
        client.asset.return_value = dict(tradable=True, fractionable=True, status="active")
        client.bars.return_value = raw_bars(frames(15))
        with tempfile.TemporaryDirectory() as directory:
            result = probe(client, directory)
        self.assertTrue(result["read_only"])
        self.assertTrue(result["dedicated_2000_account_ready"])
        self.assertNotIn("test-paper-account", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
