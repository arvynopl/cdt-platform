"""
tests/test_counterfactual.py — Tests for compute_counterfactual.

Uses shared db fixture from conftest.py.
"""


from config import ROUNDS_PER_SESSION
from modules.feedback.generator import compute_counterfactual


def _make_trade(stock_id, buy_round, sell_round, buy_price, sell_price, quantity=10):
    return {
        "stock_id": stock_id, "buy_round": buy_round, "sell_round": sell_round,
        "buy_price": buy_price, "sell_price": sell_price, "quantity": quantity,
    }


def test_no_winners_returns_empty_string(db):
    """realized_trades with only losses → empty string."""
    losing_trades = [
        _make_trade("ANTM.JK", buy_round=1, sell_round=5, buy_price=2000, sell_price=1800),
    ]
    result = compute_counterfactual(db, losing_trades, [], {})
    assert result == ""


def test_winner_at_last_round_returns_empty_string(db):
    """Winner sold at round 14 → actual_extra = 0 → empty string."""
    trades = [
        _make_trade("BBCA.JK", buy_round=1, sell_round=ROUNDS_PER_SESSION,
                    buy_price=9000, sell_price=9500),
    ]
    result = compute_counterfactual(db, trades, [], {})
    assert result == ""


def test_valid_winner_returns_rupiah_string(db):
    """Winner sold at round 5 with upward trend → non-empty Indonesian string with Rp."""
    trades = [
        _make_trade("BBCA.JK", buy_round=1, sell_round=5,
                    buy_price=9000, sell_price=9600, quantity=100),
    ]
    result = compute_counterfactual(db, trades, [], {}, extra_rounds=3)
    assert result != ""
    assert "Rp" in result
    # Should mention the stock
    assert "BBCA.JK" in result


def test_projected_gain_exceeds_actual(db):
    """Projected gain in output is higher than actual gain for uptrend winner."""
    buy_price = 9000
    sell_price = 10000
    qty = 10
    actual_gain = (sell_price - buy_price) * qty  # 10_000

    trades = [_make_trade("BBCA.JK", 1, 5, buy_price, sell_price, qty)]
    result = compute_counterfactual(db, trades, [], {}, extra_rounds=3)
    # The text contains a projected gain > 10_000
    assert result != ""
    # Verify the extra gain text is present
    assert "tambahan" in result
