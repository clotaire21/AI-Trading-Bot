from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import hashlib
import math
from .alpaca import SafetyError
from .config import LIMITS, SYMBOLS


def number(x):
    try:
        n = float(x)
    except (TypeError, ValueError):
        raise SafetyError("Invalid numeric broker field") from None
    if not math.isfinite(n):
        raise SafetyError("Nonfinite broker field")
    return n


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    qty: Decimal
    limit_price: Decimal
    client_id: str

    def validate(self):
        if self.symbol not in SYMBOLS or self.side not in ("buy", "sell"):
            raise SafetyError("Order outside universe")
        if not self.qty.is_finite() or not self.limit_price.is_finite() or min(self.qty, self.limit_price) <= 0:
            raise SafetyError("Invalid order quantity/limit")
        if self.qty.as_tuple().exponent < (-6 if self.side == "buy" else -9) or self.limit_price.as_tuple().exponent < -2:
            raise SafetyError("Invalid precision")
        if self.side == "buy" and self.qty * self.limit_price > Decimal("400"):
            raise SafetyError("Absolute position budget exceeded")


def account_values(account, positions):
    for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if account.get(flag, False):
            raise SafetyError("Account trading blocked")
    if account.get("status") != "ACTIVE" or account.get("currency") != "USD":
        raise SafetyError("Account must be active USD")
    cash, equity = number(account["cash"]), number(account["equity"])
    if cash < 0 or equity <= 0 or number(account.get("short_market_value", 0)) != 0:
        raise SafetyError("Borrowing/short exposure detected")
    seen = set()
    gross = 0.0
    for p in positions:
        symbol = p["symbol"]
        if symbol not in SYMBOLS or symbol in seen or p.get("side") != "long":
            raise SafetyError("Unexpected position")
        seen.add(symbol)
        if number(p["qty"]) <= 0 or number(p["market_value"]) <= 0 or number(p["avg_entry_price"]) <= 0:
            raise SafetyError("Invalid long position")
        gross += number(p["market_value"])
    if abs(cash + gross - equity) > 2.0:
        raise SafetyError("Account reconciliation failed")
    return cash, equity, gross


def make_order(symbol, side, price, budget_or_qty, bar, account_hash, strategy):
    # Limit orders cap entry expenditure. No stale-market-order slippage surprise.
    limit = (Decimal(str(price)) * Decimal("1.001" if side == "buy" else "0.999"))
    limit = limit.quantize(Decimal("0.01"), rounding=ROUND_UP if side == "buy" else ROUND_DOWN)
    qty = (Decimal(str(budget_or_qty)) / limit if side == "buy" else Decimal(str(budget_or_qty)))
    qty = qty.quantize(Decimal("0.000001" if side == "buy" else "0.000000001"), rounding=ROUND_DOWN)
    identity = f"{account_hash}:{strategy}:{bar}:{symbol}:{side}"
    client_id = "lab-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    order = Order(symbol, side, qty, limit, client_id)
    order.validate()
    return order
