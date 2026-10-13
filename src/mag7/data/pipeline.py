"""Daily Yahoo snapshots. This module never fills missing trading sessions."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd

UNIVERSE = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "QQQ", "QLD")
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]
REQUIRED = PRICE_COLUMNS + ["Volume", "Dividends", "Stock Splits"]
RENAME = {"Open": "open_yahoo", "High": "high_yahoo", "Low": "low_yahoo",
          "Close": "close_yahoo", "Adj Close": "adj_close", "Volume": "volume",
          "Dividends": "dividend_yahoo", "Stock Splits": "split_ratio"}


@dataclass(frozen=True)
class DataConfig:
    symbols: tuple[str, ...] = UNIVERSE
    start: str = "2016-01-01"
    end: str = ""
    output_dir: str = "data"
    calendar: str = "XNYS"

    def resolve(self):
        today = datetime.now(ZoneInfo("America/New_York")).date()
        end = date.fromisoformat(self.end) if self.end else today
        start = date.fromisoformat(self.start)
        if start < date(2013, 1, 1):
            raise ValueError("Prototype starts in 2013 or later (common post-IPO universe)")
        if not start < end <= today:
            raise ValueError("Require start < end <= today's New York date; end is exclusive")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Symbols must be nonempty and unique")
        if not set(self.symbols) <= set(UNIVERSE):
            raise ValueError("This prototype supports only the nine configured US instruments")
        if self.calendar != "XNYS":
            raise ValueError("Only XNYS daily session calendar is validated in this prototype")
        return DataConfig(tuple(self.symbols), start.isoformat(), end.isoformat(),
                          self.output_dir, self.calendar)


def expected_schedule(config: DataConfig) -> pd.DataFrame:
    last = (date.fromisoformat(config.end) - timedelta(days=1)).isoformat()
    # Extra padding allows ranges starting/ending on a holiday.
    calendar = xcals.get_calendar(config.calendar,
        start=(date.fromisoformat(config.start) - timedelta(days=10)).isoformat(),
        end=(date.fromisoformat(config.end) + timedelta(days=10)).isoformat())
    schedule = calendar.schedule.loc[config.start:last].copy()
    if schedule.empty:
        raise ValueError("No trading sessions in requested interval")
    schedule.index = pd.Index([d.date().isoformat() for d in schedule.index], name="date")
    return schedule


def fetch_yahoo(symbol: str, start: str, end: str):
    import yfinance as yf
    last_error = None
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(start=start, end=end, interval="1d",
                auto_adjust=False, back_adjust=False, actions=True, repair=False,
                keepna=True, prepost=False, rounding=False, timeout=20, raise_errors=True)
            if frame is None or frame.empty:
                raise ValueError("Provider returned no observations")
            metadata = ticker.get_history_metadata()
            if not metadata:
                raise ValueError("Provider returned no metadata")
            return frame, metadata
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Yahoo failed for {symbol} after 3 attempts: {last_error}")


def normalize(frame: pd.DataFrame, symbol: str, expected: list[str],
              metadata: dict) -> tuple[pd.DataFrame | None, dict]:
    report = {"symbol": symbol, "rows": len(frame), "status": "failed", "errors": [], "warnings": []}
    errors, warnings = report["errors"], report["warnings"]
    missing_cols = sorted(set(REQUIRED) - set(frame.columns))
    if missing_cols:
        errors.append(f"Missing columns: {missing_cols}")
        return None, report
    if metadata.get("currency") != "USD":
        errors.append("Currency is not explicitly USD")
    if metadata.get("exchangeTimezoneName") not in ("America/New_York", "US/Eastern"):
        errors.append("Exchange timezone is not explicitly New York")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        errors.append("Expected timezone-aware provider DatetimeIndex")
        return None, report
    dates = [d.date().isoformat() for d in frame.index.tz_convert("America/New_York")]
    if len(dates) != len(set(dates)):
        errors.append("Duplicate trading dates")
    if dates != sorted(dates):
        errors.append("Dates are not sorted")
    missing = sorted(set(expected) - set(dates))
    extra = sorted(set(dates) - set(expected))
    report["missing_sessions"] = missing
    report["unexpected_sessions"] = extra
    if missing:
        errors.append(f"Missing {len(missing)} expected sessions; no forward filling")
    if extra:
        errors.append(f"Unexpected sessions: {extra}")
    numeric = frame[REQUIRED].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("Missing or nonfinite numeric values")
    if (numeric[PRICE_COLUMNS] <= 0).any().any():
        errors.append("Nonpositive prices")
    if (numeric[["Volume", "Dividends", "Stock Splits"]] < 0).any().any():
        errors.append("Negative volume or corporate action")
    if ((numeric["High"] + 1e-8 < numeric[["Open", "Close", "Low"]].max(axis=1)) |
        (numeric["Low"] - 1e-8 > numeric[["Open", "Close", "High"]].min(axis=1))).any():
        errors.append("Inconsistent OHLC range")
    if (numeric["Volume"] == 0).any():
        warnings.append("Zero volume sessions: manual review needed")
    adjusted_return = numeric["Adj Close"].pct_change(fill_method=None)
    extreme = [d for d, flag in zip(dates, adjusted_return.abs() > 0.35) if flag]
    if extreme:
        warnings.append(f"Adjusted daily moves above 35%: {extreme}")
    if "Capital Gains" in frame and frame["Capital Gains"].fillna(0).ne(0).any():
        errors.append("Nonzero capital gains distribution: unsupported action; review required")
    report["first_date"] = dates[0] if dates else None
    report["last_date"] = dates[-1] if dates else None
    report["dividend_events"] = int((numeric["Dividends"] > 0).sum())
    report["split_events"] = int((numeric["Stock Splits"] > 0).sum())
    report["status"] = "failed" if errors else ("review" if warnings else "passed")
    if errors:
        return None, report
    output = numeric.rename(columns=RENAME).reset_index(drop=True)
    output.insert(0, "symbol", symbol)
    output.insert(0, "date", dates)
    # These are adjusted synthetic prices, NOT executable historical dollar quotes.
    factor = output["adj_close"] / output["close_yahoo"]
    output["adjustment_factor"] = factor
    for field in ("open", "high", "low"):
        output[f"adj_{field}"] = output[f"{field}_yahoo"] * factor
    output["currency"] = "USD"
    output["price_basis"] = "yahoo_split_adjusted_ohlc"
    return output, report


def dump_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(config: DataConfig, fetch: Callable = fetch_yahoo) -> tuple[int, Path]:
    config = config.resolve()
    schedule = expected_schedule(config)
    expected = schedule.index.tolist()
    root = Path(config.output_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:6]
    raw = root / "raw" / stamp
    processed = root / "processed" / stamp
    raw.mkdir(parents=True, exist_ok=False)
    schedule.to_csv(raw / "sessions.csv")
    normalized, reports = [], []
    manifest = {"run_id": stamp, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running", "config": asdict(config), "python": platform.python_version(),
        "versions": {}, "git_commit": None, "files_sha256": {},
        "provider": "Yahoo Finance via yfinance",
        "raw_definition": "Unmodified yfinance DataFrame serialization, not HTTP response bytes",
        "query_options": {"interval": "1d", "auto_adjust": False, "back_adjust": False,
            "actions": True, "repair": False, "keepna": True, "prepost": False},
        "calendar_note": "XNYS used as daily US equity session proxy; not venue-specific",
        "warnings": ["Retrospectively selected Mag7 universe", "Revised historical data, not point-in-time archive",
                     "No independent provider reconciliation", "No dividend payment dates or cash rates"]}
    for dependency in ("yfinance", "pandas", "numpy", "exchange_calendars", "tzdata"):
        try:
            manifest["versions"][dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            manifest["versions"][dependency] = None
    try:
        manifest["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    dump_json(raw / "manifest.json", manifest)
    for symbol in config.symbols:
        print(f"Downloading {symbol} ...", flush=True)
        try:
            frame, metadata = fetch(symbol, config.start, config.end)
            frame.to_csv(raw / f"{symbol}.csv", index_label="timestamp")
            dump_json(raw / f"{symbol}.metadata.json", {
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "metadata": metadata})
            table, report = normalize(frame, symbol, expected, metadata)
            reports.append(report)
            if table is not None:
                normalized.append(table)
        except Exception as exc:
            reports.append({"symbol": symbol, "status": "failed", "errors": [str(exc)], "warnings": []})
    failed = any(r["errors"] for r in reports)
    status = "failed" if failed else ("review" if any(r["warnings"] for r in reports) else "passed")
    dump_json(raw / "quality_report.json", {"status": status, "symbols": reports})
    manifest["status"] = status
    if not failed:
        processed.mkdir(parents=True, exist_ok=False)
        table = pd.concat(normalized, ignore_index=True).sort_values(["date", "symbol"])
        table.to_csv(processed / "market_daily.csv", index=False)
        signals = table.pivot(index="date", columns="symbol", values="adj_close")
        signals.to_csv(processed / "signal_prices.csv")
        if "QQQ" in signals:
            signals[["QQQ"]].rename(columns={"QQQ": "close"}).to_csv(processed / "qqq.csv")
    for folder in (raw, processed):
        if folder.exists():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.name != "manifest.json":
                    manifest["files_sha256"][path.relative_to(root).as_posix()] = sha256(path)
    dump_json(raw / "manifest.json", manifest)
    # Never replace the latest successful pointer after a failed/incomplete run.
    if not failed:
        pointer = root / "processed" / "latest.json"
        temp = pointer.with_suffix(".tmp")
        dump_json(temp, {"run_id": stamp, "status": status,
                        "directory": stamp, "manifest": f"../raw/{stamp}/manifest.json"})
        temp.replace(pointer)
    print(f"Status: {status}. Audit: {raw / 'quality_report.json'}")
    if not failed:
        print(f"Research files: {processed}")
    return (1 if failed else 0), raw
