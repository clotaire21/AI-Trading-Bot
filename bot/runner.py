"""Reconcile, journal, then optionally submit PAPER limits, one order per run.

Missing/corrupt state, pending orders, clock drift, stale bars, unknown fills,
unvalidated code, a failed research gate or kill switch all fail closed.
"""
from __future__ import annotations
import hashlib
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from .alpaca import ReadOnlyPaper, ExecutionPaper, SafetyError
from .config import LIMITS, SYMBOLS, PAPER_URL
from .data import frames_from_bars, align
from .risk import account_values, make_order, number
from .state import atomic_json, append_event, code_hash, load, now
from .strategies import signals, STRATEGIES


def account_hash(account):
    return hashlib.sha256(account["id"].encode()).hexdigest()


def probe(client, directory):
    account, positions, orders, clock = client.account(), client.positions(), client.orders(), client.clock()
    historical_orders = client.orders("all")
    cash, equity, _ = account_values(account, positions)
    assets = {s: client.asset(s) for s in SYMBOLS}
    flags = all(a.get("tradable") and a.get("fractionable") and a.get("status") == "active" for a in assets.values())
    start = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    end = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    bars = align(frames_from_bars(client.bars(start, end)))
    report = {"at": now(), "endpoint": PAPER_URL, "read_only": True,
        "account_hash": account_hash(account), "cash_usd": cash, "equity_usd": equity,
        "positions_count": len(positions), "open_orders_count": len(orders),
        "historical_orders_count_capped_500": len(historical_orders),
        "assets_ready": flags, "market_open": bool(clock["is_open"]),
        "last_bar": str(bars["SPY"].index[-1]), "code_sha256": code_hash(),
        "dedicated_2000_account_ready": abs(cash - 2000) < .01 and not positions and not orders and not historical_orders and flags}
    atomic_json(Path(directory) / "connection.json", report)
    return report


def execution_gate(directory, policy, account):
    if os.environ.get("PAPER_KILL_SWITCH", "true") != "false":
        raise SafetyError("Kill switch is on (default)")
    if not policy.get("orders_enabled") or policy.get("strategy") not in STRATEGIES:
        raise SafetyError("Paper order policy disabled")
    try:
        proof = load(Path(directory) / "validation.json")
        research = load(Path(directory) / "research.json")
    except (OSError, ValueError):
        raise SafetyError("Missing/corrupt validation evidence") from None
    if (proof.get("code_sha256") != code_hash() or not proof.get("safety_tests_passed") or
            proof.get("account_hash") != account_hash(account) or not proof.get("connection_passed")):
        raise SafetyError("Missing or invalid safety/connection evidence")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(proof["at"])
    if not timedelta(0) <= age <= timedelta(days=7):
        raise SafetyError("Expired safety validation")
    if (not research.get("research_gate_passed") or
            research.get("selected_on_validation") != policy["strategy"] or
            proof.get("research_data_sha256") != research.get("data_sha256")):
        raise SafetyError("Research gate failed")


