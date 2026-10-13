import math

import pandas as pd

from mag7.backtest import BacktestConfig, run_backtest


def make_matrix(prices_by_symbol, dates):
    rows = []
    for d in dates:
        for symbol, prices in prices_by_symbol.items():
            rows.append({
                "date": d,
                "symbol": symbol,
                "adj_open": prices[d][0],
                "adj_close": prices[d][1],
            })
    return pd.DataFrame(rows)


def test_units_are_preserved_without_transactions():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    prices = {
        "AAPL": {"2024-01-01": (100.0, 100.0), "2024-01-02": (110.0, 110.0), "2024-01-03": (120.0, 120.0)},
        "QLD": {"2024-01-01": (50.0, 50.0), "2024-01-02": (60.0, 60.0), "2024-01-03": (75.0, 75.0)},
    }
    df = make_matrix(prices, dates)
    config = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    result = run_backtest(df, config)
    rows = result["daily"].sort_values("date").reset_index(drop=True)
    assert rows.loc[0, "units_AAPL"] == 5.0
    assert rows.loc[0, "units_QLD"] == 10.0
    assert rows.loc[1, "units_AAPL"] == 5.0
    assert rows.loc[1, "units_QLD"] == 10.0
    assert rows.loc[1, "weight_AAPL"] != rows.loc[0, "weight_AAPL"]


def test_overnight_gap_belongs_to_previous_units():
    df = pd.DataFrame([
        {"date": "2024-01-31", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-02-01", "symbol": "AAPL", "adj_open": 120.0, "adj_close": 120.0},
        {"date": "2024-01-31", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
        {"date": "2024-02-01", "symbol": "QLD", "adj_open": 60.0, "adj_close": 60.0},
    ])
    config = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    result = run_backtest(df, config)
    row = result["daily"].iloc[-1]
    assert row["mark_to_market"] > 1000.0
    assert row["holding_value_AAPL"] > 0.0


def test_flat_prices_keep_capital_without_costs_and_reduce_with_costs():
    df = pd.DataFrame([
        {"date": "2024-01-01", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-02", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-03", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-01", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
        {"date": "2024-01-02", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
        {"date": "2024-01-03", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
    ])
    cfg0 = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    cfg5 = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=5.0)
    zero = run_backtest(df, cfg0)
    fee = run_backtest(df, cfg5)
    assert zero["daily"].iloc[-1]["mark_to_market"] == 1000.0
    assert fee["daily"].iloc[-1]["mark_to_market"] < 1000.0
    assert fee["summary"]["cum_costs"] > 0.0


def test_rebalance_without_costs_preserves_total_value():
    df = pd.DataFrame([
        {"date": "2024-01-31", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-02-01", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-02-02", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-31", "symbol": "QLD", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-02-01", "symbol": "QLD", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-02-02", "symbol": "QLD", "adj_open": 100.0, "adj_close": 100.0},
    ])
    cfg = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    result = run_backtest(df, cfg)
    final_value = result["daily"].iloc[-1]["mark_to_market"]
    assert abs(final_value - 1000.0) < 1e-9


def test_rebalance_does_not_count_sale_proceeds_twice():
    df = pd.DataFrame([
        {"date": "2024-01-31", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 120.0},
        {"date": "2024-01-31", "symbol": "QLD", "adj_open": 100.0, "adj_close": 80.0},
        {"date": "2024-02-01", "symbol": "AAPL", "adj_open": 120.0, "adj_close": 120.0},
        {"date": "2024-02-01", "symbol": "QLD", "adj_open": 80.0, "adj_close": 80.0},
    ])
    cfg = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    result = run_backtest(df, cfg)
    row = result["daily"].iloc[-1]
    assert abs(row["mark_to_market"] - 1000.0) < 1e-9
    assert abs(row["cash"]) < 1e-9


def test_no_leverage_after_cost_payment():
    df = pd.DataFrame([
        {"date": "2024-01-01", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-02", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-03", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-01", "symbol": "QLD", "adj_open": 10.0, "adj_close": 10.0},
        {"date": "2024-01-02", "symbol": "QLD", "adj_open": 10.0, "adj_close": 10.0},
        {"date": "2024-01-03", "symbol": "QLD", "adj_open": 10.0, "adj_close": 10.0},
    ])
    cfg = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=5.0)
    result = run_backtest(df, cfg)
    rows = result["daily"]
    assert (rows["cash"] >= -1e-9).all()
    assert (rows["gross_exposure"] <= 1.0 + 1e-9).all()


def test_future_prices_do_not_change_past_trades():
    df = pd.DataFrame([
        {"date": "2024-01-01", "symbol": "AAPL", "adj_open": 100.0, "adj_close": 100.0},
        {"date": "2024-01-02", "symbol": "AAPL", "adj_open": 200.0, "adj_close": 200.0},
        {"date": "2024-01-03", "symbol": "AAPL", "adj_open": 300.0, "adj_close": 300.0},
        {"date": "2024-01-01", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
        {"date": "2024-01-02", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
        {"date": "2024-01-03", "symbol": "QLD", "adj_open": 50.0, "adj_close": 50.0},
    ])
    cfg = BacktestConfig(symbols=["AAPL", "QLD"], target_weights={"AAPL": 0.5, "QLD": 0.5}, initial_capital=1000.0, rebalance_rule="monthly", cost_bps=0.0)
    result = run_backtest(df, cfg)
    initial_trade = result["transactions"][0]
    assert initial_trade["symbol"] == "AAPL"
    assert initial_trade["units"] == 5.0
    assert initial_trade["trade_value"] == 500.0
