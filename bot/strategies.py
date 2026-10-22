"""All decisions at close t use at most bars <= t. No fitted model."""
import pandas as pd

STRATEGIES = ("trend_6_24", "breakout_12", "reversion_20")
WARMUP = 30


def signals(frame, strategy):
    close = frame.Close
    if strategy == "trend_6_24":
        enter = close.rolling(6).mean() > close.rolling(24).mean()
        exit_ = ~enter
    elif strategy == "breakout_12":
        enter = close > frame.High.rolling(12).max().shift(1)
        exit_ = close < frame.Low.rolling(6).min().shift(1)
    elif strategy == "reversion_20":
        std = close.rolling(20).std().replace(0, float("nan"))
        z = (close - close.rolling(20).mean()) / std
        enter, exit_ = z < -1.5, z >= 0
    else:
        raise ValueError("Unknown strategy")
    return pd.DataFrame({"enter": enter.fillna(False), "exit": exit_.fillna(False)}, index=frame.index)
