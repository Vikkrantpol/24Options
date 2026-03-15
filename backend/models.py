"""
Core data models for the 24 Options Strategies Platform.
Covers instruments, strategy templates, instances, orders, positions,
backtesting configs, and risk limits.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime
import uuid


# ──────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OptionRight(str, Enum):
    CE = "CE"  # Call
    PE = "PE"  # Put
    FUT = "FUT"  # Future contract or underlying stock

class InstrumentType(str, Enum):
    STOCK = "STOCK"
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    OPTION = "OPTION"

class OptionStyle(str, Enum):
    EUROPEAN = "EUROPEAN"
    AMERICAN = "AMERICAN"

class StrategyCategory(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"
    HEDGE = "Hedge"

class PayoffType(str, Enum):
    LIMITED_RISK_LIMITED_REWARD = "Limited Risk / Limited Reward"
    LIMITED_RISK_UNLIMITED_REWARD = "Limited Risk / Unlimited Reward"
    UNLIMITED_RISK_LIMITED_REWARD = "Unlimited Risk / Limited Reward"
    UNLIMITED_RISK_UNLIMITED_REWARD = "Unlimited Risk / Unlimited Reward"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


# ──────────────────────────────────────────────────────────────
# Instrument
# ──────────────────────────────────────────────────────────────

class Instrument(BaseModel):
    """Represents a tradeable instrument (stock, index, future, or option)."""
    symbol: str
    underlying_id: str
    instrument_type: InstrumentType
    # Option-specific fields
    strike: Optional[float] = None
    expiry: Optional[str] = None       # ISO date string
    right: Optional[OptionRight] = None
    style: OptionStyle = OptionStyle.EUROPEAN
    tick_size: float = 0.05
    lot_size: int = 65  # Default NIFTY lot


# ──────────────────────────────────────────────────────────────
# Strategy Templates (parametrized definitions)
# ──────────────────────────────────────────────────────────────

class LegTemplate(BaseModel):
    """Defines one leg of a strategy relative to the ATM strike."""
    side: Side
    right: OptionRight                  # CE or PE
    qty_multiplier: int = 1             # e.g., 2 for ratio spreads
    strike_offset: int = 0              # 0 = ATM, +1 = ATM+1 step OTM, -1 = ITM
    expiry_offset: int = 0              # 0 = current expiry, +1 = next expiry (for calendars)
    is_stock_leg: bool = False          # True for covered call / protective put stock leg


class StrategyTemplate(BaseModel):
    """A parametrized strategy definition — one of the canonical 24."""
    id: int
    name: str
    category: StrategyCategory
    subcategory: str                    # e.g., "Vertical Spread", "Straddle"
    legs: list[LegTemplate]
    description: str                    # Human-readable short description
    primary_view: str                   # e.g., "Moderately bullish"
    payoff_type: PayoffType
    max_risk: str                       # e.g., "Net premium paid" or "Unlimited"
    max_reward: str                     # e.g., "Unlimited" or "Net premium received"
    breakeven_formula: str              # e.g., "Strike A + Net Premium"
    tags: list[str] = []                # e.g., ["income", "weekly", "theta"]


# ──────────────────────────────────────────────────────────────
# Concrete Leg & Strategy Instance (resolved at a specific time)
# ──────────────────────────────────────────────────────────────

class ConcreteLeg(BaseModel):
    """A fully resolved leg with actual strikes and premiums."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    side: Side
    right: OptionRight
    strike: float
    premium: float
    qty: int                            # Actual quantity (lots × lot_size)
    expiry: str                         # Actual expiry date
    iv: Optional[float] = None          # Implied volatility at entry
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None


class ExitRule(BaseModel):
    """Defines when to exit a strategy instance."""
    rule_type: Literal["time", "pnl", "greek", "manual"]
    description: str
    # For time-based: days before expiry
    days_before_expiry: Optional[int] = None
    # For PnL-based: profit/loss thresholds as % of max
    target_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    # For Greek-based: threshold values
    delta_threshold: Optional[float] = None


class StrategyInstance(BaseModel):
    """A concrete instance of a strategy at a specific point in time."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template_id: int                    # References StrategyTemplate.id
    template_name: str
    underlying: str                     # e.g., "NIFTY", "BANKNIFTY"
    spot_at_entry: float
    legs: list[ConcreteLeg]
    entry_time: datetime = Field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    exit_rules: list[ExitRule] = []
    status: Literal["active", "closed", "expired"] = "active"
    tags: list[str] = []
    # Computed fields
    net_premium: float = 0.0            # Net credit (+) or debit (-)
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


# ──────────────────────────────────────────────────────────────
# Orders, Fills, Positions
# ──────────────────────────────────────────────────────────────

class Order(BaseModel):
    """An order placed for a single leg."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_instance_id: str
    leg_id: str
    symbol: str
    side: Side
    right: OptionRight
    strike: float
    qty: int
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    placed_at: datetime = Field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    slippage: float = 0.0


