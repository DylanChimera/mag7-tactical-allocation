"""Monthly benchmark with synthetic adjusted-price units, not live execution.

Run from project root:
  python -m mag7.backtest --self-test
  python -m mag7.backtest --config configs/backtest.toml --cost-bps 0
  python -m mag7.backtest --config configs/backtest.toml --cost-bps 5

No data download. Snapshot hash and passed/review audit are required by the CLI.
Each run gets its own directory. The CLI checks a separate zero-cost monthly
product formula. Costs are deducted on both buys and sells, including entry.
The optional 'none' rule implements buy-and-hold for independent verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import tomllib
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "QLD")
DEFAULT_TARGET_WEIGHTS = dict(zip(DEFAULT_SYMBOLS, [0.1] * 7 + [0.3]))
ENGINE_VERSION = "0.3.0-accounting-fix"


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")


@dataclass(frozen=True)
class BacktestConfig:
    snapshot_run_id: str = "20261012T220229517719Z_52db55"
    snapshot_root: str = "data/processed"
    data_root: str = "data"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    target_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TARGET_WEIGHTS))
    initial_capital: float = 100_000.0
    rebalance_rule: str = "monthly"
    cost_bps: float = 0.0
    open_column: str = "adj_open"
    close_column: str = "adj_close"

    def __post_init__(self):
        object.__setattr__(self, "symbols", tuple(self.symbols))
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be nonempty and unique")
        target = dict(self.target_weights)
        if set(target) != set(self.symbols):
            raise ValueError("target_weights must match symbols exactly")
        for symbol, value in target.items():
            _finite(value, f"weight {symbol}")
            if value < 0:
                raise ValueError("Short positions are not supported")
        total = math.fsum(target.values())
        if not math.isclose(total, 1., rel_tol=0., abs_tol=1e-12):
            raise ValueError("Target weights must sum to one")
        object.__setattr__(self, "target_weights", {s: w / total for s, w in target.items()})
        _finite(self.initial_capital, "initial_capital")
        _finite(self.cost_bps, "cost_bps")
        if self.initial_capital <= 0 or not 0 <= self.cost_bps < 10000:
            raise ValueError("Require capital > 0 and 0 <= cost_bps < 10000")
        if self.rebalance_rule not in ("monthly", "none"):
            raise ValueError("rebalance_rule must be monthly or none")
        if (self.open_column, self.close_column) != ("adj_open", "adj_close"):
            raise ValueError("This engine requires the coherent adj_open/adj_close pair")
        if (not self.snapshot_run_id or self.snapshot_run_id in (".", "..")
                or any(c in self.snapshot_run_id for c in ("/", "\\"))):
            raise ValueError("snapshot_run_id must be a single directory name")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coerce_config(config):
    if config is None:
        return BacktestConfig()
    if isinstance(config, BacktestConfig):
        return config
    if isinstance(config, Mapping):
        return BacktestConfig(**dict(config))
    raise TypeError("config must be a BacktestConfig, mapping, or None")


def validate_snapshot(config: BacktestConfig) -> Path:
    processed = Path(config.snapshot_root) / config.snapshot_run_id / "market_daily.csv"
    raw = Path(config.data_root) / "raw" / config.snapshot_run_id
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("run_id") != config.snapshot_run_id:
        raise ValueError("Snapshot ID mismatch")
    if manifest.get("status") not in ("passed", "review"):
        raise ValueError("Snapshot did not pass quality gates")
    for path, key in ((processed, f"processed/{config.snapshot_run_id}/market_daily.csv"),
                      (raw / "sessions.csv", f"raw/{config.snapshot_run_id}/sessions.csv")):
        expected = manifest.get("files_sha256", {}).get(key)
        if not expected:
            raise ValueError(f"Missing mandatory SHA-256: {key}")
        if _sha256(path) != expected:
            raise ValueError(f"SHA-256 mismatch: {path}")
    return processed


def _normalise_snapshot(frame: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    required = {"date", "symbol", config.open_column, config.close_column}
    if frame.empty or not required <= set(frame.columns):
        raise ValueError("Empty snapshot or missing required columns")
    df = frame[list(required)].copy()
    if df["date"].isna().any() or df["symbol"].isna().any():
        raise ValueError("Missing date or symbol")
    labels = df["date"].astype(str)
    if not labels.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("Dates must be ISO session labels YYYY-MM-DD")
    pd.to_datetime(labels, format="%Y-%m-%d", errors="raise")
    df["date"] = labels
    all_dates = set(labels)
    df = df[df.symbol.isin(config.symbols)].copy()
    if df.duplicated(["date", "symbol"]).any():
        raise ValueError("Duplicate date/symbol observations")
    if set(df.symbol) != set(config.symbols) or set(df.date) != all_dates:
        raise ValueError("Missing configured asset or session")
    if not df.groupby("date").size().eq(len(config.symbols)).all():
        raise ValueError("Assets do not cover identical sessions")
    for col in (config.open_column, config.close_column):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not df[col].map(lambda p: math.isfinite(p) and p > 0).all():
            raise ValueError(f"Invalid prices in {col}")
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


def _month_end_trigger(current_date, previous_date):
    return previous_date is not None and current_date[:7] != previous_date[:7]


def _portfolio_value(units, prices):
    return math.fsum(q * prices[s] for s, q in units.items())


def _trade_cost(amount, bps):
    return abs(amount) * bps / 10000.


def _execute_target(units, cash, prices, weights, cost_bps, trigger):
    """Self-financing rebalance using *one* opening valuation.

    Solve E + c * sum(abs(w_i E - h_i)) = V_before for post-cost equity E.
    Execute sells before buys. Cash starts at the real cash, not projected sales.
    """
    if set(prices) != set(weights) or set(units) - set(weights):
        raise ValueError("Position, price and target universes do not match")
    if cash < 0 or not math.isfinite(cash):
        raise ValueError("Starting cash must be nonnegative and finite")
    for s, p in prices.items():
        if not math.isfinite(p) or p <= 0 or not math.isfinite(units.get(s, 0.)) or units.get(s, 0.) < 0:
            raise ValueError("Invalid price or position")
    before = cash + _portfolio_value(units, prices)
    if not math.isfinite(before) or before <= 0:
        raise ValueError("Portfolio equity must be positive and finite")
    holdings = {s: units.get(s, 0.) * prices[s] for s in weights}
    rate = cost_bps / 10000.
    if rate == 0:
        equity = before
    else:
        lo, hi = 0., before
        for _ in range(100):
            mid = (lo + hi) / 2
            needed = mid + rate * math.fsum(abs(weights[s] * mid - holdings[s]) for s in weights)
            if needed <= before:
                lo = mid
            else:
                hi = mid
        equity = lo  # Feasible side of the root; rounding may leave tiny cash.
    target = {s: weights[s] * equity / prices[s] for s in weights}
    new_units = {s: units.get(s, 0.) for s in weights}
    deltas = {s: target[s] - new_units[s] for s in weights}
    tolerance = max(1e-9, before * 1e-12)
    new_cash = cash
    trades = []
    for side in ("sell", "buy"):
        for s, delta in deltas.items():
            if (side == "sell" and delta >= 0) or (side == "buy" and delta <= 0):
                continue
            amount = abs(delta) * prices[s]
            fee = amount * rate
            new_cash += amount - fee if side == "sell" else -amount - fee
            new_units[s] = target[s]
            if new_cash < -tolerance:
                raise ArithmeticError("Transaction would require borrowing")
            trades.append({"symbol": s, "direction": side, "trade_value": amount,
                "units": abs(delta), "price": prices[s], "fee": fee,
                "cash_after": new_cash, "trigger": trigger})
    # Only correct negative floating-point residue, never hide a material deficit.
    rounding_adjustment = -new_cash if -tolerance <= new_cash < 0 else 0.
    new_cash += rounding_adjustment
    after = new_cash + _portfolio_value(new_units, prices)
    fees = math.fsum(t["fee"] for t in trades)
    error = after + fees - before
    if abs(error) > tolerance:
        raise ArithmeticError(f"Self-financing violation: {error}")
    audit = {"trigger": trigger, "equity_before_open": before, "equity_after_open": after,
        "fees": fees, "cash_before": cash, "cash_after": new_cash,
        "conservation_error": error, "cash_rounding_adjustment": rounding_adjustment,
        "turnover_notional": math.fsum(t["trade_value"] for t in trades)}
    return new_units, new_cash, trades, audit


def _simulate_rebalance(units, cash, prev_close, current_open, target_weights, cost_bps):
    """Compatibility wrapper: prev_close is deliberately not used for sizing."""
    cfg = BacktestConfig(symbols=tuple(target_weights), target_weights=target_weights, cost_bps=cost_bps)
    q, c, trades, _ = _execute_target(units, cash, current_open, cfg.target_weights, cost_bps, "rebalance")
    return q, c, trades


def _initial_allocation(current_open, config):
    q, cash, trades, _ = _execute_target({}, config.initial_capital, current_open,
                                        config.target_weights, config.cost_bps, "initial")
    return q, cash, trades


def _simulate(frame, cfg):
    units = {}
    cash = cfg.initial_capital
    rows, transactions, audits = [], [], []
    previous_date = None
    for day_date, group in frame.groupby("date", sort=True):
        day = group.set_index("symbol")
        opens = {s: float(day.loc[s, cfg.open_column]) for s in cfg.symbols}
        closes = {s: float(day.loc[s, cfg.close_column]) for s in cfg.symbols}
        opening_equity = cash + _portfolio_value(units, opens)
        trigger = "initial" if previous_date is None else "rebalance"
        fees = 0.
        if previous_date is None or (cfg.rebalance_rule == "monthly" and _month_end_trigger(day_date, previous_date)):
            units, cash, trades, audit = _execute_target(units, cash, opens, cfg.target_weights, cfg.cost_bps, trigger)
            transactions.extend({**t, "date": day_date} for t in trades)
            audits.append({**audit, "date": day_date})
            fees = audit["fees"]
        holdings = {s: units[s] * closes[s] for s in cfg.symbols}
        value = cash + math.fsum(holdings.values())
        row = {"date": day_date, "cash": cash, "mark_to_market": value,
               "equity_before_open": opening_equity, "fees_today": fees,
               "gross_exposure": math.fsum(holdings.values()) / value}
        for s in cfg.symbols:
            row.update({f"units_{s}": units[s], f"holding_value_{s}": holdings[s], f"weight_{s}": holdings[s] / value})
        rows.append(row)
        previous_date = day_date
    daily = pd.DataFrame(rows)
    baseline = daily.mark_to_market.shift(1)
    baseline.iloc[0] = cfg.initial_capital
    daily["daily_return"] = daily.mark_to_market / baseline - 1
    daily["drawdown"] = daily.mark_to_market / daily.mark_to_market.cummax().clip(lower=cfg.initial_capital) - 1
    return daily, transactions, audits


def _reference_path(frame, cfg):
    """Independent period-product calculation, no cash ledger or trade routine."""
    opens = frame.pivot(index="date", columns="symbol", values=cfg.open_column).loc[:, list(cfg.symbols)]
    closes = frame.pivot(index="date", columns="symbol", values=cfg.close_column).loc[:, list(cfg.symbols)]
    weights = pd.Series(cfg.target_weights)
    anchor = opens.iloc[0]
    base = cfg.initial_capital
    output = []
    previous = None
    for d in opens.index:
        if previous is not None and cfg.rebalance_rule == "monthly" and d[:7] != previous[:7]:
            base *= float((weights * opens.loc[d] / anchor).sum())
            anchor = opens.loc[d]
        output.append(base * float((weights * closes.loc[d] / anchor).sum()))
        previous = d
    return pd.Series(output, index=opens.index, name="reference_equity")


def run_backtest(frame=None, config=None):
    cfg = _coerce_config(config)
    from_snapshot = frame is None
    if from_snapshot:
        frame = pd.read_csv(validate_snapshot(cfg))
    frame = _normalise_snapshot(frame, cfg)
    if from_snapshot:
        sessions = pd.read_csv(Path(cfg.data_root) / "raw" / cfg.snapshot_run_id / "sessions.csv")
        expected = sessions["date"].astype(str).tolist()
        if expected != sorted(frame.date.unique()):
            raise ValueError("Snapshot dates do not match the archived trading calendar")
    daily, trades, audits = _simulate(frame, cfg)
    zero_daily = daily if cfg.cost_bps == 0 else _simulate(frame, replace(cfg, cost_bps=0.))[0]
    reference = _reference_path(frame, cfg)
    zero_values = zero_daily.mark_to_market.to_numpy()
    errors = (pd.Series(zero_values, index=reference.index) - reference).abs()
    if (errors > 1e-8 * reference.abs().clip(lower=1.)).any():
        raise ArithmeticError("Zero-cost engine disagrees with independent period-product reference")
    final = float(daily.mark_to_market.iloc[-1])
    elapsed_days = (pd.Timestamp(daily.date.iloc[-1]) - pd.Timestamp(daily.date.iloc[0])).days
    years = elapsed_days / 365.25
    summary = {"engine_version": ENGINE_VERSION, "snapshot_run_id": cfg.snapshot_run_id,
        "initial_capital": cfg.initial_capital, "final_value": final,
        "net_return": final / cfg.initial_capital - 1,
        "gross_return": float(zero_values[-1]) / cfg.initial_capital - 1,
        "zero_cost_final_value": float(zero_values[-1]),
        "annualized_return": (final / cfg.initial_capital) ** (1 / years) - 1 if years > 0 else None,
        "annualized_volatility": float(daily.daily_return.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 else None,
        "max_drawdown": float(-daily.drawdown.min()),
        "cum_costs": math.fsum(t["fee"] for t in trades), "cost_bps": cfg.cost_bps,
        "start": daily.date.iloc[0], "end": daily.date.iloc[-1], "sessions": len(daily),
        "rebalance_events": sum(a["trigger"] == "rebalance" for a in audits),
        "transactions": len(trades), "independent_reference_max_abs_error": float(errors.max()),
        "max_conservation_error": max(abs(a["conservation_error"]) for a in audits),
        "rounding_adjustments": math.fsum(a["cash_rounding_adjustment"] for a in audits),
        "input_validation": "snapshot_hash_and_calendar" if from_snapshot else "in_memory_synthetic_or_caller_supplied"}
    return {"daily": daily, "transactions": trades, "rebalance_audit": audits,
            "reference": reference, "summary": summary}


def _self_test():
    """Executable regression suite; no internet or real snapshot needed."""
    import unittest
    import tempfile

    def data(dates, opens, closes=None):
        closes = opens if closes is None else closes
        return pd.DataFrame([{"date": d, "symbol": s, "adj_open": float(opens[j][i]), "adj_close": float(closes[j][i])}
            for j, d in enumerate(dates) for i, s in enumerate(("A", "B"))])

    def config(**kwargs):
        options = dict(symbols=("A", "B"), target_weights={"A": .5, "B": .5}, initial_capital=100.)
        options.update(kwargs)
        return BacktestConfig(**options)

    class AccountingTests(unittest.TestCase):
        def test_double_sale_regression(self):
            q, c, _ = _simulate_rebalance({"A": 6., "B": 4.}, 0., {"A": 10., "B": 10.},
                                         {"A": 10., "B": 10.}, {"A": .5, "B": .5}, 0.)
            self.assertAlmostEqual(c, 0.)
            self.assertEqual(q, {"A": 5., "B": 5.})
            self.assertAlmostEqual(c + _portfolio_value(q, {"A": 10., "B": 10.}), 100.)

        def test_overnight_gap_uses_opening_equity(self):
            f = data(["2024-01-31", "2024-02-01"], [[10, 10], [20, 10]])
            r = run_backtest(f, config())
            self.assertAlmostEqual(r["summary"]["final_value"], 150.)
            self.assertAlmostEqual(r["daily"].units_A.iloc[-1], 3.75)
            self.assertAlmostEqual(r["daily"].units_B.iloc[-1], 7.5)

        def test_sells_before_buys_and_cost_conservation(self):
            q, c, t, a = _execute_target({"A": 4., "B": 6.}, 0., {"A": 10., "B": 10.}, {"A": .5, "B": .5}, 50., "rebalance")
            self.assertEqual(t[0]["direction"], "sell")
            self.assertTrue(all(x["cash_after"] > -1e-9 for x in t))
            self.assertAlmostEqual(a["equity_after_open"] + a["fees"], 100.)
            self.assertAlmostEqual(q["A"] * 10, q["B"] * 10)

        def test_initial_fee_exact_solution(self):
            cfg = config(cost_bps=100.)
            q, c, t = _initial_allocation({"A": 10., "B": 10.}, cfg)
            self.assertAlmostEqual(_portfolio_value(q, {"A": 10., "B": 10.}), 100 / 1.01)
            self.assertAlmostEqual(c + sum(x["trade_value"] + x["fee"] for x in t), 100.)

        def test_flat_prices_with_and_without_costs(self):
            f = data(["2024-01-02", "2024-02-01", "2024-03-01"], [[10, 10]] * 3)
            for bps in (0., 5., 100.):
                r = run_backtest(f, config(cost_bps=bps))
                self.assertAlmostEqual(r["summary"]["final_value"], 100 / (1 + bps / 10000))
                self.assertTrue((r["daily"].cash >= 0).all())

        def test_drawdown_after_recovery(self):
            f = data(["2024-01-02", "2024-01-03", "2024-01-04"], [[10, 10], [5, 5], [11, 11]])
            self.assertAlmostEqual(run_backtest(f, config())["summary"]["max_drawdown"], .5)

        def test_first_day_loss_and_fees_included(self):
            f = data(["2024-01-02"], [[10, 10]], [[9, 9]])
            r = run_backtest(f, config(cost_bps=100.))
            self.assertAlmostEqual(r["daily"].daily_return.iloc[0], 90 / 1.01 / 100 - 1)
            self.assertAlmostEqual(r["summary"]["max_drawdown"], 1 - 90 / 1.01 / 100)
            self.assertIsNone(r["summary"]["annualized_return"])

        def test_buy_hold_direct(self):
            f = data(["2024-01-02", "2024-02-01", "2024-03-01"], [[10, 20], [20, 10], [30, 40]])
            r = run_backtest(f, config(rebalance_rule="none"))
            self.assertAlmostEqual(r["summary"]["final_value"], 50 * 3 + 50 * 2)
            self.assertEqual(r["summary"]["rebalance_events"], 0)
            self.assertEqual(r["daily"].units_A.nunique(), 1)

        def test_monthly_reference_and_future_invariance(self):
            f = data(["2024-01-02", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"],
                     [[10, 20], [13, 18], [15, 16], [12, 25], [18, 22]])
            a = run_backtest(f, config())
            g = f.copy(); g.loc[g.date == "2024-03-01", ["adj_open", "adj_close"]] *= 3
            b = run_backtest(g, config())
            pd.testing.assert_frame_equal(a["daily"].iloc[:-1], b["daily"].iloc[:-1])
            expected = 100 * (.5 * 15 / 10 + .5 * 16 / 20) * (.5 * 18 / 15 + .5 * 22 / 16)
            self.assertAlmostEqual(a["summary"]["final_value"], expected)
            self.assertEqual(a["summary"]["rebalance_events"], 2)

        def test_invalid_prices_and_missing_rows(self):
            f = data(["2024-01-02", "2024-01-03"], [[10, 10], [11, 12]])
            for bad in (0., -1., float("nan"), float("inf")):
                g = f.copy(); g.loc[0, "adj_open"] = bad
                with self.assertRaises(ValueError): run_backtest(g, config())
            for g in (f.iloc[:-1], pd.concat([f, f.iloc[:1]])):
                with self.assertRaises(ValueError): run_backtest(g, config())

        def test_invalid_config(self):
            for changes in ({"cost_bps": float("nan")}, {"cost_bps": -1.},
                            {"target_weights": {"A": -.5, "B": 1.5}}, {"symbols": ("A", "A")},
                            {"initial_capital": float("inf")}, {"open_column": "open_yahoo"}):
                with self.assertRaises(ValueError): config(**changes)

        def test_hash_required_and_tamper_rejected(self):
            with tempfile.TemporaryDirectory() as tmp:
                cfg = config(data_root=tmp, snapshot_root=str(Path(tmp) / "processed"), snapshot_run_id="test")
                raw = Path(tmp) / "raw/test"; raw.mkdir(parents=True)
                out = Path(tmp) / "processed/test"; out.mkdir(parents=True)
                data(["2024-01-02"], [[10, 10]]).to_csv(out / "market_daily.csv", index=False)
                pd.DataFrame({"date": ["2024-01-02"]}).to_csv(raw / "sessions.csv", index=False)
                manifest = {"run_id": "test", "status": "passed", "files_sha256": {}}
                (raw / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError): validate_snapshot(cfg)
                manifest["files_sha256"] = {"processed/test/market_daily.csv": _sha256(out / "market_daily.csv"),
                    "raw/test/sessions.csv": _sha256(raw / "sessions.csv")}
                (raw / "manifest.json").write_text(json.dumps(manifest))
                self.assertAlmostEqual(run_backtest(None, cfg)["summary"]["final_value"], 100.)
                (out / "market_daily.csv").write_text("modified")
                with self.assertRaises(ValueError): validate_snapshot(cfg)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AccountingTests))
    return result.wasSuccessful()


def _load_toml_config(path):
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def main():
    parser = argparse.ArgumentParser(description="Corrected synthetic-unit B0 backtest")
    parser.add_argument("--config", type=Path, default=Path("configs/backtest.toml"))
    parser.add_argument("--cost-bps", type=float)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/backtest"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(0 if _self_test() else 1)
    payload = _load_toml_config(args.config)
    options = dict(payload["backtest"])
    options.update(snapshot_run_id=payload["snapshot"]["run_id"],
                   snapshot_root=payload["snapshot"].get("processed_root", "data/processed"),
                   data_root=payload["snapshot"].get("data_root", "data"))
    if args.cost_bps is not None:
        options["cost_bps"] = args.cost_bps
    cfg = BacktestConfig(**options)
    result = run_backtest(None, cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:6]
    output = args.output_dir / cfg.snapshot_run_id / f"{cfg.rebalance_rule}_cost{cfg.cost_bps:g}bps_{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    result["daily"].to_csv(output / "daily.csv", index=False)
    pd.DataFrame(result["transactions"]).to_csv(output / "transactions.csv", index=False)
    pd.DataFrame(result["rebalance_audit"]).to_csv(output / "rebalance_audit.csv", index=False)
    result["reference"].to_csv(output / "zero_cost_reference.csv", index_label="date")
    conventions = {
        "pricing": "Synthetic adjusted units; opening prices for sizing and fills, closing marks",
        "cash": "Non-interest-bearing; no account borrowing. QLD still has embedded daily leverage",
        "execution": "Fixed target weights, idealized exact opening fills; sales before purchases",
        "fees": "Proportional on both sides; initial investment = capital/(1+fee_rate)",
        "gross_return": "Separate zero-cost simulation, not net equity plus nominal fees",
        "annualization": "CAGR uses elapsed calendar days/365.25; undefined for one session",
        "volatility": "Sample std of daily returns times sqrt(252); first entry session is partial",
        "drawdown": "Close-based running peaks including initial pre-fee capital; positive maximum loss",
        "gross_exposure": "Holdings market value / equity; does not look through QLD leverage",
        "data_limit": "Retrospective Mag7 selection; adjusted historical data not point-in-time"}
    snapshot_path = Path(cfg.snapshot_root) / cfg.snapshot_run_id / "market_daily.csv"
    result["summary"].update(run_id=stamp, conventions=conventions, effective_config=asdict(cfg),
        input_sha256=_sha256(snapshot_path), engine_sha256=_sha256(Path(__file__)),
        python=platform.python_version(), pandas=pd.__version__)
    (output / "summary.json").write_text(json.dumps(result["summary"], indent=2, allow_nan=False), encoding="utf-8")
    (output / "effective_config.json").write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    (output / "config.original.toml").write_text(args.config.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({**result["summary"], "output_dir": str(output)}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
