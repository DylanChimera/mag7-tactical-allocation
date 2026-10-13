"""Causal close-based signals. No execution or portfolio simulation here."""
from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import mean, stdev
from collections.abc import Sequence


@dataclass(frozen=True)
class SignalConfig:
    trend_window: int = 200
    vol_window: int = 60
    annualization: int = 252
    vol_threshold: float = 0.20
    qld_cap: float = 0.30

    def __post_init__(self):
        for value in (self.trend_window, self.vol_window, self.annualization):
            if type(value) is not int or value < 2:
                raise ValueError("Windows and annualization must be integers >= 2")
        if not isfinite(self.vol_threshold) or self.vol_threshold <= 0:
            raise ValueError("vol_threshold must be finite and positive")
        if not isfinite(self.qld_cap) or not 0 <= self.qld_cap <= 1:
            raise ValueError("qld_cap must lie in [0, 1]")


@dataclass(frozen=True)
class Signal:
    trend_up: bool
    annual_vol: float
    state: str
    qld_target: float


def signal_at(closes: Sequence[float], index: int,
              config: SignalConfig = SignalConfig()) -> Signal | None:
    """Use information through index inclusive; execute strictly later.

    None means insufficient history, not a bearish signal.
    """
    if not 0 <= index < len(closes):
        raise IndexError("Signal index is outside the price history")
    required = max(config.trend_window, config.vol_window + 1)
    history = list(closes[max(0, index + 1 - required):index + 1])
    if any(not isfinite(p) or p <= 0 for p in history):
        raise ValueError("Closes must be finite and strictly positive")
    if len(history) < required:
        return None
    trend_up = history[-1] > mean(history[-config.trend_window:])
    sample = history[-(config.vol_window + 1):]
    returns = [b / a - 1 for a, b in zip(sample, sample[1:])]
    vol = stdev(returns) * sqrt(config.annualization)
    state = ("up" if trend_up else "down") + ("_high_vol" if vol > config.vol_threshold else "_low_vol")
    target = 0.0
    if trend_up:
        target = config.qld_cap if vol == 0 else min(
            config.qld_cap, config.qld_cap * config.vol_threshold / vol)
    return Signal(trend_up, vol, state, target)
