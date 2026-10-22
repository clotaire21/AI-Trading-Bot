"""Backtest éducatif autonome, aucun accès au courtier, aucun ordre envoyé."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

START_CAPITAL = 2000.0
SYMBOL = "SPY"
COST_RATE = 0.001
START = "2023-01-01"

def backtest(data: pd.DataFrame) -> dict:
    if data.empty or len(data) < 45:
        raise ValueError("Historique insuffisant")
    frame = data[["Open", "Close"]].copy().dropna()
    # Les signaux calculés après la clôture de J ne peuvent s'exécuter qu'à l'ouverture J+1.
    fast = frame["Close"].rolling(10).mean()
    slow = frame["Close"].rolling(30).mean()
    target = (fast > slow).shift(1, fill_value=False).astype(bool)

    cash = START_CAPITAL
    units = 0.0
    trades = []
    equity = []
    for date, row in frame.iterrows():
        px = float(row["Open"])
        want = bool(target.loc[date])
        if want and units == 0:
            units = cash / (px * (1 + COST_RATE))
            cash = 0.0
            trades.append({"date": str(date.date()), "side": "BUY", "price": px})
        elif not want and units > 0:
            cash = units * px * (1 - COST_RATE)
            units = 0.0
            trades.append({"date": str(date.date()), "side": "SELL", "price": px})
        equity.append(cash + units * float(row["Close"]))
    buy_hold = START_CAPITAL * float(frame["Close"].iloc[-1]) / float(frame["Open"].iloc[0])
    curve = pd.Series(equity)
    drawdown = float((curve / curve.cummax() - 1).min())
    return {
        "symbol": SYMBOL,
        "initial_capital_usd": START_CAPITAL,
        "final_capital_usd": round(equity[-1], 2),
        "return_pct": round(100 * (equity[-1] / START_CAPITAL - 1), 2),
        "benchmark_buy_hold_usd": round(buy_hold, 2),
        "max_drawdown_pct": round(100 * drawdown, 2),
        "trades": trades,
        "days": len(frame),
        "assumed_cost_per_trade_pct": COST_RATE * 100,
    }

def main() -> None:
    import yfinance as yf
    raw = yf.download(SYMBOL, start=START, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    result = backtest(raw)
    out = Path("results")
    out.mkdir(exist_ok=True)
    (out / "backtest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "trades"}, indent=2))

if __name__ == "__main__":
    main()