class Position(BaseModel):
    """A currently held position."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_instance_id: str
    symbol: str
    side: Side
    right: OptionRight
    strike: float
    qty: int
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0


# ──────────────────────────────────────────────────────────────
# Greeks (aggregated view)
# ──────────────────────────────────────────────────────────────

class GreeksSummary(BaseModel):
    """Aggregated Greeks for a strategy or portfolio."""
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    rho: float = 0.0
    iv_avg: float = 0.0


# ──────────────────────────────────────────────────────────────
# Backtesting
# ──────────────────────────────────────────────────────────────

class BacktestConfig(BaseModel):
    """Configuration for running a backtest."""
    strategy_template_id: int
    underlying: str = "NIFTY"
    start_date: str                     # ISO date
    end_date: str                       # ISO date
    initial_capital: float = 1_000_000
    lot_size: int = 65
    num_lots: int = 1
    slippage_pct: float = 0.1
    brokerage_per_order: float = 20.0
    strike_step: int = 100              # Strike interval (50 for NIFTY, 100 for BANKNIFTY)
    # Entry filters
    iv_percentile_min: Optional[float] = None
    iv_percentile_max: Optional[float] = None
    # Exit rules
    days_before_expiry_exit: int = 1
    target_profit_pct: Optional[float] = 50.0
    stop_loss_pct: Optional[float] = 100.0


class BacktestMetrics(BaseModel):
    """Summary performance metrics from a backtest."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    avg_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    cagr: float = 0.0
    avg_holding_days: float = 0.0
    profit_factor: float = 0.0


class BacktestResult(BaseModel):
    """Full result of a backtest run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: list[dict] = []       # [{date, equity, pnl}]
    trades: list[dict] = []             # [{entry_date, exit_date, pnl, ...}]
    run_time_seconds: float = 0.0
    completed_at: datetime = Field(default_factory=datetime.now)


# ──────────────────────────────────────────────────────────────
# Risk Management
# ──────────────────────────────────────────────────────────────

class RiskLimits(BaseModel):
    """Configurable risk limits for the portfolio."""
    max_portfolio_delta: float = 500.0
    max_portfolio_gamma: float = 100.0
    max_portfolio_vega: float = 5000.0
    max_single_strategy_loss: float = 50000.0
    max_portfolio_loss: float = 200000.0
    max_margin_utilization_pct: float = 80.0
    kill_switch_enabled: bool = True


class RiskSummary(BaseModel):
    """Current risk state of the portfolio."""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_vega: float = 0.0
    net_theta: float = 0.0
    total_margin_used: float = 0.0
    margin_utilization_pct: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    active_strategies: int = 0
    alerts: list[str] = []
    kill_switch_triggered: bool = False


# ──────────────────────────────────────────────────────────────
# API Request / Response Models
# ──────────────────────────────────────────────────────────────

class PayoffRequest(BaseModel):
    spot_price: float
    legs: list[ConcreteLeg]


class GreeksRequest(BaseModel):
    spot_price: float
    risk_free_rate: float = 0.10       # NSE standard 10%
    legs: list[ConcreteLeg]
    underlying: Optional[str] = None


class ScenarioRequest(BaseModel):
    """What-if scenario: shift spot, IV, or time."""
    spot_price: float
    legs: list[ConcreteLeg]
    delta_spot_pct: float = 0.0        # e.g., +5 means +5%
    delta_iv_points: float = 0.0       # e.g., -3 means -3 IV points
    delta_days: int = 0                # e.g., +10 means 10 days forward
    risk_free_rate: float = 0.10
    underlying: Optional[str] = None


class ResolveRequest(BaseModel):
    """Resolve a strategy template into concrete legs using current market data."""
    template_id: int
    underlying: str = "NIFTY"
    spot_price: float = 22000
    strike_step: int = 100
    lot_size: int = 65
    num_lots: int = 1
    expiry: str = ""                   # ISO date, empty = next weekly


class AIChatRequest(BaseModel):
    query: str
    context: Optional[str] = None
    current_legs: list[ConcreteLeg] = []


class AIStrategyRequest(BaseModel):
    """Natural language → strategy JSON."""
    description: str                   # e.g., "NIFTY range-bound, high IV, safest income"
    underlying: str = "NIFTY"
    spot_price: float = 22000
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
