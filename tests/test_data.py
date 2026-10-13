import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mag7.data.pipeline import DataConfig, expected_schedule, normalize, run, sha256, fetch_yahoo

META = {"currency": "USD", "exchangeTimezoneName": "America/New_York"}


def fixture(dates):
    index = pd.DatetimeIndex(dates, tz="America/New_York")
    return pd.DataFrame({"Open": 100., "High": 102., "Low": 99., "Close": 101.,
        "Adj Close": 100., "Volume": 10000, "Dividends": 0., "Stock Splits": 0.}, index=index)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.dates = ["2024-07-03", "2024-07-05"]
        self.frame = fixture(self.dates)

    def test_holiday_is_not_missing_and_end_is_exclusive(self):
        c = DataConfig(start="2024-07-03", end="2024-07-06").resolve()
        self.assertEqual(expected_schedule(c).index.tolist(), self.dates)

    def test_adjusted_open_uses_same_factor_as_close(self):
        table, audit = normalize(self.frame, "QQQ", self.dates, META)
        self.assertFalse(audit["errors"])
        self.assertAlmostEqual(table.adj_open.iloc[0], 100 * 100 / 101)
        self.assertEqual(table.open_yahoo.iloc[0], 100)

    def test_missing_session_fails_no_forward_fill(self):
        table, audit = normalize(self.frame.iloc[:1], "QQQ", self.dates, META)
        self.assertIsNone(table)
        self.assertEqual(audit["missing_sessions"], ["2024-07-05"])

    def test_duplicate_dates_fail(self):
        table, audit = normalize(pd.concat([self.frame, self.frame.iloc[:1]]), "QQQ", self.dates, META)
        self.assertIsNone(table)
        self.assertIn("Duplicate trading dates", audit["errors"])

    def test_nan_and_invalid_ohlc_fail(self):
        for column, value in [("Low", 200.), ("Adj Close", float("nan")), ("Volume", -1)]:
            frame = self.frame.copy()
            frame.loc[frame.index[0], column] = value
            self.assertIsNone(normalize(frame, "QQQ", self.dates, META)[0])

    def test_unknown_currency_fails(self):
        self.assertIsNone(normalize(self.frame, "QQQ", self.dates, {})[0])

    def test_split_not_applied_twice(self):
        frame = self.frame.copy()
        frame.loc[frame.index[1], "Stock Splits"] = 4.
        table, _ = normalize(frame, "NVDA", self.dates, META)
        self.assertEqual(table.close_yahoo.tolist(), [101., 101.])
        self.assertEqual(table.split_ratio.tolist(), [0., 4.])

    def test_repeated_runs_snapshot_and_failed_run_preserves_latest(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            c = DataConfig(symbols=("QQQ", "QLD"), start="2024-07-03", end="2024-07-06", output_dir=tmp)
            good = lambda *_: (self.frame.copy(), META.copy())
            code, first = run(c, good)
            self.assertEqual(code, 0)
            pointer = Path(tmp) / "processed/latest.json"
            first_pointer = pointer.read_text()
            manifest = json.loads((first / "manifest.json").read_text())
            for relative, digest in manifest["files_sha256"].items():
                self.assertEqual(sha256(Path(tmp) / relative), digest)
            code, second = run(c, good)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_pointer, pointer.read_text())
            latest = pointer.read_text()
            def partial(symbol, *_):
                if symbol == "QLD":
                    raise RuntimeError("Simulated API outage")
                return self.frame.copy(), META.copy()
            code, failed = run(c, partial)
            self.assertEqual(code, 1)
            self.assertEqual(latest, pointer.read_text())
            self.assertFalse((Path(tmp) / "processed" / failed.name).exists())
            self.assertTrue((failed / "QQQ.csv").exists())

    def test_empty_provider_response_is_retried_and_fails(self):
        with patch("yfinance.Ticker") as ticker, patch("mag7.data.pipeline.time.sleep"):
            ticker.return_value.history.return_value = pd.DataFrame()
            with self.assertRaises(RuntimeError):
                fetch_yahoo("QQQ", "2024-07-03", "2024-07-06")
            self.assertEqual(ticker.return_value.history.call_count, 3)


if __name__ == "__main__":
    unittest.main()
