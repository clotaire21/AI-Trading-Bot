from __future__ import annotations
import hashlib
import pandas as pd
import numpy as np
from .config import SYMBOLS


def validate(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("UTC-aware timestamps required")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Duplicate/unsorted bars")
    if not set(("Open", "High", "Low", "Close", "Volume")) <= set(frame.columns):
        raise ValueError("Missing OHLCV")
    a = frame[["Open", "High", "Low", "Close", "Volume"]].to_numpy(float)
    if not len(a) or not np.isfinite(a).all() or (a[:, :4] <= 0).any() or (a[:, 4] <= 0).any():
        raise ValueError("Nonfinite/nonpositive OHLCV")
    if ((frame.High < frame[["Open", "Close", "Low"]].max(axis=1)) |
        (frame.Low > frame[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC")
    return frame


def frames_from_bars(bars):
    result = {}
    for s in SYMBOLS:
        df = pd.DataFrame(bars[s]).rename(columns={"t": "timestamp", "o": "Open",
            "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        if df.empty:
            raise ValueError("Missing symbol bars: " + s)
        df.index = pd.to_datetime(df.pop("timestamp"), utc=True)
        # Only full clock-hour bars 10:00..15:00 New York, weekdays.
        # Discard opening partial/extended-hours bars; no synthetic forward fill.
        ny = df.index.tz_convert("America/New_York")
        df = df[(ny.hour >= 10) & (ny.hour <= 15) & (ny.dayofweek < 5)]
        result[s] = validate(df[["Open", "High", "Low", "Close", "Volume"]])
    return result


def align(frames):
    if set(frames) != set(SYMBOLS):
        raise ValueError("Fixed universe required")
    index = frames[SYMBOLS[0]].index
    for s in SYMBOLS:
        validate(frames[s])
        if not index.equals(frames[s].index):
            raise ValueError("Missing or misaligned cross-symbol bars")
    return frames


def fingerprint(frames):
    digest = hashlib.sha256()
    for s in SYMBOLS:
        digest.update(s.encode())
        digest.update(frames[s].rename_axis("timestamp").to_csv(float_format="%.10f").encode())
    return digest.hexdigest()
