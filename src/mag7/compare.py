"""Compare six portfolios on a common post-warmup sample. No downloads.
Requires corrected mag7.backtest ENGINE_VERSION 0.3.0-accounting-fix.
Run: python -m mag7.compare --cost-bps 0 5
"""
from __future__ import annotations
import argparse
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from . import backtest as bt

MAG7 = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA")
SYMBOLS = MAG7 + ("QLD", "QQQ")
STRATEGIES = ("qqq_buy_hold", "qld_buy_hold", "mag7_monthly", "b0_monthly", "static25_monthly", "trend200_monthly")


def allocation(name, bullish):
    w = dict.fromkeys(SYMBOLS, 0.)
    if name in ("qqq_buy_hold", "qld_buy_hold"):
        w["QQQ" if name == "qqq_buy_hold" else "QLD"] = 1.
    elif name == "mag7_monthly":
        w.update({s: 1 / 7 for s in MAG7})
    elif name == "static25_monthly":
        w.update({s: .1 for s in MAG7})
        w["QLD"] = .25  # Total risky weights = .95; .05 stays as actual cash.
    elif name in ("b0_monthly", "trend200_monthly"):
        w.update({s: .1 for s in MAG7})
        w["QLD"] = .3 if name == "b0_monthly" or bullish else 0.
    else:
        raise ValueError(f"Unknown strategy: {name}")
    return w


def prepare(frame, window=200):
    if type(window) is not int or window < 2:
        raise ValueError("window must be an integer >= 2")
    cfg = bt.BacktestConfig(symbols=SYMBOLS, target_weights=allocation("qqq_buy_hold", True))
    frame = bt._normalise_snapshot(frame, cfg)
    opens = frame.pivot(index="date", columns="symbol", values="adj_open").loc[:, list(SYMBOLS)]
    closes = frame.pivot(index="date", columns="symbol", values="adj_close").loc[:, list(SYMBOLS)]
    if len(closes) <= window:
        raise ValueError("Not enough observations after warmup")
    ma = closes.QQQ.rolling(window, min_periods=window).mean()
    # The opening decision at date t uses *only* the preceding close and MA.
    signals = pd.DataFrame({"decision_date": pd.Series(closes.index, index=closes.index).shift(1),
        "qqq_previous_close": closes.QQQ.shift(1), "previous_ma": ma.shift(1)})
    signals["bullish"] = signals.qqq_previous_close > signals.previous_ma
    return opens.iloc[window:], closes.iloc[window:], signals.iloc[window:]


def reference_path(opens, closes, signals, name, capital):
    """Independent zero-cost interval product, including uninvested cash weight."""
    result = []
    base = capital
    anchor = None
    old_w = None
    previous = None
    for d in opens.index:
        execute = previous is None or (name not in ("qqq_buy_hold", "qld_buy_hold") and d[:7] != previous[:7])
        if execute:
            if previous is not None:
                base *= 1 - old_w.sum() + float((old_w * opens.loc[d] / anchor).sum())
            old_w = pd.Series(allocation(name, bool(signals.loc[d, "bullish"])))
            anchor = opens.loc[d]
        result.append(base * (1 - old_w.sum() + float((old_w * closes.loc[d] / anchor).sum())))
        previous = d
    return pd.Series(result, index=opens.index)


