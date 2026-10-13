"""python -m mag7.data --start 2016-01-01 --end 2026-10-12"""
import argparse
import sys
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Download and audit daily market snapshots")
    parser.add_argument("--config", type=Path, default=Path("configs/data.toml"))
    parser.add_argument("--start", help="Inclusive ISO date")
    parser.add_argument("--end", help="Exclusive ISO date, no later than today in New York")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        from .pipeline import DataConfig, run
    except ImportError as exc:
        parser.exit(2, f'Data dependencies missing ({exc}). Install: python -m pip install -e ".[data]"\n')
    try:
        with args.config.open("rb") as handle:
            options = tomllib.load(handle)["data"]
        for key in ("start", "end", "output_dir"):
            value = getattr(args, key)
            if value is not None:
                options[key] = str(value)
        code, _ = run(DataConfig(**options))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Configuration/pipeline error: {exc}\n")
    sys.exit(code)


if __name__ == "__main__":
    main()
