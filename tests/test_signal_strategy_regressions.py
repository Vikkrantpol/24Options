import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.ai_engine import build_signal_strategy_profile
from backend.main import ai_best_picks, fyers_client
from backend.models import ConcreteLeg, OptionRight, Side
from backend.pricing_engine import bs_price, delta as bs_delta, compute_strategy_metrics, scenario_analysis


def _expiry(days: int) -> str:
    return (datetime.now().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def _option_snapshot(
    *,
    spot: float,
    strike: float,
    right: str,
    iv: float,
    expiry_days: int,
    price_shift: float,
    delta_shift: float,
    oi: int,
    volume: int,
) -> dict:
    T = max(expiry_days, 1) / 365.0
    q = 0.012
    fair = bs_price(spot, strike, 0.10, iv, T, right, q=q)
    market = max(round(fair + price_shift, 2), 0.5)
    model_delta = bs_delta(spot, strike, 0.10, iv, T, right, q=q)
    return {
        "ltp": market,
        "premium": market,
        "iv": round(iv * 100, 2),
        "delta": round(model_delta + delta_shift, 4),
        "gamma": 0.0012,
        "theta": -11.0,
        "vega": 9.0,
        "oi": oi,
        "volume": volume,
        "bid": round(market * 0.99, 2),
        "ask": round(market * 1.01, 2),
    }


def _bullish_signal_chain() -> dict:
    spot = 22500.0
    expiry_days = 7
    rows = []
    for strike in (22300, 22400, 22500, 22600, 22700):
        rows.append({
            "strike": strike,
            "CE": _option_snapshot(
                spot=spot,
                strike=strike,
                right="CE",
                iv=0.16,
                expiry_days=expiry_days,
                price_shift=-14.0 if strike >= 22500 else -8.0,
                delta_shift=0.06,
                oi=70000,
                volume=4200,
            ),
            "PE": _option_snapshot(
                spot=spot,
                strike=strike,
                right="PE",
                iv=0.17,
                expiry_days=expiry_days,
                price_shift=12.0 if strike <= 22500 else 6.0,
                delta_shift=0.04,
                oi=130000,
                volume=5600,
            ),
        })
    return {
        "symbol": "NSE:NIFTY50-INDEX",
        "spot": spot,
        "expiry": _expiry(expiry_days),
        "lot_size": 65,
        "chain": rows,
    }


def _bearish_signal_chain() -> dict:
    spot = 22500.0
    expiry_days = 7
    rows = []
    for strike in (22300, 22400, 22500, 22600, 22700):
        rows.append({
            "strike": strike,
            "CE": _option_snapshot(
                spot=spot,
                strike=strike,
                right="CE",
                iv=0.17,
                expiry_days=expiry_days,
                price_shift=13.0 if strike >= 22500 else 7.0,
                delta_shift=-0.05,
                oi=135000,
                volume=5400,
            ),
            "PE": _option_snapshot(
                spot=spot,
                strike=strike,
                right="PE",
                iv=0.16,
                expiry_days=expiry_days,
                price_shift=-15.0 if strike <= 22500 else -8.0,
                delta_shift=-0.06,
                oi=68000,
                volume=4100,
            ),
        })
    return {
        "symbol": "NSE:NIFTY50-INDEX",
        "spot": spot,
        "expiry": _expiry(expiry_days),
        "lot_size": 65,
        "chain": rows,
    }


def test_breakeven_matches_textbook_long_call():
    leg = ConcreteLeg(side=Side.BUY, right=OptionRight.CE, strike=25000, premium=200, qty=50, expiry=_expiry(7), iv=0.2)
    metrics = compute_strategy_metrics(25000, [leg])
    assert metrics["breakevens"] == [25200.0]


def test_breakeven_matches_textbook_bull_call_spread():
    legs = [
        ConcreteLeg(side=Side.BUY, right=OptionRight.CE, strike=25000, premium=220, qty=50, expiry=_expiry(7), iv=0.2),
        ConcreteLeg(side=Side.SELL, right=OptionRight.CE, strike=25200, premium=120, qty=50, expiry=_expiry(7), iv=0.2),
    ]
    metrics = compute_strategy_metrics(25000, legs)
    assert metrics["breakevens"] == [25100.0]


def test_breakeven_matches_textbook_long_straddle():
    legs = [
        ConcreteLeg(side=Side.BUY, right=OptionRight.CE, strike=25000, premium=200, qty=50, expiry=_expiry(7), iv=0.2),
        ConcreteLeg(side=Side.BUY, right=OptionRight.PE, strike=25000, premium=180, qty=50, expiry=_expiry(7), iv=0.2),
    ]
    metrics = compute_strategy_metrics(25000, legs)
    assert metrics["breakevens"] == [24620.0, 25380.0]


def test_scenario_expiry_converges_to_intrinsic_payoff():
    leg = ConcreteLeg(side=Side.BUY, right=OptionRight.CE, strike=25000, premium=200, qty=50, expiry=_expiry(30), iv=0.2)
    scenario = scenario_analysis(25100, [leg], delta_days=30)
    # Intrinsic at 25100 is 100; pnl = (100 - 200) * 50 = -5000
    assert abs(scenario["pnl_at_scenario"] + 5000.0) < 1e-6


def test_signal_profile_prefers_bullish_structure():
    profile = build_signal_strategy_profile(_bullish_signal_chain(), top_n=5)
    assert profile["combined"]["direction"] == "bullish"
    assert profile["combined"]["volatility_bias"] == "short_vol"
    assert profile["recommended_strategy_ids"][0] == 10


def test_signal_profile_prefers_bearish_structure():
    profile = build_signal_strategy_profile(_bearish_signal_chain(), top_n=5)
    assert profile["combined"]["direction"] == "bearish"
    assert profile["combined"]["volatility_bias"] == "short_vol"
    assert profile["recommended_strategy_ids"][0] == 9


def test_ai_best_picks_align_with_bullish_signal_engine():
    original_get_chain = fyers_client.get_option_chain
    try:
        fyers_client.get_option_chain = lambda _symbol: _bullish_signal_chain()
        result = ai_best_picks("NIFTY")
        assert result["picks"], "Expected at least one scored strategy"
        assert result["picks"][0]["strategy_id"] == 10
    finally:
        fyers_client.get_option_chain = original_get_chain


def test_ai_best_picks_align_with_bearish_signal_engine():
    original_get_chain = fyers_client.get_option_chain
    try:
        fyers_client.get_option_chain = lambda _symbol: _bearish_signal_chain()
        result = ai_best_picks("NIFTY")
        assert result["picks"], "Expected at least one scored strategy"
        assert result["picks"][0]["strategy_id"] == 9
    finally:
        fyers_client.get_option_chain = original_get_chain


if __name__ == "__main__":
    tests = [
        test_breakeven_matches_textbook_long_call,
        test_breakeven_matches_textbook_bull_call_spread,
        test_breakeven_matches_textbook_long_straddle,
        test_scenario_expiry_converges_to_intrinsic_payoff,
        test_signal_profile_prefers_bullish_structure,
        test_signal_profile_prefers_bearish_structure,
        test_ai_best_picks_align_with_bullish_signal_engine,
        test_ai_best_picks_align_with_bearish_signal_engine,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
            failures += 1
    if failures:
        raise SystemExit(1)