def simulate(opens, closes, signals, name, capital=100000., cost_bps=5.):
    bt.BacktestConfig(initial_capital=capital, cost_bps=cost_bps)
    cash, units = capital, {}
    rows, trades, audits = [], [], []
    previous = None
    for d in opens.index:
        prices = opens.loc[d].to_dict()
        execute = previous is None or (name not in ("qqq_buy_hold", "qld_buy_hold") and d[:7] != previous[:7])
        if execute:
            target = allocation(name, bool(signals.loc[d, "bullish"]))
            # Uninvested weight remains actual cash: .05 for static25, .30 for trend risk-off.
            # Existing post-fee equity equation works with sum(weights) <= 1.
            if not 0 <= math.fsum(target.values()) <= 1 + 1e-12:
                raise ValueError("Invalid risky-asset allocation")
            units, cash, ts, audit = bt._execute_target(units, cash, prices, target, cost_bps,
                                                       "initial" if previous is None else "rebalance")
            fees = math.fsum(t["fee"] for t in ts)
            equity = cash + bt._portfolio_value(units, prices)
            tolerance = max(1e-8, equity * 1e-10)
            if abs(cash - (1 - math.fsum(target.values())) * equity) > tolerance:
                raise ArithmeticError("Cash allocation does not match target")
            if any(abs(units[s] * prices[s] - target[s] * equity) > tolerance for s in SYMBOLS):
                raise ArithmeticError("Opening weights do not match targets")
            trades.extend({**t, "date": d} for t in ts)
            audits.append({**audit, "date": d, "decision_date": signals.loc[d, "decision_date"],
                "bullish": bool(signals.loc[d, "bullish"]), "qld_target": target["QLD"],
                "cash_target": 1 - math.fsum(target.values())})
        else:
            fees = 0.
        holdings = {s: units[s] * float(closes.loc[d, s]) for s in SYMBOLS}
        equity = cash + math.fsum(holdings.values())
        row = {"date": d, "mark_to_market": equity, "cash": cash, "fees_today": fees,
            "decision_date": signals.loc[d, "decision_date"],
            "bullish_previous_close": bool(signals.loc[d, "bullish"]),
            "executed_rebalance": execute, "qld_weight": holdings["QLD"] / equity,
            "cash_weight": cash / equity}
        for s in SYMBOLS:
            row[f"units_{s}"] = units[s]
            row[f"holding_value_{s}"] = holdings[s]
        rows.append(row)
        previous = d
    daily = pd.DataFrame(rows)
    denominator = daily.mark_to_market.shift(1)
    denominator.iloc[0] = capital
    daily["daily_return"] = daily.mark_to_market / denominator - 1
    daily["drawdown"] = daily.mark_to_market / daily.mark_to_market.cummax().clip(lower=capital) - 1
    days = (pd.Timestamp(daily.date.iloc[-1]) - pd.Timestamp(daily.date.iloc[0])).days
    final = float(daily.mark_to_market.iloc[-1])
    summary = {"strategy": name, "cost_bps": cost_bps, "start": daily.date.iloc[0],
        "end": daily.date.iloc[-1], "sessions": len(daily), "initial_capital": capital,
        "final_value": final, "total_return": final / capital - 1,
        "annualized_return": (final / capital)**(365.25 / days) - 1 if days > 0 else None,
        "annualized_volatility": float(daily.daily_return.std(ddof=1) * math.sqrt(252)) if len(daily)>1 else None,
        "max_drawdown": float(-daily.drawdown.min()), "cum_costs": math.fsum(t["fee"] for t in trades),
        "transactions": len(trades), "rebalance_events": len(audits)-1,
        "mean_qld_weight": float(daily.qld_weight.mean()),
        "mean_cash_weight": float(daily.cash_weight.mean()),
        "fraction_sessions_holding_qld": float(daily.units_QLD.gt(0).mean()),
        "traded_notional": math.fsum(t["trade_value"] for t in trades),
        "max_conservation_error": max(abs(a["conservation_error"]) for a in audits)}
    return daily, trades, audits, summary


def compare(frame, capital=100000., costs=(0., 5.), window=200):
    opens, closes, signals = prepare(frame, window)
    output = {}
    for name in STRATEGIES:
        ref = reference_path(opens, closes, signals, name, capital)
        zero = simulate(opens, closes, signals, name, capital, 0.)
        error = (zero[0].mark_to_market.to_numpy() - ref).abs()
        if (error > ref.abs().clip(lower=1.) * 1e-8).any():
            raise ArithmeticError(f"Independent reference disagrees for {name}")
        for bps in dict.fromkeys(costs):
            daily, trades, audit, summary = zero if bps == 0 else simulate(opens, closes, signals, name, capital, bps)
            summary = {**summary, "zero_cost_final_value": float(ref.iloc[-1]),
                "independent_reference_max_abs_error": float(error.max()), "warmup_sessions": window}
            output[(name, bps)] = (daily, trades, audit, summary)
    return output, signals


