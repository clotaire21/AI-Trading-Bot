"""Forward-only virtual portfolios; this module has no broker write path.

Each strategy starts with its own modeled USD 2,000 account. A signal observed
at one completed bar is filled at the next observed bar open, using the same
fee/slippage assumptions as the research backtest. Results are durable but can
never authorize paper orders: only the separate research/validation gate can.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import math
import pandas as pd

from .alpaca import ReadOnlyPaper, SafetyError
from .config import LIMITS, SYMBOLS
from .data import align, frames_from_bars
from .risk import account_values
from .state import append_event, atomic_json, code_hash, load, now
from .strategies import SHADOW_STRATEGIES, SHADOW_WARMUP, signals


STATE_FILE = "shadow-state.json"
REPORT_FILE = "shadow-performance.json"
SHADOW_SCHEMA = 3
SHADOW_MIGRATION_PREDECESSORS = frozenset({
    "31e357916a0bbb7df545fc07ff8296952474e5ba5c981ee5d8d17288f7440504",
})


def _account_hash(account):
    return hashlib.sha256(account["id"].encode()).hexdigest()


def _value(portfolio, frames, i, field):
    return portfolio["cash"] + sum(
        position["qty"] * float(frames[symbol].iloc[i][field])
        for symbol, position in portfolio["positions"].items()
    )


def _new_portfolio(timestamp, spy_start):
    return {
        "started_at": str(timestamp), "cash": LIMITS.capital, "equity": LIMITS.capital,
        "spy_start": float(spy_start),
        "positions": {}, "pending": None, "peak": LIMITS.capital,
        "max_drawdown": 0.0, "day": None, "day_start": LIMITS.capital,
        "daily_halt": False, "halted": False, "orders_today": 0,
        "sessions": 0, "fills": 0, "round_trips": 0, "modeled_cost": 0.0,
    }


def _fill_pending(portfolio, frames, i, strategy):
    pending = portfolio["pending"]
    portfolio["pending"] = None
    if not pending:
        return None, None
    symbol, side = pending["symbol"], pending["side"]
    reference = float(frames[symbol].Open.iloc[i])
    fee = LIMITS.fee_bps / 10000
    slip = LIMITS.slippage_bps / 10000
    if side == "sell":
        if symbol not in portfolio["positions"]:
            raise SafetyError("Shadow sell missing virtual position")
        position = portfolio["positions"].pop(symbol)
        price = reference * (1 - slip)
        proceeds = position["qty"] * price * (1 - fee)
        cost = position["qty"] * (reference - price + price * fee)
        portfolio["cash"] += proceeds
        portfolio["round_trips"] += 1
        exited = symbol
        qty = position["qty"]
    elif side == "buy":
        if symbol in portfolio["positions"]:
            raise SafetyError("Shadow duplicate virtual position")
        if portfolio["halted"] or portfolio["daily_halt"] or portfolio["orders_today"] >= LIMITS.max_orders_day:
            return None, None
        opening_equity = _value(portfolio, frames, i, "Open")
        base = min(LIMITS.capital, opening_equity)
        gross = opening_equity - portfolio["cash"]
        budget = max(0.0, min(base * LIMITS.position,
                              base * LIMITS.exposure - gross,
                              portfolio["cash"] - base * LIMITS.reserve)) * .99
        price = reference * (1 + slip)
        qty = budget / (price * (1 + fee)) if price > 0 else 0
        if budget < 5 or qty <= 0:
            return None, None
        cost = qty * (price - reference + price * fee)
        portfolio["cash"] -= qty * price * (1 + fee)
        portfolio["positions"][symbol] = {
            "qty": qty, "entry": price, "bars_held": 0,
        }
        exited = None
    else:
        raise SafetyError("Invalid shadow pending side")
    portfolio["orders_today"] += 1
    portfolio["fills"] += 1
    portfolio["modeled_cost"] += cost
    if portfolio["cash"] < -0.000001:
        raise SafetyError("Shadow leverage detected")
    return {
        "strategy": strategy, "symbol": symbol, "side": side, "qty": qty,
        "price": price, "cost": cost, "reason": pending["reason"],
        "signal_bar": pending["signal_bar"],
    }, exited


def _choose_pending(portfolio, frames, i, strategy, exited):
    index = frames[SYMBOLS[0]].index
    close_equity = _value(portfolio, frames, i, "Close")
    base = min(LIMITS.capital, close_equity)
    gross = close_equity - portfolio["cash"]
    sig = {symbol: signals(frames[symbol], strategy).iloc[i] for symbol in SYMBOLS}
    for symbol, position in portfolio["positions"].items():
        close = float(frames[symbol].Close.iloc[i])
        market_value = position["qty"] * close
        reason = (
            "drawdown_halt" if portfolio["halted"] else
            "daily_halt" if portfolio["daily_halt"] else
            "position_cap" if market_value > base * LIMITS.position + 1 or gross > base * LIMITS.exposure + 1 else
            "stop_loss" if close <= position["entry"] * (1 - LIMITS.stop_loss) else
            "max_hold" if position["bars_held"] >= LIMITS.max_hold_bars else
            "signal_exit" if bool(sig[symbol].exit) else None
        )
        if reason:
            return {"symbol": symbol, "side": "sell", "reason": reason,
                    "signal_bar": str(index[i])}
    if not (portfolio["halted"] or portfolio["daily_halt"]):
        for symbol in SYMBOLS:
            if (symbol not in portfolio["positions"] and symbol != exited and
                    bool(sig[symbol].enter)):
                return {"symbol": symbol, "side": "buy", "reason": "signal_entry",
                        "signal_bar": str(index[i])}
    return None


def _process_bar(state, frames, i):
    index = frames[SYMBOLS[0]].index
    timestamp = index[i]
    fills = []
    for strategy in SHADOW_STRATEGIES:
        portfolio = state["strategies"][strategy]
        day = timestamp.tz_convert("America/New_York").date().isoformat()
        if day != portfolio["day"]:
            portfolio.update(day=day, day_start=portfolio["equity"],
                             daily_halt=False, orders_today=0)
            portfolio["sessions"] += 1
        for position in portfolio["positions"].values():
            position["bars_held"] += 1
        opening_equity = _value(portfolio, frames, i, "Open")
        portfolio["halted"] |= opening_equity <= portfolio["peak"] * (1 - LIMITS.drawdown)
        portfolio["daily_halt"] |= opening_equity <= portfolio["day_start"] * (1 - LIMITS.daily_loss)
        fill, exited = _fill_pending(portfolio, frames, i, strategy)
        if fill:
            fill["timestamp"] = str(timestamp)
            fills.append(fill)
        close_equity = _value(portfolio, frames, i, "Close")
        portfolio["equity"] = close_equity
        portfolio["peak"] = max(portfolio["peak"], close_equity)
        portfolio["max_drawdown"] = min(
            portfolio["max_drawdown"], close_equity / portfolio["peak"] - 1)
        portfolio["halted"] |= close_equity <= portfolio["peak"] * (1 - LIMITS.drawdown)
        portfolio["daily_halt"] |= close_equity <= portfolio["day_start"] * (1 - LIMITS.daily_loss)
        portfolio["pending"] = _choose_pending(portfolio, frames, i, strategy, exited)
    state["last_bar"] = str(timestamp)
    return fills


def _report(state, frames):
    index = frames[SYMBOLS[0]].index
    latest = pd.Timestamp(state["last_bar"])
    i = index.get_loc(latest)
    current_spy = float(frames["SPY"].Close.iloc[i])
    friction = (LIMITS.fee_bps + LIMITS.slippage_bps) / 10000
    strategies = {}
    for name in SHADOW_STRATEGIES:
        portfolio = state["strategies"][name]
        units = LIMITS.capital * LIMITS.exposure / (portfolio["spy_start"] * (1 + friction))
        spy_value = LIMITS.capital * LIMITS.reserve + units * current_spy
        return_pct = (portfolio["equity"] / LIMITS.capital - 1) * 100
        drawdown_pct = portfolio["max_drawdown"] * 100
        excess_pct = return_pct - (spy_value / LIMITS.capital - 1) * 100
        blockers = []
        if portfolio["sessions"] < 60: blockers.append("below_60_sessions")
        if portfolio["round_trips"] < 30: blockers.append("below_30_round_trips")
        if return_pct <= 0: blockers.append("not_profitable")
        if excess_pct <= 0: blockers.append("does_not_beat_60pct_spy")
        if drawdown_pct < -LIMITS.drawdown * 100: blockers.append("drawdown_exceeds_limit")
        if portfolio["halted"]: blockers.append("risk_circuit_breaker_triggered")
        strategies[name] = {
            "started_at": portfolio["started_at"],
            "equity_usd": portfolio["equity"],
            "return_pct": return_pct, "excess_vs_spy_pct": excess_pct,
            "spy_60pct_value_usd": spy_value,
            "spy_60pct_return_pct": (spy_value / LIMITS.capital - 1) * 100,
            "max_drawdown_pct": drawdown_pct, "sessions": portfolio["sessions"],
            "modeled_cost_usd": portfolio["modeled_cost"],
            "fills": portfolio["fills"], "round_trips": portfolio["round_trips"],
            "positions": sorted(portfolio["positions"]),
            "pending": portfolio["pending"], "halted": portfolio["halted"],
            "forward_gate_passed": not blockers, "blockers": blockers,
        }
    leaderboard = sorted(SHADOW_STRATEGIES, key=lambda name: (
        strategies[name]["forward_gate_passed"], strategies[name]["excess_vs_spy_pct"],
        strategies[name]["return_pct"], strategies[name]["max_drawdown_pct"]), reverse=True)
    return {
        "schema": SHADOW_SCHEMA, "mode": "forward_shadow_no_orders", "bar": str(latest),
        "code_sha256": state["code_sha256"],
        "capital_per_strategy_usd": LIMITS.capital,
        "strategies": strategies, "leaderboard": leaderboard,
        "warning": "Modeled portfolios only; forward gate is diagnostic and cannot authorize Alpaca orders.",
    }


def advance(frames, directory, account_hash):
    """Advance all virtual portfolios over unseen completed bars."""
    align(frames)
    directory = Path(directory)
    index = frames[SYMBOLS[0]].index
    if len(index) <= SHADOW_WARMUP:
        raise SafetyError("Insufficient shadow lookback")
    path = directory / STATE_FILE
    if path.exists():
        state = load(path)
        if state.get("schema") != SHADOW_SCHEMA or state.get("account_hash") != account_hash:
            raise SafetyError("Invalid shadow state/account")
        if state.get("code_sha256") != code_hash():
            raise SafetyError("Shadow code changed; explicit state migration required")
        if set(state.get("strategies", {})) != set(SHADOW_STRATEGIES):
            raise SafetyError("Shadow strategy set changed")
        last = pd.Timestamp(state["last_bar"])
        if last > index[-1]:
            raise SafetyError("Shadow signal time moved backwards")
        if last not in index:
            raise SafetyError("Shadow state bar outside lookback")
        unseen = range(index.get_loc(last) + 1, len(index))
    else:
        latest = index[-1]
        state = {
            "schema": SHADOW_SCHEMA, "created_at": now(), "account_hash": account_hash,
            "code_sha256": code_hash(),
            "last_bar": None,
            "strategies": {name: _new_portfolio(
                latest, frames["SPY"].Close.iloc[-1]) for name in SHADOW_STRATEGIES},
        }
        unseen = (len(index) - 1,)
    indices = list(unseen)
    all_fills = []
    for i in indices:
        all_fills.extend(_process_bar(state, frames, i))
    if state["last_bar"] is None:
        raise SafetyError("Shadow state did not advance")
    report = _report(state, frames)
    atomic_json(path, state)
    atomic_json(directory / REPORT_FILE, report)
    if all_fills:
        append_event(directory, {"event": "shadow_fills", "bar": state["last_bar"],
                                 "fills": all_fills})
    if indices:
        append_event(directory, {"event": "shadow_snapshot", "bar": state["last_bar"],
                                 "strategies": {name: {
                                     "equity_usd": item["equity_usd"],
                                     "return_pct": item["return_pct"],
                                     "fills": item["fills"]}
                                     for name, item in report["strategies"].items()}})
    return report


def _shadow_inputs(client):
    account, positions, orders, clock = client.account(), client.positions(), client.orders(), client.clock()
    cash, equity, _ = account_values(account, positions)
    if positions or orders or abs(cash - LIMITS.capital) >= .01 or abs(equity - LIMITS.capital) >= .01:
        raise SafetyError("Shadow requires the dedicated flat USD 2,000 paper account")
    wall = datetime.now(timezone.utc)
    clock_time = datetime.fromisoformat(clock["timestamp"].replace("Z", "+00:00"))
    if abs((wall - clock_time).total_seconds()) > 120:
        raise SafetyError("Broker clock drift")
    raw = client.bars((wall - timedelta(days=45)).isoformat(),
                      (wall - timedelta(minutes=2)).isoformat())
    frames = align(frames_from_bars(raw))
    frames = {symbol: frame[frame.index + pd.Timedelta(hours=1) <= pd.Timestamp(wall - timedelta(minutes=2))]
              for symbol, frame in frames.items()}
    align(frames)
    return account, frames


def migrate_shadow(client, directory):
    """Advance a reviewed schema-2 state to V2 without inventing observations."""
    if type(client) is not ReadOnlyPaper:
        raise SafetyError("Shadow migration requires the read-only broker client")
    directory = Path(directory)
    account, frames = _shadow_inputs(client)
    state = load(directory / STATE_FILE)
    previous = state.get("code_sha256")
    old_names = set(SHADOW_STRATEGIES) - {"trend_pullback_rsi_stoch"}
    if (state.get("schema") != 2 or previous not in SHADOW_MIGRATION_PREDECESSORS or
            state.get("account_hash") != _account_hash(account) or
            set(state.get("strategies", {})) != old_names):
        raise SafetyError("Invalid shadow migration evidence")
    latest = frames[SYMBOLS[0]].index[-1]
    try:
        last = pd.Timestamp(state["last_bar"])
        old_spy_start = float(state["spy_start"])
    except (KeyError, TypeError, ValueError):
        raise SafetyError("Invalid shadow migration evidence") from None
    if last > latest or not math.isfinite(old_spy_start) or old_spy_start <= 0:
        raise SafetyError("Invalid shadow migration evidence")
    skipped = []
    for name, portfolio in state["strategies"].items():
        if portfolio.get("pending"):
            skipped.append({"strategy": name, "pending": portfolio["pending"]})
        portfolio["pending"] = None
        portfolio["spy_start"] = old_spy_start
        try:
            equity = _value(portfolio, frames, -1, "Close")
        except (KeyError, TypeError, ValueError):
            raise SafetyError("Invalid shadow migration portfolio") from None
        if not math.isfinite(equity) or equity < 0:
            raise SafetyError("Invalid shadow migration portfolio")
        portfolio["equity"] = equity
        portfolio["peak"] = max(float(portfolio["peak"]), equity)
        portfolio["max_drawdown"] = min(
            float(portfolio["max_drawdown"]), equity / portfolio["peak"] - 1)
    state["strategies"]["trend_pullback_rsi_stoch"] = _new_portfolio(
        latest, frames["SPY"].Close.iloc[-1])
    state.update(schema=SHADOW_SCHEMA, code_sha256=code_hash(), last_bar=str(latest))
    state.pop("spy_start", None)
    report = _report(state, frames)
    atomic_json(directory / STATE_FILE, state)
    atomic_json(directory / REPORT_FILE, report)
    append_event(directory, {
        "event": "shadow_migration", "bar": str(latest),
        "migrated_from": previous, "added": "trend_pullback_rsi_stoch",
        "skipped_pending": skipped,
    })
    return report


def shadow_cycle(client, directory):
    """Read the flat paper account and advance models without any write API."""
    if type(client) is not ReadOnlyPaper:
        raise SafetyError("Shadow requires the read-only broker client")
    account, frames = _shadow_inputs(client)
    return advance(frames, directory, _account_hash(account))
