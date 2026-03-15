"""
Black-Scholes pricing engine with Greeks computation,
payoff calculator, and scenario analysis for the 24 Options Strategies Platform.
"""

from __future__ import annotations
import math
from datetime import datetime, date
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from .models import ConcreteLeg, GreeksSummary, Side, OptionRight


# ──────────────────────────────────────────────────────────────
# Black-Scholes Core
# ──────────────────────────────────────────────────────────────

_EXPIRY_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y")


def _parse_expiry_date(expiry: str | None) -> date | None:
    """Parse supported expiry string formats into a date."""
    if not expiry:
        return None
    for fmt in _EXPIRY_FORMATS:
        try:
            return datetime.strptime(expiry, fmt).date()
        except ValueError:
            continue
    # Fallback for ISO-like strings containing timestamps
    try:
        return datetime.fromisoformat(expiry[:10]).date()
    except Exception:
        return None


def _resolve_leg_dte(expiry: str | None, fallback_dte: int) -> int:
    """Resolve leg-specific DTE from expiry; fallback when unavailable."""
    fallback = max(int(fallback_dte), 0)
    exp_date = _parse_expiry_date(expiry)
    if not exp_date:
        return fallback
    return max((exp_date - datetime.now().date()).days, 0)


def infer_dividend_yield(underlying: str | None = None, spot: float | None = None) -> float:
    """
    Infer a dividend yield proxy for index options.
    Uses explicit underlying when available; otherwise falls back to legacy spot heuristic.
    """
    if underlying:
        u = str(underlying).upper()
        if "NIFTY" in u and "BANK" not in u:
            return 0.012
        return 0.0
    if spot is not None and spot > 10000:
        # Backward-compatible fallback when underlying symbol is unavailable.
        return 0.012
    return 0.0