def self_test():
    import unittest
    def fixture():
        dates = ["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01",
                 "2024-02-02", "2024-02-29", "2024-03-01", "2024-03-04"]
        qqq = [12, 11, 10, 15, 16, 17, 18, 19]
        rows = []
        for i,d in enumerate(dates):
            for s in SYMBOLS:
                value = qqq[i] if s == "QQQ" else 10.+i/10
                rows.append(dict(date=d,symbol=s,adj_open=value,adj_close=value))
        return pd.DataFrame(rows)
    class Tests(unittest.TestCase):
        def test_common_sample_and_reference(self):
            r, signals = compare(fixture(), window=3)
            self.assertEqual(len(r), 12)
            for d,t,a,s in r.values():
                self.assertEqual(s["start"], "2024-02-01")
                self.assertLess(s["independent_reference_max_abs_error"], 1e-7)
                self.assertTrue((d.cash >= 0).all())
        def test_lag_not_current_close(self):
            o,c,s = prepare(fixture(), 3)
            self.assertFalse(bool(s.loc["2024-02-01", "bullish"]))
            r = simulate(o,c,s,"trend200_monthly",100.,0.)
            self.assertAlmostEqual(r[0].cash.iloc[0], 30.)
            self.assertEqual(r[0].units_QLD.iloc[1], 0.) # Daily bullish signal is ignored until March.
            self.assertGreater(r[0].units_QLD.iloc[-1], 0.)
        def test_partial_cash_target_with_fees(self):
            o,c,s = prepare(fixture(),3)
            r = simulate(o,c,s,"trend200_monthly",100.,5.)
            eq=100/(1+.7*.0005)
            self.assertAlmostEqual(r[0].cash.iloc[0], .3*eq)
            self.assertLess(r[3]["max_conservation_error"],1e-8)
        def test_future_does_not_change_past(self):
            f=fixture(); g=f.copy()
            g.loc[g.date=="2024-03-04",["adj_open","adj_close"]]*=2
            a,_=compare(f,window=3);b,_=compare(g,window=3)
            for key in a:
                pd.testing.assert_frame_equal(a[key][0].iloc[:-1],b[key][0].iloc[:-1])
        def test_buyhold_units_constant(self):
            r,_=compare(fixture(),window=3)
            d,t,a,s=r[("qqq_buy_hold",0.)]
            self.assertEqual(d.units_QQQ.nunique(),1)
            self.assertEqual(s["rebalance_events"],0)
        def test_qld_buyhold_direct_and_costs(self):
            f = fixture()
            r,_ = compare(f, window=3)
            qld = f[f.symbol == "QLD"].reset_index(drop=True)
            expected = 100000. * qld.adj_close.iloc[-1] / qld.adj_open.iloc[3]
            for bps in (0.,5.):
                daily,trades,audit,summary = r[("qld_buy_hold",bps)]
                self.assertAlmostEqual(summary["final_value"], expected / (1+bps/10000))
                self.assertEqual(daily.units_QLD.nunique(),1)
                self.assertEqual(summary["rebalance_events"],0)
                self.assertEqual(len(trades),1)
                self.assertAlmostEqual(summary["mean_qld_weight"],1.)
        def test_static25_ignores_signal_and_has_cash_after_fees(self):
            self.assertEqual(allocation("static25_monthly", True), allocation("static25_monthly", False))
            o,c,s = prepare(fixture(),3)
            changed=s.copy(); changed["bullish"]=~changed.bullish
            for bps in (0.,5.):
                a=simulate(o,c,s,"static25_monthly",100.,bps)
                b=simulate(o,c,changed,"static25_monthly",100.,bps)
                pd.testing.assert_series_equal(a[0].mark_to_market,b[0].mark_to_market)
                self.assertEqual(a[1],b[1])
                initial_equity=100/(1+.95*bps/10000)
                self.assertAlmostEqual(a[0].cash.iloc[0],.05*initial_equity)
                for event in a[2]:
                    self.assertAlmostEqual(event["cash_after"],.05*event["equity_after_open"])
                    self.assertAlmostEqual(event["qld_target"],.25)
        def test_static25_cash_drifts_between_rebalances(self):
            dates=["2024-01-02","2024-01-03","2024-02-01"]
            prices=pd.DataFrame([[10.]*len(SYMBOLS),[11.]*len(SYMBOLS),[12.]*len(SYMBOLS)],index=dates,columns=SYMBOLS)
            signals=pd.DataFrame({"bullish":[False,True,False],"decision_date":["2023-12-29","2024-01-02","2024-01-31"]},index=dates)
            d,t,a,summary=simulate(prices,prices,signals,"static25_monthly",100.,0.)
            self.assertAlmostEqual(d.mark_to_market.iloc[1],109.5)
            self.assertAlmostEqual(d.cash.iloc[1],5.)
            self.assertAlmostEqual(d.cash_weight.iloc[1],5/109.5)
            self.assertAlmostEqual(d.mark_to_market.iloc[-1],119.)
            self.assertAlmostEqual(d.cash.iloc[-1],5.95)
            self.assertAlmostEqual(d.qld_weight.iloc[-1],.25)
        def test_warmup_required(self):
            with self.assertRaises(ValueError): prepare(fixture(),200)
    return unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests)).wasSuccessful()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot-run-id",default="20261012T220229517719Z_52db55")
    p.add_argument("--data-root",type=Path,default=Path("data"))
    p.add_argument("--output-dir",type=Path,default=Path("reports/comparison"))
    p.add_argument("--initial-capital",type=float,default=100000.)
    p.add_argument("--cost-bps",type=float,nargs="+",default=[0.,5.])
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if bt.ENGINE_VERSION != "0.3.0-accounting-fix":
        p.error("Use the corrected 0.3.0-accounting-fix backtest.py first")
    if args.self_test:
        sys.exit(0 if self_test() else 1)
    cfg=bt.BacktestConfig(snapshot_run_id=args.snapshot_run_id,data_root=str(args.data_root),
        snapshot_root=str(args.data_root/"processed"),symbols=SYMBOLS,
        target_weights=allocation("qqq_buy_hold",True),initial_capital=args.initial_capital)
    path=bt.validate_snapshot(cfg)
    frame=pd.read_csv(path)
    calendar=pd.read_csv(args.data_root/"raw"/args.snapshot_run_id/"sessions.csv")
    if calendar.date.astype(str).tolist()!=sorted(frame.date.astype(str).unique()):
        raise ValueError("Trading calendar mismatch")
    results,signals=compare(frame,args.initial_capital,args.cost_bps)
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:6]
    dest=args.output_dir/args.snapshot_run_id/run_id
    dest.mkdir(parents=True,exist_ok=False)
    summaries=[]
    for (name,bps),(daily,trades,audit,summary) in results.items():
        folder=dest/f"{name}_cost{bps:g}bps";folder.mkdir()
        daily.to_csv(folder/"daily.csv",index=False)
        pd.DataFrame(trades).to_csv(folder/"transactions.csv",index=False)
        pd.DataFrame(audit).to_csv(folder/"rebalance_audit.csv",index=False)
        summaries.append(summary)
    table=pd.DataFrame(summaries)
    table.to_csv(dest/"comparison.csv",index=False)
    table.to_json(dest/"comparison.json",orient="records",indent=2)
    signals.to_csv(dest/"signals.csv",index_label="execution_date")
    manifest={"snapshot_run_id":args.snapshot_run_id,"run_id":run_id,"input_sha256":bt._sha256(path),
        "backtest_sha256":bt._sha256(Path(bt.__file__)),"compare_sha256":bt._sha256(Path(__file__)),
        "initial_capital":args.initial_capital,"cost_bps":args.cost_bps,"warmup_sessions":200,
        "pandas":pd.__version__,"python":sys.version,"signal":"prior QQQ adjusted close > prior SMA200",
        "schedule":"initial opening after 200 prior sessions, then first session of month",
        "cash":"unremunerated; static25 target 5%, trend risk-off target 30%; no fees on cash itself",
        "static25_selection":"25% chosen retrospectively from observed trend mean exposure, not optimized or an untouched test",
        "limits":["Exploratory in-sample comparison, not a new untouched test",
                  "Retrospective universe selection", "Idealized opening fills and synthetic units",
                  "Risk is not matched across strategies; lower drawdown alone does not prove alpha",
                  "No daily/weekly timing or volatility targeting yet"]}
    (dest/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(table[["strategy","cost_bps","start","final_value","annualized_return","annualized_volatility","max_drawdown"]].to_string(index=False))
    print(f"Outputs: {dest}")

if __name__=="__main__":
    main()
