"""
Paper trading engine.
Simulated OMS for testing strategies without real money.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
from .models import (
    ConcreteLeg, StrategyInstance, StrategyTemplate, Order, Position,
    OrderStatus, Side, OptionRight,
)
from .pricing_engine import compute_strategy_metrics, bs_price, infer_dividend_yield
from .db import PortfolioDB

_EXPIRY_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y")


def _parse_expiry(expiry: str | None):
    if not expiry:
        return None
    for fmt in _EXPIRY_FORMATS:
        try:
            return datetime.strptime(expiry, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(expiry)[:10]).date()
    except Exception:
        return None


def _normalize_expiry(expiry: str | None) -> str:
    parsed = _parse_expiry(expiry)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def _normalize_underlying(underlying: str | None) -> str:
    u = str(underlying or "").upper()
    if "BANK" in u:
        return "BANKNIFTY"
    if "NIFTY" in u:
        return "NIFTY"
    return u


def _resolve_leg_dte(expiry: str, fallback_dte: int) -> int:
    fallback = max(int(fallback_dte), 0)
    exp_date = _parse_expiry(expiry)
    if not exp_date:
        return fallback
    return max((exp_date - datetime.now().date()).days, 0)


class PaperTradingEngine:
    """In-memory paper trading engine with simulated order execution, persisted via SQLite."""

    def __init__(self, initial_capital: float = 1_000_000, lot_size: int = 65):
        self.db = PortfolioDB()
        self.initial_capital = initial_capital
        
        stats = self.db.get_portfolio_summary_stats()
        self.capital = initial_capital + stats["realized_pnl"]
        
        self.lot_size = lot_size
        self.strategies: list[StrategyInstance] = self.db.load_active_strategies()
        self.orders: list[Order] = []
        self.positions: list[Position] = []
        self.trade_history: list[dict] = []
        
        # Hydrate positions from active loaded strategies
        for strat in self.strategies:
            for leg in strat.legs:
                self.positions.append(Position(
                    strategy_instance_id=strat.id,
                    symbol=f"{strat.underlying}:{leg.strike}{leg.right.value}",
                    side=leg.side, right=leg.right, strike=leg.strike,
                    qty=leg.qty, avg_price=leg.premium, current_price=leg.premium
                ))

    def open_strategy(
        self,
        template: StrategyTemplate,
        legs: list[ConcreteLeg],
        underlying: str,
        spot_price: float,
        tags: list[str] | None = None,
    ) -> StrategyInstance:
        """Open a new strategy instance with the given concrete legs."""
        net_premium = sum(
            (-leg.premium if leg.side == Side.BUY else leg.premium) * leg.qty
            for leg in legs
        )

        instance = StrategyInstance(
            template_id=template.id,
            template_name=template.name,
            underlying=underlying,
            spot_at_entry=spot_price,
            legs=legs,
            net_premium=net_premium,
            tags=tags or [],
        )

        # Simulate order fills
        for leg in legs:
            order = Order(
                strategy_instance_id=instance.id,
                leg_id=leg.id,
                symbol=f"{underlying}:{leg.strike}{leg.right.value}",
                side=leg.side,
                right=leg.right,
                strike=leg.strike,
                qty=leg.qty,
                status=OrderStatus.FILLED,
                filled_at=datetime.now(),
                fill_price=leg.premium,
                slippage=0.0,
            )
            self.orders.append(order)

            # Create position
            pos = Position(
                strategy_instance_id=instance.id,
                symbol=order.symbol,
                side=leg.side,
                right=leg.right,
                strike=leg.strike,
                qty=leg.qty,
                avg_price=leg.premium,
                current_price=leg.premium,
            )
            self.positions.append(pos)

        self.strategies.append(instance)
        self.db.save_strategy(instance)
        return instance

    def close_strategy(self, strategy_id: str, spot_price: float, risk_free_rate: float = 0.10) -> dict:
        """Close an active strategy at current market prices."""
        strat = next((s for s in self.strategies if s.id == strategy_id and s.status == "active"), None)
        if not strat:
            return {"error": "Strategy not found or already closed"}

        realized_pnl = 0.0
        q = infer_dividend_yield(strat.underlying, spot_price)
        for leg in strat.legs:
            iv = leg.iv if leg.iv and leg.iv > 0 else 0.18
            T = _resolve_leg_dte(leg.expiry, 1) / 365.0
            exit_price = bs_price(spot_price, leg.strike, risk_free_rate, iv, T, leg.right.value, q=q)

            if leg.side == Side.BUY:
                pnl = (exit_price - leg.premium) * leg.qty
            else:
                pnl = (leg.premium - exit_price) * leg.qty

            realized_pnl += pnl

        strat.status = "closed"
        strat.exit_time = datetime.now()
        strat.realized_pnl = round(realized_pnl, 2)

        # Remove from positions
        self.positions = [p for p in self.positions if p.strategy_instance_id != strategy_id]

        # Record trade
        trade = {
            "strategy_id": strategy_id,
            "template_name": strat.template_name,
            "underlying": strat.underlying,
            "entry_time": strat.entry_time.isoformat(),
            "exit_time": strat.exit_time.isoformat(),
            "spot_at_entry": strat.spot_at_entry,
            "spot_at_exit": spot_price,
            "realized_pnl": strat.realized_pnl,
            "num_legs": len(strat.legs),
        }
        self.trade_history.append(trade)
        self.capital += realized_pnl
        self.db.update_strategy_pnl(strat)

        return trade

    def update_mtm(
        self,
        spot_price: float,
        risk_free_rate: float = 0.10,
        default_dte: int = 7,
        chain: list[dict[str, Any]] | None = None,
        underlying: str | None = None,
        chain_expiry: str | None = None,
    ):
        """Mark-to-market all active positions."""
        quote_map: dict[tuple[float, str], float] = {}
        target_underlying = _normalize_underlying(underlying) if underlying else ""
        chain_expiry_norm = _normalize_expiry(chain_expiry)
        if chain:
            for row in chain:
                strike = float(row.get("strike", 0) or 0)
                if strike <= 0:
                    continue
                for right in ("CE", "PE"):
                    opt = row.get(right, {}) or {}
                    ltp = float(opt.get("ltp", 0) or opt.get("premium", 0) or 0)
                    if ltp > 0:
                        quote_map[(round(strike, 4), right)] = ltp

        for strat in self.strategies:
            if strat.status != "active":
                continue
            if target_underlying and _normalize_underlying(strat.underlying) != target_underlying:
                continue
            unrealized = 0.0
            q = infer_dividend_yield(strat.underlying, spot_price)
            for leg in strat.legs:
                right = leg.right.value
                quote_key = (round(float(leg.strike), 4), right)
                leg_expiry_norm = _normalize_expiry(leg.expiry)
                can_use_chain_quote = (
                    bool(quote_map)
                    and (
                        not chain_expiry_norm
                        or not leg_expiry_norm
                        or leg_expiry_norm == chain_expiry_norm
                    )
                )
                current_price = quote_map.get(quote_key) if can_use_chain_quote else None

                if current_price is None:
                    iv = leg.iv if leg.iv and leg.iv > 0 else 0.18
                    T = _resolve_leg_dte(leg.expiry, default_dte) / 365.0
                    current_price = bs_price(spot_price, leg.strike, risk_free_rate, iv, T, right, q=q)

                if leg.side == Side.BUY:
                    leg_unrealized = (current_price - leg.premium) * leg.qty
                else:
                    leg_unrealized = (leg.premium - current_price) * leg.qty

                unrealized += leg_unrealized

                # Update position
                for pos in self.positions:
                    if pos.strategy_instance_id == strat.id and pos.strike == leg.strike and pos.right == leg.right:
                        pos.current_price = round(current_price, 2)
                        pos.unrealized_pnl = round(leg_unrealized, 2)

            strat.unrealized_pnl = round(unrealized, 2)
            self.db.update_strategy_pnl(strat)

    def get_portfolio_summary(self) -> dict:
        """Get a summary of the paper trading portfolio."""
        stats = self.db.get_portfolio_summary_stats()
        active = [s for s in self.strategies if s.status == "active"]
        total_unrealized = sum(s.unrealized_pnl for s in active)
        total_realized = stats["realized_pnl"]

        return {
            "capital": round(self.initial_capital + total_realized + total_unrealized, 2),
            "initial_capital": self.initial_capital,
            "total_pnl": round(total_unrealized + total_realized, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(total_realized, 2),
            "active_strategies": len(active),
            "closed_strategies": stats["closed_count"],
            "total_orders": len(self.orders),
            "positions": len(self.positions),
        }
