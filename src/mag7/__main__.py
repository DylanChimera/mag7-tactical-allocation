"""Run from repository root: python -m mag7 --demo."""
import argparse
import csv
import json
import math
import tomllib
from dataclasses import asdict
from datetime import date
from pathlib import Path
from .signals import SignalConfig, signal_at


def main():
    parser = argparse.ArgumentParser(description="Compute a signal, not a backtest")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Synthetic prices only")
    source.add_argument("--csv", type=Path, help="CSV with date,close columns")
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    args = parser.parse_args()
    with args.config.open("rb") as handle:
        config = SignalConfig(**tomllib.load(handle)["signal"])
    if args.demo:
        closes = [100 * math.exp(0.0005 * i + 0.015 * math.sin(i / 8))
                  for i in range(300)]
        label = "SYNTHETIC DEMO - no investment performance"
    else:
        with args.csv.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not {"date", "close"} <= set(reader.fieldnames or []):
                parser.error("CSV requires date and close columns")
            rows = list(reader)
        dates = [date.fromisoformat(row["date"]) for row in rows]
        if any(a >= b for a, b in zip(dates, dates[1:])):
            parser.error("Dates must be unique and strictly increasing")
        closes = [float(row["close"]) for row in rows]
        label = str(args.csv)
    if not closes:
        parser.error("Empty price history")
    result = signal_at(closes, len(closes) - 1, config)
    print(json.dumps({"source": label, "observations": len(closes),
                      "signal": asdict(result) if result else None}, indent=2))


if __name__ == "__main__":
    main()
