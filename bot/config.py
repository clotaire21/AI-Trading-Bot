"""Conservative fixed limits. No URL, leverage or live-mode configuration."""
from dataclasses import dataclass

SYMBOLS = ("SPY", "QQQ", "IWM")
PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


@dataclass(frozen=True)
class Limits:
    capital: float = 2000.0
    position: float = 0.20
    exposure: float = 0.60
    reserve: float = 0.40
    daily_loss: float = 0.02
    drawdown: float = 0.08
    stop_loss: float = 0.03
    max_hold_bars: int = 18
    max_orders_day: int = 6
    fee_bps: float = 1.0
    slippage_bps: float = 9.0


LIMITS = Limits()