def _d1(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """d1 parameter of Black-Scholes."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0
    return (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """d2 parameter of Black-Scholes."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0
    return _d1(S, K, r, sigma, T, q) - sigma * math.sqrt(T)


def bs_call_price(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """Black-Scholes European call price."""
    if T <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return max(S - K, 0.0)
    d1 = _d1(S, K, r, sigma, T, q)
    d2 = _d2(S, K, r, sigma, T, q)
    return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_put_price(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """Black-Scholes European put price."""
    if T <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return max(K - S, 0.0)
    d1 = _d1(S, K, r, sigma, T, q)
    d2 = _d2(S, K, r, sigma, T, q)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def bs_price(S: float, K: float, r: float, sigma: float, T: float, right: str, q: float = 0.0) -> float:
    """Unified Black-Scholes pricer."""
    if right.upper() == "FUT":
        return S
    if right.upper() in ("CE", "CALL", "C"):
        return bs_call_price(S, K, r, sigma, T, q)
    else:
        return bs_put_price(S, K, r, sigma, T, q)


# ──────────────────────────────────────────────────────────────
# Greeks (per-leg analytical)
# ──────────────────────────────────────────────────────────────

def delta(S: float, K: float, r: float, sigma: float, T: float, right: str, q: float = 0.0) -> float:
    """Option delta."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        if right.upper() in ("CE", "CALL", "C"):
            if abs(S - K) < 1e-4: return 0.5
            return 1.0 if S > K else 0.0
        else:
            if abs(S - K) < 1e-4: return -0.5
            return -1.0 if S < K else 0.0
    d1 = _d1(S, K, r, sigma, T, q)
    if right.upper() in ("CE", "CALL", "C"):
        return math.exp(-q * T) * norm.cdf(d1)
    else:
        return math.exp(-q * T) * (norm.cdf(d1) - 1.0)


def gamma(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """Option gamma (same for calls and puts)."""
    # BUG FIX: Gamma explodes to infinity for ATM options at 0 DTE.
    # Previous code returned 0.0 for everything.
    if T <= 1e-6:
        return 0.0 if abs(S - K) > 1e-2 else 1e9  # Theoretical infinity for ATM at expiry
    if sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0

    d1 = _d1(S, K, r, sigma, max(T, 1e-5), q)  # Prevent division by zero
    return math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))


def vega(S: float, K: float, r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """Option vega (per 1% move in IV). Same for calls and puts."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0
    d1 = _d1(S, K, r, sigma, T, q)
    return math.exp(-q * T) * S * norm.pdf(d1) * math.sqrt(T) / 100.0  # per 1% IV


def theta(S: float, K: float, r: float, sigma: float, T: float, right: str, q: float = 0.0) -> float:
    """Option theta (per calendar day)."""
    # BUG FIX: Theta is massive near 0 DTE. Don't suppress it to 0.0 unless S/K/sigma are invalid.
    if sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0
        
    T_safe = max(T, 1e-5) # Prevent division by zero for d1/d2 and term1
    d1 = _d1(S, K, r, sigma, T_safe, q)
    d2 = _d2(S, K, r, sigma, T_safe, q)
    
    term1 = -(math.exp(-q * T_safe) * S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T_safe))
    if right.upper() in ("CE", "CALL", "C"):
        term2 = -r * K * math.exp(-r * T_safe) * norm.cdf(d2)
        term3 = q * S * math.exp(-q * T_safe) * norm.cdf(d1)
        res = term1 + term2 + term3
    else:
        term2 = r * K * math.exp(-r * T_safe) * norm.cdf(-d2)
        term3 = -q * S * math.exp(-q * T_safe) * norm.cdf(-d1)
        res = term1 + term2 + term3
        
    # Return theta per calendar day
    return res / 365.0


def rho(S: float, K: float, r: float, sigma: float, T: float, right: str, q: float = 0.0) -> float:
    """Option rho (per 1% move in interest rate)."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 1e-6 or K <= 1e-6:
        return 0.0
    d2 = _d2(S, K, r, sigma, T, q)
    if right.upper() in ("CE", "CALL", "C"):
        return K * T * math.exp(-r * T) * norm.cdf(d2) / 100.0
    else:
        return -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100.0


def compute_leg_greeks(
    S: float, K: float, r: float, sigma: float, T: float, right: str, side: str, qty: int, q: float = 0.0
) -> dict:
    """Compute all Greeks for a single leg, accounting for side and quantity."""
    multiplier = qty if side.upper() == "BUY" else -qty
    if right.upper() == "FUT":
        return {
            "delta": 1.0 * multiplier,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rho": 0.0,
        }
    return {
        "delta": delta(S, K, r, sigma, T, right, q) * multiplier,
        # Gamma flips sign for short options.
        "gamma": gamma(S, K, r, sigma, T, q) * multiplier,
        "vega": vega(S, K, r, sigma, T, q) * multiplier,
        "theta": theta(S, K, r, sigma, T, right, q) * multiplier,
        "rho": rho(S, K, r, sigma, T, right, q) * multiplier,
    }


# ──────────────────────────────────────────────────────────────
# Portfolio Greeks (aggregate)
# ──────────────────────────────────────────────────────────────

def compute_strategy_greeks(
    spot: float,
    legs: list[ConcreteLeg],
    risk_free_rate: float = 0.10,
    default_iv: float = 0.18,
    default_dte: int = 7,
    leg_dte_overrides: dict[str, int] | None = None,
    dividend_yield: float | None = None,
    underlying: str | None = None,
) -> GreeksSummary:
    """Compute aggregated Greeks for all legs in a strategy."""
    summary = GreeksSummary()
    iv_values = []

    q = float(dividend_yield) if dividend_yield is not None else infer_dividend_yield(underlying, spot)

    for leg in legs:
        iv = leg.iv if leg.iv and leg.iv > 0 else default_iv
        leg_dte = (
            max(int(leg_dte_overrides[leg.id]), 0)
            if leg_dte_overrides and leg.id in leg_dte_overrides
            else _resolve_leg_dte(leg.expiry, default_dte)
        )
        T = leg_dte / 365.0
        g = compute_leg_greeks(
            S=spot,
            K=leg.strike,
            r=risk_free_rate,
            sigma=iv,
            T=T,
            right=leg.right.value,
            side=leg.side.value,
            qty=leg.qty,
            q=q,
        )
        summary.delta += g["delta"]
        summary.gamma += g["gamma"]
        summary.vega += g["vega"]
        summary.theta += g["theta"]
        summary.rho += g["rho"]
        if leg.right != OptionRight.FUT:
            iv_values.append(iv)

    summary.iv_avg = float(sum(iv_values) / len(iv_values)) if iv_values else 0.0

    # Round for cleanliness
    summary.delta = round(float(summary.delta), 4)
    summary.gamma = round(float(summary.gamma), 6)
    summary.vega = round(float(summary.vega), 4)
    summary.theta = round(float(summary.theta), 4)
    summary.rho = round(float(summary.rho), 4)
    summary.iv_avg = round(float(summary.iv_avg), 4)

    return summary


# ──────────────────────────────────────────────────────────────
# Implied Volatility Solver
# ──────────────────────────────────────────────────────────────

def implied_volatility(
    market_price: float, S: float, K: float, r: float, T: float, right: str,
    lower: float = 0.001, upper: float = 20.0, q: float = 0.0
) -> float:
    """Solve for implied volatility using Brent's method."""
    if T <= 1e-6 or market_price <= 1e-6:
        return 0.0

    def objective(sigma):
        return bs_price(S, K, r, sigma, T, right, q) - market_price

    # BUG FIX: If option is trading below theoretical lower bound (arbitrage violation), return 0.0.
    if right.upper() in ("CE", "CALL", "C"):
        intrinsic = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    else:
        intrinsic = max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0)
        
    if market_price < intrinsic:
        return 0.0

    default_bounds_used = math.isclose(lower, 0.001) and math.isclose(upper, 20.0)
    lower = max(float(lower), 1e-6)
    upper = max(float(upper), lower + 1e-6)

    try:
        return brentq(objective, lower, upper, xtol=1e-5, maxiter=100)
    except ValueError:
        # Respect explicit caller bounds. Only auto-expand default bracket.
        if not default_bounds_used:
            return 0.0
        try:
            wide_lower = 0.0001
            wide_upper = 20.0
            return brentq(objective, wide_lower, wide_upper, xtol=1e-5, maxiter=100)
        except (ValueError, RuntimeError):
            return 0.0
    except (ValueError, RuntimeError):
        return 0.0


# ──────────────────────────────────────────────────────────────
# Payoff Calculator (at expiry)
# ──────────────────────────────────────────────────────────────

def calculate_payoff(
    spot_price: float,
    legs: list[ConcreteLeg],
    num_points: int = 200,
    range_mode: str = "chart",
) -> list[dict]:
    """
    Calculate the payoff curve at expiry for a set of legs.
    Returns a list of {underlying_price, pnl} data points.
    """
    if not legs:
        return []

    strikes = [leg.strike for leg in legs]
    min_strike = min(strikes)
    max_strike = max(strikes)

    # Keep chart view focused, but widen risk sampling for max loss/profit math.
    if range_mode == "risk":
        net_premium_per_unit = sum(
            (-leg.premium if leg.side == Side.BUY else leg.premium) for leg in legs
        )
        chart_min = 0.0
        chart_max = max(
            spot_price * 2.0,
            max_strike * 1.75,
            max_strike + abs(net_premium_per_unit) * 3.0,
        )
    else:
        # Chart range: extend 15% beyond the strike boundaries.
        chart_min = min(spot_price * 0.85, min_strike * 0.90)
        chart_max = max(spot_price * 1.15, max_strike * 1.10)

    prices = np.linspace(max(chart_min, 0.0), chart_max, num_points)
    data_points = []

    for p in prices:
        total_pnl = 0.0
        for leg in legs:
            intrinsic = 0.0
            if leg.right == OptionRight.CE:
                intrinsic = max(p - leg.strike, 0.0)
            elif leg.right == OptionRight.PE:
                intrinsic = max(leg.strike - p, 0.0)
            else:
                intrinsic = float(p)  # Linear for FUT

            if leg.side == Side.BUY:
                pnl = (intrinsic - leg.premium) * leg.qty
            else:
                pnl = (leg.premium - intrinsic) * leg.qty

            total_pnl += pnl

        data_points.append({
            "underlying_price": round(float(p), 2),
            "pnl": round(total_pnl, 2),
        })

    return data_points


def calculate_payoff_at_time(
    spot_price: float,
    legs: list[ConcreteLeg],
    days_to_expiry: int,
    risk_free_rate: float = 0.10,
    num_points: int = 200,
    leg_days_to_expiry: dict[str, int] | None = None,
    dividend_yield: float | None = None,
    underlying: str | None = None,
) -> list[dict]:
    """
    Calculate P&L at a given time before expiry using Black-Scholes pricing.
    More accurate than intrinsic-only payoff for scenario analysis.
    """
    if not legs:
        return []

    strikes = [leg.strike for leg in legs]
    chart_min = min(spot_price * 0.85, min(strikes) * 0.90)
    chart_max = max(spot_price * 1.15, max(strikes) * 1.10)
    prices = np.linspace(max(chart_min, 0.0), chart_max, num_points)

    data_points = []
    q = float(dividend_yield) if dividend_yield is not None else infer_dividend_yield(underlying, spot_price)
    for p in prices:
        total_pnl = 0.0
        for leg in legs:
            iv = leg.iv if leg.iv and leg.iv > 0 else 0.18
            leg_dte = (
                max(int(leg_days_to_expiry[leg.id]), 0)
                if leg_days_to_expiry and leg.id in leg_days_to_expiry
                else max(days_to_expiry, 0)
            )
            T = leg_dte / 365.0
            current_price = bs_price(float(p), leg.strike, risk_free_rate, iv, T, leg.right.value, q)

            if leg.side == Side.BUY:
                pnl = (current_price - leg.premium) * leg.qty
            else:
                pnl = (leg.premium - current_price) * leg.qty

            total_pnl += pnl

        data_points.append({
            "underlying_price": round(float(p), 2),
            "pnl": round(total_pnl, 2),
        })

    return data_points


# ──────────────────────────────────────────────────────────────
# Scenario Analysis (What-If Engine)
# ──────────────────────────────────────────────────────────────

def scenario_analysis(
    spot_price: float,
    legs: list[ConcreteLeg],
    delta_spot_pct: float = 0.0,
    delta_iv_points: float = 0.0,
    delta_days: int = 0, risk_free_rate: float = 0.10,
    default_dte: int = 7,
    dividend_yield: float | None = None,
    underlying: str | None = None,
) -> dict:
    """
    What-if scenario: shift spot, IV, and/or time.
    Returns new payoff curve, Greeks, and P&L summary.
    """
    new_spot = spot_price * (1 + delta_spot_pct / 100.0)

    # Adjust IVs on legs
    adjusted_legs = []
    leg_dte_overrides: dict[str, int] = {}
    for leg in legs:
        adj = leg.model_copy()
        current_iv = adj.iv if adj.iv and adj.iv > 0 else 0.18
        adj.iv = max(current_iv + delta_iv_points / 100.0, 0.01)
        current_dte = _resolve_leg_dte(adj.expiry, default_dte)
        leg_dte_overrides[adj.id] = max(current_dte - delta_days, 0)
        adjusted_legs.append(adj)

    # Keep backwards-compatible scalar DTE in the response.
    new_dte = (
        round(sum(leg_dte_overrides.values()) / len(leg_dte_overrides))
        if leg_dte_overrides
        else max(default_dte - delta_days, 0)
    )

    # Compute time-adjusted payoff curve
    payoff_curve = calculate_payoff_at_time(
        spot_price=new_spot,
        legs=adjusted_legs,
        days_to_expiry=new_dte,
        risk_free_rate=risk_free_rate,
        leg_days_to_expiry=leg_dte_overrides,
        dividend_yield=dividend_yield,
        underlying=underlying,
    )

    # Compute Greeks at the scenario point
    greeks = compute_strategy_greeks(
        spot=new_spot,
        legs=adjusted_legs,
        risk_free_rate=risk_free_rate,
        default_dte=new_dte,
        leg_dte_overrides=leg_dte_overrides,
        dividend_yield=dividend_yield,
        underlying=underlying,
    )

    # Compute current strategy P&L at the shifted spot
    current_pnl = 0.0
    q = float(dividend_yield) if dividend_yield is not None else infer_dividend_yield(underlying, new_spot)
    for leg in adjusted_legs:
        iv = leg.iv if leg.iv and leg.iv > 0 else 0.18
        T = max(leg_dte_overrides.get(leg.id, new_dte), 0) / 365.0
        current_price = bs_price(new_spot, leg.strike, risk_free_rate, iv, T, leg.right.value, q)
        if leg.side == Side.BUY:
            current_pnl += (current_price - leg.premium) * leg.qty
        else:
            current_pnl += (leg.premium - current_price) * leg.qty

    return {
        "scenario": {
            "new_spot": round(new_spot, 2),
            "new_dte": new_dte,
            "iv_shift": delta_iv_points,
        },
        "pnl_at_scenario": round(current_pnl, 2),
        "greeks": greeks.model_dump(),
        "payoff_curve": payoff_curve,
    }


# ──────────────────────────────────────────────────────────────
# Strategy Metrics (Max P&L, Breakeven)
# ──────────────────────────────────────────────────────────────

def compute_strategy_metrics(spot_price: float, legs: list[ConcreteLeg]) -> dict:
    """Compute max profit, max loss, and breakeven points from the payoff curve."""
    payoff = calculate_payoff(spot_price, legs, num_points=1200, range_mode="risk")
    if not payoff:
        return {
            "max_profit": 0,
            "max_loss": 0,
            "breakevens": [],
            "unbounded_profit": False,
            "unbounded_loss": False,
        }

    pnls = [p["pnl"] for p in payoff]
    prices = [p["underlying_price"] for p in payoff]

    max_profit = max(pnls)
    max_loss = min(pnls)

    left_slope = pnls[1] - pnls[0] if len(pnls) > 1 else 0.0
    right_slope = pnls[-1] - pnls[-2] if len(pnls) > 1 else 0.0

    # With non-negative underlying, unbounded tails come from upside (e.g., naked short call/future).
    unbounded_profit = bool(right_slope > 1e-2)
    unbounded_loss = bool(right_slope < -1e-2)

    # Find breakeven points (where PnL crosses zero)
    breakevens = []
    for i in range(1, len(pnls)):
        if (pnls[i - 1] < 0 and pnls[i] >= 0) or (pnls[i - 1] >= 0 and pnls[i] < 0):
            # Linear interpolation for more precise breakeven
            ratio = abs(pnls[i - 1]) / (abs(pnls[i - 1]) + abs(pnls[i]))
            be_price = prices[i - 1] + ratio * (prices[i] - prices[i - 1])
            breakevens.append(round(float(be_price), 2))

    return {
        "max_profit": round(float(max_profit), 2),
        "max_loss": round(float(max_loss), 2),
        "breakevens": breakevens,
        "unbounded_profit": unbounded_profit,
        "unbounded_loss": unbounded_loss,
        "net_premium": round(sum(
            (-leg.premium if leg.side == Side.BUY else leg.premium) * leg.qty
            for leg in legs
        ), 2),
    }


# ──────────────────────────────────────────────────────────────
# Enhanced Metrics (PoP, Capital, % Breakeven, % Return)
# ──────────────────────────────────────────────────────────────

def compute_enhanced_metrics(
    spot: float,
    legs: list[ConcreteLeg],
    dte: int = 7,
    risk_free_rate: float = 0.10,
    dividend_yield: float | None = None,
    underlying: str | None = None,
) -> dict:
    """
    Extended analytics beyond basic payoff:
      - capital_required: estimated margin (max_loss for defined risk, or net_debit)
      - pct_return: max_profit / capital_required as %
      - pop: Probability of Profit — integrates over payoff curve using delta-normal approx
      - be_pct: breakeven distances from spot as % (list)
      - current_pnl: live P&L at current spot using BS pricing
      - iv_avg: portfolio average IV
      - theta_daily: net daily theta decay in rupees
      - one_sigma_range: ±1σ move from spot over DTE
    """
    base = compute_strategy_metrics(spot, legs)
    greeks = compute_strategy_greeks(
        spot,
        legs,
        risk_free_rate,
        default_dte=dte,
        dividend_yield=dividend_yield,
        underlying=underlying,
    )

    max_profit = base["max_profit"]
    max_loss = base["max_loss"]   # already negative
    breakevens = base["breakevens"]
    net_premium = base["net_premium"]

    # ── Capital Required ──────────────────────────────────────
    # For defined-risk strategies: margin = abs(max_loss)
    # For undefined risk (naked shorts): use a robust SPAN proxy 

    is_undefined_risk = bool(base.get("unbounded_loss", False))

    if is_undefined_risk:
        qty_proxy = max(l.qty for l in legs) if legs else 50
        capital_required = (spot * 0.12 * qty_proxy)  # ~12% SPAN margin proxy
    else:
        capital_required = abs(max_loss) if max_loss < -1 else abs(net_premium) * 5

    capital_required = max(capital_required, 1.0)

    # ── % Return on Capital ───────────────────────────────────
    pct_return = round((max_profit / capital_required) * 100, 2) if capital_required > 0 else 0.0

    # ── Breakeven % distances from spot ───────────────────────
    be_pct = [round(((be - spot) / spot) * 100, 2) for be in breakevens]

    # ── Probability of Profit ─────────────────────────────────
    # Method: integrate the payoff curve — count points where PnL > 0,
    # weighted by the log-normal density of the underlying at expiry.
    # Simplified: use proportion of price range where PnL >= 0, weighted by
    # a log-normal distribution centered on spot with σ = iv_avg * sqrt(T).
    payoff = calculate_payoff(spot, legs, num_points=800, range_mode="risk")
    T = dte / 365.0
    iv_avg = greeks.iv_avg if greeks.iv_avg > 0 else 0.18

    if payoff and T > 0 and iv_avg > 0:
        sigma_total = iv_avg * math.sqrt(T)
        total_weight = 0.0
        profit_weight = 0.0
        for pt in payoff:
            p = pt["underlying_price"]
            pnl = pt["pnl"]
            if p <= 0:
                continue
            # Log-normal density weight
            log_ret = math.log(p / spot)
            weight = math.exp(-0.5 * ((log_ret - (-0.5 * iv_avg**2 * T)) / sigma_total)**2)
            total_weight += weight
            if pnl > 0:
                profit_weight += weight
        pop = round((profit_weight / total_weight) * 100, 1) if total_weight > 0 else 50.0
    else:
        pop = 50.0

    # ── Live P&L at current spot (BS-priced, not intrinsic) ──
    current_pnl = 0.0
    q = float(dividend_yield) if dividend_yield is not None else infer_dividend_yield(underlying, spot)
    for leg in legs:
        iv = leg.iv if leg.iv and leg.iv > 0 else 0.18
        leg_T = _resolve_leg_dte(leg.expiry, dte) / 365.0
        current_price = bs_price(spot, leg.strike, risk_free_rate, iv, leg_T, leg.right.value, q)
        if leg.side == Side.BUY:
            current_pnl += (current_price - leg.premium) * leg.qty
        else:
            current_pnl += (leg.premium - current_price) * leg.qty

    # ── 1σ expected move ─────────────────────────────────────
    one_sigma = round(spot * iv_avg * math.sqrt(T), 0)

    return {
        "capital_required": round(capital_required, 0),
        "pct_return": pct_return,
        "pop": pop,
        "be_pct": be_pct,
        "current_pnl": round(current_pnl, 2),
        "theta_daily": round(greeks.theta, 2),
        "delta_net": round(greeks.delta, 3),
        "vega_net": round(greeks.vega, 2),
        "iv_avg_pct": round(iv_avg * 100, 1),
        "one_sigma_up": round(spot + one_sigma, 0),
        "one_sigma_down": round(spot - one_sigma, 0),
        "dte": dte,
    }


# ──────────────────────────────────────────────────────────────
# Strike Optimizer (Greek-driven best combo finder)
# ──────────────────────────────────────────────────────────────

def find_optimal_strikes(
    spot: float,
    chain: list[dict],
    leg_templates: list,         # list of LegTemplate
    lot_size: int,
    dte: int = 7,
    risk_free_rate: float = 0.10,
    top_n: int = 3,
    dividend_yield: float | None = None,
    underlying: str | None = None,
) -> list[dict]:
    """
    Scans all valid strike combinations for a given strategy template against
    the live option chain and scores each combo on:
      1. Probability of Profit (PoP) — primary
      2. Theta/day — income efficiency
      3. Risk-Reward Ratio (max_profit / max_loss)
      4. Delta neutrality proximity (abs(net_delta) low = more neutral = safer)
      5. ±1σ breakeven safety margin

    Returns top_n combos sorted by composite score, each containing full metrics.
    """
    from .models import ConcreteLeg as CL, Side, OptionRight

    strikes = sorted([c["strike"] for c in chain])
    chain_by_strike = {c["strike"]: c for c in chain}

    if len(strikes) < len(leg_templates) + 1:
        return []

    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    T = dte / 365.0

    # Generate candidate offsets for each leg: ±5 strikes around ATM
    search_range = range(-5, 6)
    combos = []

    def _strike_at(offset: int) -> float | None:
        i = atm_idx + offset
        if 0 <= i < len(strikes):
            return strikes[i]
        return None

    # Generate all combinations of offsets for the leg templates
    import itertools
    offset_ranges = [search_range for _ in leg_templates]
    tried = 0

    for offsets in itertools.product(*offset_ranges):
        if tried > 50000:
            break
        tried += 1

        # Enforce monotone ordering for spread-type strategies
        strike_sequence = [_strike_at(o) for o in offsets]
        if any(s is None for s in strike_sequence):
            continue
        if len(set(strike_sequence)) != len(strike_sequence):
            continue

        # Build concrete legs
        concrete: list[CL] = []
        valid = True
        for tmpl, strike in zip(leg_templates, strike_sequence):
            row = chain_by_strike.get(strike, {})
            right_key = tmpl.right.value if hasattr(tmpl.right, "value") else tmpl.right
            opt = row.get(right_key, {})
            premium = opt.get("premium", 0)
            if premium <= 0:
                valid = False
                break
            iv = opt.get("iv", 18.0)
            iv = iv / 100.0 if iv > 1 else iv
            concrete.append(CL(
                side=tmpl.side,
                right=tmpl.right,
                strike=strike,
                premium=premium,
                qty=lot_size * tmpl.qty_multiplier,
                expiry="",
                iv=iv,
                delta=opt.get("delta"),
                gamma=opt.get("gamma"),
                vega=opt.get("vega"),
                theta=opt.get("theta"),
            ))

        if not valid or not concrete:
            continue

        try:
            metrics = compute_strategy_metrics(spot, concrete)
            enhanced = compute_enhanced_metrics(
                spot, concrete, dte, risk_free_rate,
                dividend_yield=dividend_yield, underlying=underlying,
            )
            greeks = compute_strategy_greeks(
                spot, concrete, risk_free_rate, default_dte=dte,
                dividend_yield=dividend_yield, underlying=underlying,
            )

            max_profit = metrics["max_profit"]
            unbounded_loss = bool(metrics.get("unbounded_loss", False))
            max_loss = float("inf") if unbounded_loss else abs(metrics["max_loss"])
            pop = enhanced["pop"]
            theta_day = greeks.theta
            capital = enhanced["capital_required"]

            if capital <= 0 or max_loss <= 0:
                continue

            rr = max_profit / max_loss if max_loss > 0 else 0
            delta_penalty = abs(greeks.delta)
            theta_efficiency = max(theta_day, 0.0)

            # Composite score (higher = better)
            score = (
                pop * 0.40                          # 40% weight: PoP
                + min(theta_efficiency / capital * 10000, 20) * 0.25  # 25%: positive theta efficiency
                + min(rr * 10, 20) * 0.20           # 20%: risk-reward
                + max(0, 10 - delta_penalty * 10) * 0.15  # 15%: delta neutrality
            )

            combos.append({
                "strikes": [{"side": t.side.value, "right": t.right.value,
                              "strike": s, "premium": chain_by_strike.get(s, {}).get(t.right.value if hasattr(t.right, "value") else t.right, {}).get("premium", 0)}
                             for t, s in zip(leg_templates, strike_sequence)],
                "legs": [l.model_dump() for l in concrete],
                "score": round(score, 2),
                "pop": pop,
                "max_profit": round(max_profit, 0),
                "max_loss": round(-abs(metrics["max_loss"]), 0),
                "unbounded_loss": unbounded_loss,
                "capital_required": round(capital, 0),
                "pct_return": enhanced["pct_return"],
                "theta_daily": round(greeks.theta, 2),
                "delta_net": round(greeks.delta, 3),
                "breakevens": metrics["breakevens"],
                "be_pct": enhanced["be_pct"],
                "net_premium": metrics["net_premium"],
            })
        except Exception:
            continue

    combos.sort(key=lambda x: x["score"], reverse=True)
    return combos[:top_n]
