"""
modules/simulation/portfolio.py — Pure-Python portfolio tracker.

No database access, no Streamlit imports — only domain logic.

Classes:
    Position   — A single stock holding with average cost basis.
    Portfolio  — Cash + holdings container with buy/sell/valuation logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    """Represents a currently-held stock position.

    Attributes:
        stock_id:           Identifier matching StockCatalog.stock_id (e.g. "BBCA.JK").
        quantity:           Number of shares held (always > 0 when tracked).
        avg_purchase_price: Weighted average cost per share (in IDR).
        purchase_round:     Simulation round in which the *first* lot was bought.
    """

    stock_id: str
    quantity: int
    avg_purchase_price: float
    purchase_round: int


@dataclass
class SoldTrade:
    """Record of a completed (buy→sell) round-trip trade.

    Used by the analytics layer to compute disposition-effect and
    loss-aversion metrics without re-querying the database.
    """

    stock_id: str
    buy_round: int
    sell_round: int
    buy_price: float
    sell_price: float
    quantity: int

    @property
    def realized_pnl(self) -> float:
        """Net profit/loss for this trade (positive = gain)."""
        return (self.sell_price - self.buy_price) * self.quantity


class Portfolio:
    """Manages cash balance, stock holdings and realized P&L for one session.

    Args:
        initial_capital: Starting cash in IDR (default from config).
    """

    def __init__(self, initial_capital: float) -> None:
        self.cash: float = initial_capital
        self.initial_capital: float = initial_capital
        self.holdings: dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self._sold_trades: list[SoldTrade] = []

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def buy(self, stock_id: str, quantity: int, price: float, round_num: int) -> None:
        """Purchase *quantity* shares at *price* in round *round_num*.

        Raises:
            ValueError: if quantity ≤ 0, price ≤ 0, or cash is insufficient.
        """
        if quantity <= 0:
            raise ValueError(f"Buy quantity must be positive, got {quantity}.")
        if price <= 0:
            raise ValueError(f"Price must be positive, got {price}.")

        cost = quantity * price
        if cost > self.cash:
            raise ValueError(
                f"Insufficient cash: need Rp {cost:,.0f}, have Rp {self.cash:,.0f}."
            )

        self.cash -= cost

        if stock_id in self.holdings:
            pos = self.holdings[stock_id]
            total_qty = pos.quantity + quantity
            # Weighted average cost basis
            pos.avg_purchase_price = (
                pos.avg_purchase_price * pos.quantity + price * quantity
            ) / total_qty
            pos.quantity = total_qty
        else:
            self.holdings[stock_id] = Position(
                stock_id=stock_id,
                quantity=quantity,
                avg_purchase_price=price,
                purchase_round=round_num,
            )

    def sell(self, stock_id: str, quantity: int, price: float, round_num: int) -> float:
        """Sell *quantity* shares at *price* in round *round_num*.

        Returns:
            Realized P&L for this sale.

        Raises:
            ValueError: if quantity ≤ 0, price ≤ 0, or holdings are insufficient.
        """
        if quantity <= 0:
            raise ValueError(f"Sell quantity must be positive, got {quantity}.")
        if price <= 0:
            raise ValueError(f"Price must be positive, got {price}.")

        if stock_id not in self.holdings:
            raise ValueError(f"No holdings in {stock_id}.")
        pos = self.holdings[stock_id]
        if quantity > pos.quantity:
            raise ValueError(
                f"Cannot sell {quantity} shares of {stock_id}; only {pos.quantity} held."
            )

        proceeds = quantity * price
        self.cash += proceeds

        pnl = (price - pos.avg_purchase_price) * quantity
        self._realized_pnl += pnl

        trade = SoldTrade(
            stock_id=stock_id,
            buy_round=pos.purchase_round,
            sell_round=round_num,
            buy_price=pos.avg_purchase_price,
            sell_price=price,
            quantity=quantity,
        )
        self._sold_trades.append(trade)

        pos.quantity -= quantity
        if pos.quantity == 0:
            del self.holdings[stock_id]
        else:
            # Cost basis unchanged when partially selling
            pass

        return pnl

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------

    def get_total_value(self, current_prices: dict[str, float]) -> float:
        """Return total portfolio value = cash + market value of all holdings.

        Args:
            current_prices: Mapping of stock_id → current close price.
        """
        market_value = sum(
            pos.quantity * current_prices.get(pos.stock_id, pos.avg_purchase_price)
            for pos in self.holdings.values()
        )
        return self.cash + market_value

    def get_pnl(self, current_prices: dict[str, float]) -> dict[str, float]:
        """Return unrealized P&L per held position.

        Args:
            current_prices: Mapping of stock_id → current close price.

        Returns:
            Dict mapping stock_id → unrealized P&L (positive = gain).
        """
        result = {}
        for stock_id, pos in self.holdings.items():
            current = current_prices.get(stock_id, pos.avg_purchase_price)
            result[stock_id] = (current - pos.avg_purchase_price) * pos.quantity
        return result

    def get_realized_pnl(self) -> float:
        """Return total accumulated realized P&L across all closed trades."""
        return self._realized_pnl

    def get_sold_trades(self) -> list[SoldTrade]:
        """Return a copy of the list of completed sell trades."""
        return list(self._sold_trades)

    def get_open_positions(
        self, current_prices: dict[str, float], current_round: int
    ) -> list[dict]:
        """Return a list of open position summaries for the analytics layer.

        Returns:
            List of dicts with keys:
                stock_id, quantity, avg_price, current_price, unrealized_pnl,
                rounds_held (= current_round - purchase_round).
        """
        result = []
        for stock_id, pos in self.holdings.items():
            current = current_prices.get(stock_id, pos.avg_purchase_price)
            result.append({
                "stock_id": stock_id,
                "quantity": pos.quantity,
                "avg_price": pos.avg_purchase_price,
                "current_price": current,
                "unrealized_pnl": (current - pos.avg_purchase_price) * pos.quantity,
                "rounds_held": max(current_round - pos.purchase_round, 0),
            })
        return result