def cycle(client, directory, policy, execute=False):
    directory = Path(directory)
    account, clock = client.account(), client.clock()
    positions, open_orders = client.positions(), client.orders()
    cash, equity, gross = account_values(account, positions)
    clock_time = datetime.fromisoformat(clock["timestamp"].replace("Z", "+00:00"))
    wall = datetime.now(timezone.utc)
    if abs((wall - clock_time).total_seconds()) > 120:
        raise SafetyError("Broker clock drift")
    if execute:
        execution_gate(directory, policy, account)
    if not clock["is_open"]:
        append_event(directory, {"event": "market_closed", "equity": equity})
        return
    state_path = directory / "state.json"
    if state_path.exists():
        state = load(state_path)
        if state["account_hash"] != account_hash(account):
            raise SafetyError("Account changed; state cannot be reused")
    else:
        if positions or open_orders or abs(equity - LIMITS.capital) >= .01 or client.orders("all"):
            raise SafetyError("Initialize only a dedicated unused flat $2,000 paper account")
        state = {"account_hash": account_hash(account), "peak": equity, "day": None,
            "day_start": equity, "daily_halt": False, "halted": False,
            "orders_today": 0, "entries": {}, "last_bar": None, "pending": None,
            "benchmark_start": None, "initial_equity": equity, "modeled_cost": 0.0,
            "tracked_quantities": {}, "tracked_cash": cash}
    # Reconcile any ambiguous POST before another decision. Never retry POST.
    if state.get("pending"):
        pending = state["pending"]
        recent = client.orders("all")
        matching = [o for o in recent if o.get("client_order_id") == pending["client_id"]]
        if not matching or matching[0]["status"] not in ("filled", "canceled", "expired", "rejected"):
            raise SafetyError("Pending/ambiguous order; reconcile before further submissions")
        order = matching[0]
        filled = number(order.get("filled_qty", 0))
        if order.get("symbol") != pending["symbol"] or order.get("side") != pending["side"] or not 0 <= filled <= number(pending["qty"]):
            raise SafetyError("Unexpected order reconciliation fields")
        expected = {s: DecimalQty(q) for s, q in state["tracked_quantities"].items()}
        symbol = pending["symbol"]
        expected[symbol] = expected.get(symbol, DecimalQty(0)) + DecimalQty(order.get("filled_qty", 0)) * (1 if pending["side"] == "buy" else -1)
        expected = {s: q for s, q in expected.items() if q != 0}
        actual = {p["symbol"]: DecimalQty(p["qty"]) for p in positions}
        if expected != actual:
            raise SafetyError("Fills do not explain observed quantities")
        if filled > 0:
            notional = filled * number(order["filled_avg_price"])
            state["modeled_cost"] += notional * .001
            state["tracked_cash"] += notional * (-1 if pending["side"] == "buy" else 1)
            if pending["side"] == "buy":
                state["entries"][pending["symbol"]] = pending["bar"]
        state["tracked_quantities"] = {p["symbol"]: p["qty"] for p in positions}
        state["pending"] = None
        append_event(directory, {"event": "order_reconciled", "client_id": pending["client_id"],
                                  "status": order["status"], "filled_qty": filled,
                                  "filled_avg_price": order.get("filled_avg_price")})
        atomic_json(state_path, state)
    observed = {p["symbol"]: DecimalQty(p["qty"]) for p in positions}
    tracked = {s: DecimalQty(q) for s, q in state["tracked_quantities"].items()}
    if observed != tracked:
        raise SafetyError("Unexplained position change (manual trade/corporate action); suspend")
    if abs(cash - state["tracked_cash"]) > .02:
        raise SafetyError("Unexplained cash change; suspend")
    if open_orders:
        raise SafetyError("Open orders exist; no additional exposure")
    today = clock_time.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if today != state["day"]:
        state.update(day=today, day_start=state.get("last_equity", equity), daily_halt=False, orders_today=0)
    risk_equity = equity - state["modeled_cost"]
    state["peak"] = max(state["peak"], risk_equity)
    state["halted"] |= risk_equity <= state["peak"] * (1 - LIMITS.drawdown)
    state["daily_halt"] |= risk_equity <= state["day_start"] * (1 - LIMITS.daily_loss)
    state["last_equity"] = risk_equity
    state["max_drawdown"] = min(state.get("max_drawdown", 0), risk_equity / state["peak"] - 1)
    # Persist observed loss suspensions even if the data request later fails.
    atomic_json(state_path, state)
    bars = align(frames_from_bars(client.bars((wall - timedelta(days=20)).isoformat(),
                                             (wall - timedelta(minutes=2)).isoformat())))
    # Alpaca end is inclusive on bar start. Remove all incomplete clock hours.
    bars = {s: f[f.index + pd.Timedelta(hours=1) <= pd.Timestamp(wall - timedelta(minutes=2))] for s, f in bars.items()}
    index = bars["SPY"].index
    if len(index) < 30:
        raise SafetyError("Insufficient completed bars")
    latest = index[-1]
    age = (pd.Timestamp(wall) - latest - pd.Timedelta(hours=1)).total_seconds()
    if not 0 <= age <= 3600:
        raise SafetyError("Stale completed signal bar")
    bar = str(latest)
    if state["last_bar"] and pd.Timestamp(state["last_bar"]) > latest:
        raise SafetyError("Signal time moved backwards")
    strategy = policy.get("strategy") or "trend_6_24"
    if strategy not in STRATEGIES:
        raise SafetyError("Unknown strategy")
    by_symbol = {p["symbol"]: p for p in positions}
    budget_equity = min(LIMITS.capital, risk_equity)
    portfolio_over = gross > budget_equity * LIMITS.exposure + 1
    decisions, candidates = [], []
    for s in SYMBOLS:
        p = by_symbol.get(s)
        signal = signals(bars[s], strategy).iloc[-1]
        price = float(bars[s].Close.iloc[-1])
        reason, order = "no_signal", None
        if p:
            if s not in state["entries"]:
                raise SafetyError("Position missing entry journal")
            held = sum(index > pd.Timestamp(state["entries"][s]))
            stop = number(p["current_price"]) <= number(p["avg_entry_price"]) * (1 - LIMITS.stop_loss)
            over = portfolio_over or number(p["market_value"]) > budget_equity * LIMITS.position + 1
            if state["halted"] or state["daily_halt"] or stop or over or held >= LIMITS.max_hold_bars or bool(signal.exit):
                reason = "risk_exit" if state["halted"] or state["daily_halt"] or stop or over else "time_or_signal_exit"
                order = make_order(s, "sell", price, p["qty"], bar, state["account_hash"], strategy)
            else:
                reason = "hold"
        elif bool(signal.enter):
            reason = "entry_blocked"
            if not (state["halted"] or state["daily_halt"]) and state["orders_today"] < LIMITS.max_orders_day:
                # Reserve 1% extra against fees/rounding; never use buying_power.
                budget = min(budget_equity * LIMITS.position, budget_equity * LIMITS.exposure - gross,
                             cash - budget_equity * LIMITS.reserve) * .99
                if budget >= 5:
                    order = make_order(s, "buy", price, budget, bar, state["account_hash"], strategy)
                    reason = "entry"
        decisions.append({"symbol": s, "reason": reason, "enter": bool(signal.enter),
                          "exit": bool(signal.exit), "reference_price": price})
        if order:
            candidates.append(order)
    if state["benchmark_start"] is None:
        state["benchmark_start"] = float(bars["SPY"].Close.iloc[-1])
    benchmark = LIMITS.capital * float(bars["SPY"].Close.iloc[-1]) / state["benchmark_start"]
    snapshot = {"event": "decision", "bar": bar, "strategy": strategy,
        "equity_usd": equity, "net_modeled_equity_usd": equity - state["modeled_cost"],
        "return_pct": (equity / LIMITS.capital - 1) * 100,
        "net_return_pct": (risk_equity / LIMITS.capital - 1) * 100,
        "spy_return_pct": (benchmark / LIMITS.capital - 1) * 100,
        "max_drawdown_pct": state["max_drawdown"] * 100,
        "benchmark_timestamp": bar, "account_timestamp": clock["timestamp"],
        "spy_price_benchmark_usd": benchmark, "cash_usd": cash,
        "halted": state["halted"], "daily_halt": state["daily_halt"],
        "execute": execute, "code_sha256": code_hash(), "decisions": decisions}
    append_event(directory, snapshot)
    atomic_json(directory / "performance.json", snapshot)
    if state["last_bar"] == bar:
        atomic_json(state_path, state)
        return
    # One POST per cycle, exits first. This prevents cash reuse before fills and
    # makes crash recovery deterministic without resubmitting a batch.
    candidates.sort(key=lambda o: o.side == "buy")
    state["last_bar"] = bar
    atomic_json(state_path, state)
    if execute and candidates:
        order = candidates[0]
        intent = {"symbol": order.symbol, "side": order.side, "qty": str(order.qty),
                  "limit_price": str(order.limit_price), "client_id": order.client_id, "bar": bar}
        state["pending"] = intent
        state["orders_today"] += 1
        append_event(directory, {"event": "order_intent", **intent})
        atomic_json(state_path, state)  # persist intent BEFORE network write
        response = client.submit(order)
        append_event(directory, {"event": "order_ack", "client_id": order.client_id,
                                  "status": response["status"]})


def DecimalQty(value):
    from decimal import Decimal
    result = Decimal(str(value))
    if not result.is_finite():
        raise SafetyError("Nonfinite quantity")
    return result
