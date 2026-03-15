import sys
import os
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.pricing_engine import (
    compute_leg_greeks,
    compute_strategy_greeks,
    compute_strategy_metrics,
    scenario_analysis,
    implied_volatility,
    bs_price,
)
from backend.models import ConcreteLeg, Side, OptionRight


def _mk_leg(side: Side, expiry: str) -> ConcreteLeg:
    return ConcreteLeg(
        side=side,
        right=OptionRight.CE,
        strike=25000,
        premium=250,
        qty=50,
        expiry=expiry,
        iv=0.2,
    )


def test_short_option_gamma_is_negative():
    long_g = compute_leg_greeks(25000, 25000, 0.10, 0.2, 30 / 365, "CE", "BUY", qty=50)
    short_g = compute_leg_greeks(25000, 25000, 0.10, 0.2, 30 / 365, "CE", "SELL", qty=50)

    assert long_g["gamma"] > 0
    assert short_g["gamma"] < 0
    assert math.isclose(long_g["gamma"], -short_g["gamma"], rel_tol=1e-12)


def test_strategy_greeks_respect_leg_expiry():
    today = datetime.now().date()
    near_expiry = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    far_expiry = (today + timedelta(days=60)).strftime("%Y-%m-%d")

    near = compute_strategy_greeks(25000, [_mk_leg(Side.BUY, near_expiry)])
    far = compute_strategy_greeks(25000, [_mk_leg(Side.BUY, far_expiry)])

    assert abs(near.theta) > abs(far.theta), f"Expected faster decay near expiry. near={near.theta}, far={far.theta}"
    assert near.vega < far.vega, f"Expected lower vega near expiry. near={near.vega}, far={far.vega}"


def test_scenario_uses_leg_expiry_not_fixed_default_dte():
    today = datetime.now().date()
    near_expiry = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    far_expiry = (today + timedelta(days=60)).strftime("%Y-%m-%d")

    near_scenario = scenario_analysis(25000, [_mk_leg(Side.BUY, near_expiry)], delta_days=0)
    far_scenario = scenario_analysis(25000, [_mk_leg(Side.BUY, far_expiry)], delta_days=0)

    near_theta = near_scenario["greeks"]["theta"]
    far_theta = far_scenario["greeks"]["theta"]
    assert abs(near_theta) > abs(far_theta), f"Scenario Greeks should reflect expiry. near={near_theta}, far={far_theta}"


def test_implied_volatility_respects_explicit_bounds():
    target_sigma = 0.8
    market_price = bs_price(25000, 25000, 0.10, target_sigma, 30 / 365, "CE")

    iv_narrow = implied_volatility(market_price, 25000, 25000, 0.10, 30 / 365, "CE", lower=0.001, upper=0.2)
    iv_default = implied_volatility(market_price, 25000, 25000, 0.10, 30 / 365, "CE")

    assert iv_narrow == 0.0
    assert abs(iv_default - target_sigma) < 1e-3


def test_strategy_metrics_flags_unbounded_upside_loss():
    leg = ConcreteLeg(
        side=Side.SELL,
        right=OptionRight.CE,
        strike=25000,
        premium=300,
        qty=50,
        expiry=(datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        iv=0.2,
    )
    metrics = compute_strategy_metrics(25000, [leg])

    assert metrics["unbounded_loss"] is True


def test_implied_volatility_q_aware_recovery():
    sigma_true = 0.2
    q = 0.012
    market_price = bs_price(25000, 25000, 0.10, sigma_true, 30 / 365, "CE", q=q)

    iv_without_q = implied_volatility(market_price, 25000, 25000, 0.10, 30 / 365, "CE")
    iv_with_q = implied_volatility(market_price, 25000, 25000, 0.10, 30 / 365, "CE", q=q)

    assert abs(iv_with_q - sigma_true) < abs(iv_without_q - sigma_true)
