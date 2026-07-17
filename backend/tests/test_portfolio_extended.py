"""
tests/test_portfolio_extended.py — Additional Portfolio edge-case tests.

Extends test_simulation.py with scenarios not covered there.
"""

import pytest

from modules.simulation.portfolio import Portfolio

INITIAL = 10_000_000.0


def test_get_open_positions_structure():
    """get_open_positions returns list with expected keys."""
    p = Portfolio(INITIAL)
    p.buy("BBCA.JK", 10, 9000.0, 1)
    positions = p.get_open_positions({"BBCA.JK": 9100.0}, current_round=3)
    assert len(positions) == 1
    pos = positions[0]
    assert pos["stock_id"] == "BBCA.JK"
    assert pos["quantity"] == 10
    assert pos["avg_price"] == 9000.0
    assert pos["current_price"] == 9100.0
    assert pos["unrealized_pnl"] == pytest.approx(1000.0)
    assert pos["rounds_held"] == 2  # round 3 - purchase round 1


def test_partial_sell_preserves_avg_cost_basis():
    """Selling half the position leaves avg_purchase_price unchanged."""
    p = Portfolio(INITIAL)
    p.buy("ANTM.JK", 20, 2000.0, 1)
    p.sell("ANTM.JK", 10, 2200.0, 3)

    assert "ANTM.JK" in p.holdings
    assert p.holdings["ANTM.JK"].quantity == 10
    # Cost basis should still be 2000 (buy price), not sell price
    assert p.holdings["ANTM.JK"].avg_purchase_price == pytest.approx(2000.0)


def test_multiple_buys_single_sell():
    """Three separate buys then one full sell records correct realized PnL."""
    p = Portfolio(INITIAL)
    # Buy 10 @ 9000, 10 @ 9200, 10 @ 9400 → avg = 9200
    p.buy("BBCA.JK", 10, 9000.0, 1)
    p.buy("BBCA.JK", 10, 9200.0, 2)
    p.buy("BBCA.JK", 10, 9400.0, 3)
    avg = p.holdings["BBCA.JK"].avg_purchase_price
    assert avg == pytest.approx(9200.0)

    pnl = p.sell("BBCA.JK", 30, 9500.0, 5)
    expected_pnl = (9500.0 - 9200.0) * 30
    assert pnl == pytest.approx(expected_pnl)
    assert "BBCA.JK" not in p.holdings


def test_get_open_positions_empty_when_no_holdings():
    """get_open_positions on empty portfolio returns empty list."""
    p = Portfolio(INITIAL)
    positions = p.get_open_positions({}, current_round=1)
    assert positions == []


def test_sold_trades_record_correct_rounds():
    """sell() records buy_round and sell_round from the buy call and sell call."""
    p = Portfolio(INITIAL)
    p.buy("GOTO.JK", 100, 70.0, 3)
    p.sell("GOTO.JK", 100, 80.0, 11)
    trades = p.get_sold_trades()
    assert len(trades) == 1
    assert trades[0].buy_round == 3
    assert trades[0].sell_round == 11
    assert trades[0].realized_pnl == pytest.approx(1000.0)
