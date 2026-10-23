"""All decisions at close t use at most bars <= t. No fitted model."""
import pandas as pd

STRATEGIES = ("trend_6_24", "breakout_12", "reversion_20")
# Forward-only candidates are deliberately separate from the original research
# set. Adding them must not silently reuse the already-observed final holdout as
# if it were new promotion evidence.
SHADOW_STRATEGIES = STRATEGIES + ("selective_reversion_20", "trend_24_72")
WARMUP = 30
SHADOW_WARMUP = 72


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
    elif strategy == "selective_reversion_20":
        # A pre-declared, lower-turnover mean-reversion hypothesis. It is only
        # eligible for new forward observation, not retrospective promotion.
        std = close.rolling(20).std().replace(0, float("nan"))
        z = (close - close.rolling(20).mean()) / std
        enter, exit_ = z < -2.5, z >= -1.0
    elif strategy == "trend_24_72":
        fast = close.ewm(span=24, adjust=False, min_periods=24).mean()
        slow = close.ewm(span=72, adjust=False, min_periods=72).mean()
        enter, exit_ = fast > slow, fast <= slow
    else:
        raise ValueError("Unknown strategy")
    return pd.DataFrame({"enter": enter.fillna(False), "exit": exit_.fillna(False)}, index=frame.index)
