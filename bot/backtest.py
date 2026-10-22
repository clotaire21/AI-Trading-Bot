"""Event-driven long-only portfolio. Signal close -> NEXT bar open.

Stops are observed at bar close and executed at next available open (gaps
included). They are NOT guaranteed stop prices. No high/low intrabar fills.
"""
import math
import pandas as pd
from .config import LIMITS, SYMBOLS
from .data import align
from .strategies import signals, WARMUP


def metrics(equity, trades, capital=2000):
    curve = pd.Series(equity, dtype=float)
    augmented = pd.concat([pd.Series([capital], index=[curve.index[0] - pd.Timedelta(seconds=1)]), curve])
    dd = augmented / augmented.cummax() - 1
    daily = augmented.groupby(augmented.index.tz_convert("America/New_York").date).last()
    returns = daily.pct_change()
    returns.iloc[0] = daily.iloc[0] / capital - 1
    std = returns.std()
    return {"final_capital_usd": float(curve.iloc[-1]),
            "return_pct": float((curve.iloc[-1] / capital - 1) * 100),
            "max_drawdown_pct": float(dd.min() * 100),
            "sharpe_daily": float(returns.mean() / std * math.sqrt(252)) if len(returns) > 2 and std > 0 else None,
            "orders": len(trades), "round_trips": sum(t["side"] == "sell" for t in trades),
            "days": len(daily), "modeled_cost_usd": float(sum(t["cost"] for t in trades))}


def run(frames, strategy, start=None, end=None, limits=LIMITS):
    align(frames)
    index = frames["SPY"].index
    idx = [i for i in range(WARMUP, len(index))
           if (start is None or index[i] >= start) and (end is None or index[i] < end)]
    if not idx:
        raise ValueError("Insufficient evaluation bars")
    sig = {s: signals(frames[s], strategy) for s in SYMBOLS}
    cash, peak, day_start = limits.capital, limits.capital, limits.capital
    positions, trades, journal, equity = {}, [], [], {}
    day, daily_orders, daily_halt, halted = None, 0, False, False
    fee, slip = limits.fee_bps / 10000, limits.slippage_bps / 10000

    def value(i, field):
        return cash + sum(p["qty"] * float(frames[s].iloc[i][field]) for s, p in positions.items())

    def sell(s, i, reason, field="Open"):
        nonlocal cash, daily_orders
        p = positions.pop(s)
        reference = float(frames[s].iloc[i][field])
        price = reference * (1 - slip)
        cash += p["qty"] * price * (1 - fee)
        trades.append(dict(timestamp=str(index[i]), symbol=s, side="sell", qty=p["qty"],
            price=price, cost=p["qty"] * (reference - price + price * fee), reason=reason))
        daily_orders += 1

    for i in idx:
        today = index[i].tz_convert("America/New_York").date()
        if today != day:
            day, daily_orders, daily_halt = today, 0, False
            day_start = list(equity.values())[-1] if equity else limits.capital
        opening_value = value(i, "Open")
        if opening_value <= peak * (1 - limits.drawdown):
            halted = True
        if opening_value <= day_start * (1 - limits.daily_loss):
            daily_halt = True
        exited = set()
        for s, p in list(positions.items()):
            close = float(frames[s].Close.iloc[i - 1])
            budget_equity = min(limits.capital, opening_value)
            over = (p["qty"] * float(frames[s].Open.iloc[i]) > budget_equity * limits.position + 1 or
                    opening_value - cash > budget_equity * limits.exposure + 1)
            reason = ("drawdown_halt" if halted else "daily_halt" if daily_halt else
                      "position_cap" if over else
                      "stop_loss" if close <= p["entry"] * (1 - limits.stop_loss) else
                      "max_hold" if i - p["bar"] >= limits.max_hold_bars else
                      "signal_exit" if bool(sig[s].exit.iloc[i - 1]) else None)
            if reason:
                sell(s, i, reason)
                exited.add(s)
                break  # production sends at most one order per hourly cycle
        entered = False
        for s in SYMBOLS:
            decision = "hold" if s in positions else "no_signal"
            if s not in positions and s not in exited and bool(sig[s].enter.iloc[i - 1]):
                decision = "blocked_risk"
                if not (halted or daily_halt or exited or entered) and daily_orders < limits.max_orders_day:
                    eq = value(i, "Open")
                    gross = eq - cash
                    base = min(limits.capital, eq)
                    budget = max(0, min(base * limits.position, base * limits.exposure - gross,
                                         cash - base * limits.reserve)) * .99
                    reference = float(frames[s].Open.iloc[i])
                    price = reference * (1 + slip)
                    qty = budget / (price * (1 + fee))
                    if budget >= 5:
                        cash -= qty * price * (1 + fee)
                        positions[s] = {"qty": qty, "entry": price, "bar": i}
                        daily_orders += 1
                        entered = True
                        trades.append(dict(timestamp=str(index[i]), signal_timestamp=str(index[i - 1]),
                            symbol=s, side="buy", qty=qty, price=price,
                            cost=qty * (price - reference + price * fee), reason="signal_entry"))
                        decision = "buy"
            journal.append(dict(timestamp=str(index[i]), symbol=s, decision=decision,
                                halted=halted, daily_halt=daily_halt))
        close_value = value(i, "Close")
        if close_value <= day_start * (1 - limits.daily_loss):
            daily_halt = True
        if close_value <= peak * (1 - limits.drawdown):
            halted = True
        peak = max(peak, close_value)
        equity[index[i]] = close_value
        if cash < -0.000001:
            raise AssertionError("Leverage detected")
    # Common end-of-test liquidation assumption, charged for every portfolio.
    for s in list(positions):
        sell(s, idx[-1], "end_of_test", "Close")
    equity[index[idx[-1]]] = cash
    return dict(metrics=metrics(equity, trades, limits.capital), equity={str(k): v for k, v in equity.items()},
                trades=trades, decisions=journal, halted=halted)


def benchmark(frame, start, end, allocation=1.0, limits=LIMITS):
    sample = frame[(frame.index >= start) & (frame.index < end)]
    fee, slip = limits.fee_bps / 10000, limits.slippage_bps / 10000
    initial, final = float(sample.Open.iloc[0]), float(sample.Close.iloc[-1])
    units = limits.capital * allocation / (initial * (1 + slip) * (1 + fee))
    reserve = limits.capital * (1 - allocation)
    curve = reserve + units * sample.Close
    curve.iloc[-1] = reserve + units * final * (1 - slip) * (1 - fee)
    trades = [{"side": "buy", "cost": units * initial * (slip + (1 + slip) * fee)},
              {"side": "sell", "cost": units * final * (slip + (1 - slip) * fee)}]
    return metrics(curve.to_dict(), trades, limits.capital)
