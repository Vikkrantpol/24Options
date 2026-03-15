"""
Risk management module.
Real-time portfolio risk computation, limit checking, and kill-switch logic.
"""

from __future__ import annotations
from .models import (
    ConcreteLeg, RiskLimits, RiskSummary, StrategyInstance, Position,
)
from .pricing_engine import compute_strategy_greeks


class RiskManager:
    """Monitors portfolio risk and enforces limits."""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.kill_switch_triggered = False
        self.alerts: list[str] = []

    def evaluate(
        self,
        strategies: list[StrategyInstance],
        spot: float,
        total_capital: float = 1_000_000,
        risk_free_rate: float = 0.10,
    ) -> RiskSummary:
        """Evaluate current portfolio risk against configured limits."""
        self.alerts = []
        self.kill_switch_triggered = False
        summary = RiskSummary()
        summary.active_strategies = len([s for s in strategies if s.status == "active"])

        # Aggregate Greeks across all active strategies
        for strat in strategies:
            if strat.status != "active":
                continue
            greeks = compute_strategy_greeks(
                spot=spot,
                legs=strat.legs,
                risk_free_rate=risk_free_rate,
                underlying=strat.underlying,
            )
            summary.net_delta += greeks.delta
            summary.net_gamma += greeks.gamma
            summary.net_vega += greeks.vega
            summary.net_theta += greeks.theta
            summary.total_unrealized_pnl += strat.unrealized_pnl
            summary.total_realized_pnl += strat.realized_pnl

        # Round
        summary.net_delta = round(summary.net_delta, 4)
        summary.net_gamma = round(summary.net_gamma, 6)
        summary.net_vega = round(summary.net_vega, 4)
        summary.net_theta = round(summary.net_theta, 4)

        # Check limits
        if abs(summary.net_delta) > self.limits.max_portfolio_delta:
            self.alerts.append(
                f"⚠️ DELTA LIMIT: Net delta {summary.net_delta:.2f} exceeds ±{self.limits.max_portfolio_delta}"
            )

        if abs(summary.net_gamma) > self.limits.max_portfolio_gamma:
            self.alerts.append(
                f"⚠️ GAMMA LIMIT: Net gamma {summary.net_gamma:.4f} exceeds ±{self.limits.max_portfolio_gamma}"
            )

        if abs(summary.net_vega) > self.limits.max_portfolio_vega:
            self.alerts.append(
                f"⚠️ VEGA LIMIT: Net vega {summary.net_vega:.2f} exceeds ±{self.limits.max_portfolio_vega}"
            )

        total_loss = summary.total_unrealized_pnl + summary.total_realized_pnl
        if total_loss < -self.limits.max_portfolio_loss:
            self.alerts.append(
                f"🚨 PORTFOLIO LOSS LIMIT: Total P&L ₹{total_loss:,.2f} exceeds max loss ₹{self.limits.max_portfolio_loss:,.2f}"
            )
            if self.limits.kill_switch_enabled:
                self.kill_switch_triggered = True
                self.alerts.append("🔴 KILL SWITCH TRIGGERED — All positions should be flattened")

        # Per-strategy loss check
        for strat in strategies:
            if strat.status == "active" and strat.unrealized_pnl < -self.limits.max_single_strategy_loss:
                self.alerts.append(
                    f"⚠️ STRATEGY LOSS: '{strat.template_name}' (ID: {strat.id[:8]}) "
                    f"unrealized P&L ₹{strat.unrealized_pnl:,.2f} exceeds single-strategy limit"
                )

        # Margin utilization (simplified)
        summary.margin_utilization_pct = round(
            (summary.total_margin_used / total_capital * 100) if total_capital > 0 else 0, 2
        )
        if summary.margin_utilization_pct > self.limits.max_margin_utilization_pct:
            self.alerts.append(
                f"⚠️ MARGIN: Utilization {summary.margin_utilization_pct:.1f}% exceeds "
                f"{self.limits.max_margin_utilization_pct:.1f}% limit"
            )

        summary.alerts = self.alerts
        summary.kill_switch_triggered = self.kill_switch_triggered
        return summary

    def reset_kill_switch(self):
        """Manual reset of kill switch after review."""
        self.kill_switch_triggered = False
        self.alerts = [a for a in self.alerts if "KILL SWITCH" not in a]
