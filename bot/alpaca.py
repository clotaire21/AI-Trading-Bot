"""Small allowlisted client; redirects and implicit retries are forbidden.

ReadOnlyPaper has no write method. The execution subclass only accepts a
validated order object; the production broker domain is absent from the code.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .config import PAPER_URL, DATA_URL, SYMBOLS


class SafetyError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafetyError("HTTP redirect refused")


class ReadOnlyPaper:
    def __init__(self):
        # Refuse conflicting SDK/environment settings, even though never used.
        for name in ("APCA_API_BASE_URL", "ALPACA_BASE_URL", "ALPACA_API_BASE_URL"):
            if os.environ.get(name, PAPER_URL).rstrip("/") != PAPER_URL:
                raise SafetyError("Conflicting broker endpoint")
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise SafetyError("Missing Alpaca paper secrets")
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                         "Content-Type": "application/json"}
        self._opener = build_opener(NoRedirect())

    def _request(self, method, base, path, params=None, body=None):
        allowed = (method == "GET" and base == PAPER_URL and
                   (path in ("/v2/account", "/v2/clock", "/v2/positions", "/v2/orders",
                             "/v2/orders:by_client_order_id") or
                    path in tuple("/v2/assets/" + s for s in SYMBOLS)))
        allowed |= method == "GET" and base == DATA_URL and path == "/v2/stocks/bars"
        allowed |= (method == "POST" and base == PAPER_URL and path == "/v2/orders"
                    and type(self) is ExecutionPaper)
        if not allowed:
            raise SafetyError("HTTP operation outside allowlist")
        if base == DATA_URL and (params or {}).get("feed") != "iex":
            raise SafetyError("Only free IEX data allowed")
        url = base + path + (("?" + urlencode(params)) if params else "")
        req = Request(url, data=json.dumps(body).encode() if body else None,
                      headers=self._headers, method=method)
        try:
            with self._opener.open(req, timeout=25) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never log server response bodies or request headers/credentials.
            raise SafetyError(f"Alpaca HTTP {exc.code}; no retry") from None
        except (URLError, TimeoutError, ValueError):
            raise SafetyError("Alpaca transport/JSON failure; no retry") from None

    def account(self):
        return self._request("GET", PAPER_URL, "/v2/account")

    def clock(self):
        return self._request("GET", PAPER_URL, "/v2/clock")

    def positions(self):
        return self._request("GET", PAPER_URL, "/v2/positions")

    def orders(self, status="open"):
        return self._request("GET", PAPER_URL, "/v2/orders",
                             {"status": status, "limit": 500, "direction": "desc"})

    def asset(self, symbol):
        return self._request("GET", PAPER_URL, "/v2/assets/" + symbol)

    def bars(self, start, end, adjustment="raw"):
        if adjustment not in ("raw", "all"):
            raise SafetyError("Unknown adjustment")
        try:
            first = datetime.fromisoformat(start.replace("Z", "+00:00"))
            last = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if first.utcoffset() is None or last.utcoffset() is None or first >= last:
                raise ValueError("Invalid time range")
        except (TypeError, AttributeError, ValueError):
            raise SafetyError("Invalid UTC-aware data time range") from None
        first, last = first.astimezone(timezone.utc), last.astimezone(timezone.utc)
        result = {s: [] for s in SYMBOLS}
        # Bound each request window, rather than permitting unlimited pagination
        # across several years of multi-symbol history. Each window must finish
        # pagination completely; no incomplete research dataset is returned.
        cursor = first
        while cursor < last:
            stop = min(cursor + timedelta(days=30), last)
            token, seen = None, set()
            for _ in range(100):
                params = dict(symbols=",".join(SYMBOLS), timeframe="1Hour",
                              start=cursor.isoformat(), end=stop.isoformat(),
                              feed="iex", adjustment=adjustment, limit=10000, sort="asc")
                if token:
                    params["page_token"] = token
                page = self._request("GET", DATA_URL, "/v2/stocks/bars", params)
                if not isinstance(page, dict) or not isinstance(page.get("bars", {}), dict):
                    raise SafetyError("Invalid market data pagination response")
                for symbol in SYMBOLS:
                    rows = page.get("bars", {}).get(symbol, [])
                    if not isinstance(rows, list):
                        raise SafetyError("Invalid market data bars")
                    result[symbol].extend(rows)
                token = page.get("next_page_token")
                if not token:
                    break
                if not isinstance(token, str) or token in seen:
                    raise SafetyError("Invalid or repeated data pagination token")
                seen.add(token)
            else:
                raise SafetyError("Data pagination limit reached within 30-day window")
            cursor = stop
        # Adjacent windows can share a boundary bar depending on provider
        # inclusivity. Deduplicate identical timestamps only when identical data;
        # never silently discard conflicting values.
        for symbol in SYMBOLS:
            unique = {}
            for row in result[symbol]:
                if not isinstance(row, dict) or not isinstance(row.get("t"), str):
                    raise SafetyError("Invalid market data bar")
                timestamp = row["t"]
                if timestamp in unique and unique[timestamp] != row:
                    raise SafetyError("Conflicting duplicate market data bar")
                unique[timestamp] = row
            result[symbol] = list(unique.values())
        return result


class ExecutionPaper(ReadOnlyPaper):
    def submit(self, order):
        from .risk import Order
        if type(order) is not Order or not re.fullmatch(r"lab-[a-f0-9]{32}", order.client_id):
            raise SafetyError("Validated order required")
        order.validate()
        return self._request("POST", PAPER_URL, "/v2/orders", body={
            "symbol": order.symbol, "side": order.side, "qty": str(order.qty),
            "type": "limit", "limit_price": str(order.limit_price),
            "time_in_force": "day", "extended_hours": False,
            "client_order_id": order.client_id})
