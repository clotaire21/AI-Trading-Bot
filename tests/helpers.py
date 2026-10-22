from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from bot.config import SYMBOLS


def frames(days=300, constant=False):
    sessions = pd.bdate_range("2023-01-02", periods=days)
    local = [d + pd.Timedelta(hours=h) for d in sessions for h in range(10, 16)]
    index = pd.DatetimeIndex(local).tz_localize("America/New_York").tz_convert("UTC")
    rng = np.random.default_rng(42)
    result = {}
    for s in SYMBOLS:
        px = np.full(len(index), 100.) if constant else 100 * np.exp(np.cumsum(rng.normal(.0001, .003, len(index))))
        result[s] = pd.DataFrame(dict(Open=px, High=px * 1.002,
            Low=px * .998, Close=px, Volume=np.full(len(index), 1000.)), index=index)
    return result


def account():
    return dict(id="test-paper-account", status="ACTIVE", currency="USD", cash="2000", equity="2000",
                trading_blocked=False, account_blocked=False, short_market_value="0")


def raw_bars(frames):
    return {s: [{"t": str(t), "o": float(r.Open), "h": float(r.High), "l": float(r.Low),
                 "c": float(r.Close), "v": float(r.Volume)} for t, r in f.iterrows()] for s, f in frames.items()}
