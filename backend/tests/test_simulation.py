"""
tests/test_simulation.py — Unit tests for Portfolio and SimulationEngine.
"""

import pytest

from modules.simulation.portfolio import Portfolio

INITIAL = 10_000_000.0


# ---------------------------------------------------------------------------
# Portfolio tests
# ---------------------------------------------------------------------------

def make_portfolio(capital=INITIAL):
    return Portfolio(capital)


def test_portfolio_buy_reduces_cash():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 9000.0, round_num=1)
    assert p.cash == INITIAL - 100 * 9000.0


def test_portfolio_buy_creates_holding():
    p = make_portfolio()
    p.buy("BBCA.JK", 50, 8000.0, round_num=1)
    assert "BBCA.JK" in p.holdings
    assert p.holdings["BBCA.JK"].quantity == 50
    assert p.holdings["BBCA.JK"].avg_purchase_price == 8000.0


def test_portfolio_buy_weighted_average_cost():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 8000.0, round_num=1)
    p.buy("BBCA.JK", 100, 10000.0, round_num=3)
    pos = p.holdings["BBCA.JK"]
    assert pos.quantity == 200
    assert pos.avg_purchase_price == pytest.approx(9000.0)


def test_portfolio_sell_increases_cash():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 9000.0, round_num=1)
    cash_after_buy = p.cash
    p.sell("BBCA.JK", 50, 10000.0, round_num=5)
    assert p.cash == pytest.approx(cash_after_buy + 50 * 10000.0)


def test_portfolio_sell_removes_holding_when_fully_sold():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 9000.0, round_num=1)
    p.sell("BBCA.JK", 100, 9000.0, round_num=5)
    assert "BBCA.JK" not in p.holdings


def test_portfolio_sell_returns_pnl():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 8000.0, round_num=1)
    pnl = p.sell("BBCA.JK", 100, 9000.0, round_num=5)
    assert pnl == pytest.approx(100 * (9000.0 - 8000.0))


def test_cannot_buy_exceeds_cash():
    p = Portfolio(100_000.0)   # small capital
    with pytest.raises(ValueError, match="Insufficient cash"):
        p.buy("GOTO.JK", 10_000, 100.0, round_num=1)  # 1,000,000 > 100,000


def test_cannot_sell_exceeds_holdings():
    p = make_portfolio()
    p.buy("BBCA.JK", 10, 9000.0, round_num=1)
    with pytest.raises(ValueError, match="Cannot sell"):
        p.sell("BBCA.JK", 100, 9000.0, round_num=5)


def test_cannot_sell_unowned_stock():
    p = make_portfolio()
    with pytest.raises(ValueError, match="No holdings"):
        p.sell("TLKM.JK", 1, 3000.0, round_num=3)


def test_portfolio_value_calculation():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 9000.0, round_num=1)
    p.buy("TLKM.JK", 200, 3000.0, round_num=2)
    prices = {"BBCA.JK": 10000.0, "TLKM.JK": 3500.0}
    expected = p.cash + 100 * 10000.0 + 200 * 3500.0
    assert p.get_total_value(prices) == pytest.approx(expected)


def test_portfolio_pnl_positive_for_price_increase():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 8000.0, round_num=1)
    pnl = p.get_pnl({"BBCA.JK": 9000.0})
    assert pnl["BBCA.JK"] == pytest.approx(100 * 1000.0)


def test_portfolio_pnl_negative_for_price_decrease():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 10000.0, round_num=1)
    pnl = p.get_pnl({"BBCA.JK": 8000.0})
    assert pnl["BBCA.JK"] == pytest.approx(-200_000.0)


def test_realized_pnl_accumulates():
    p = make_portfolio()
    p.buy("BBCA.JK", 100, 8000.0, round_num=1)
    p.buy("TLKM.JK", 100, 3000.0, round_num=2)
    p.sell("BBCA.JK", 100, 9000.0, round_num=5)   # +100,000
    p.sell("TLKM.JK", 100, 2500.0, round_num=8)   # -50,000
    assert p.get_realized_pnl() == pytest.approx(50_000.0)


def test_sold_trades_recorded():
    p = make_portfolio()
    p.buy("BBCA.JK", 50, 8000.0, round_num=1)
    p.sell("BBCA.JK", 50, 9000.0, round_num=4)
    trades = p.get_sold_trades()
    assert len(trades) == 1
    assert trades[0].stock_id == "BBCA.JK"
    assert trades[0].sell_price == 9000.0
    assert trades[0].buy_price == 8000.0


def test_buy_zero_quantity_raises():
    p = make_portfolio()
    with pytest.raises(ValueError):
        p.buy("BBCA.JK", 0, 9000.0, round_num=1)


def test_sell_zero_quantity_raises():
    p = make_portfolio()
    p.buy("BBCA.JK", 10, 9000.0, round_num=1)
    with pytest.raises(ValueError):
        p.sell("BBCA.JK", 0, 9000.0, round_num=2)
