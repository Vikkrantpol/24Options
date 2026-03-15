import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.ai_engine import build_chain_context, build_legs_context
from backend.main import ai_best_picks, fyers_client
from backend.models import ConcreteLeg, OptionRight, Side
from backend.pricing_engine import compute_strategy_greeks


def test_chain_context_includes_gamma_columns():
    chain = {
        "symbol": "NSE:NIFTY50-INDEX",
        "spot": 22500,
        "expiry": (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "lot_size": 50,
        "chain": [
            {
                "strike": 22500,
                "CE": {"premium": 200, "iv": 14, "delta": 0.5, "gamma": 0.0012, "theta": -12, "vega": 10, "oi": 100000, "volume": 5000},
                "PE": {"premium": 180, "iv": 15, "delta": -0.5, "gamma": 0.0013, "theta": -11, "vega": 11, "oi": 110000, "volume": 5200},
            }
        ],
    }
    ctx = build_chain_context(chain)
    assert "CE_Γ" in ctx and "PE_Γ" in ctx
    assert "0.00120" in ctx or "0.00130" in ctx


def test_build_legs_context_keeps_zero_delta():
    leg = ConcreteLeg(
        side=Side.BUY,
        right=OptionRight.CE,
        strike=22500,
        premium=100,
        qty=50,
        expiry=(datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        iv=0.15,
        delta=0.0,
    )
    text = build_legs_context([leg])
    assert "Δ:0.0" in text


def test_dividend_yield_inference_changes_greeks():
    expiry = (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d")
    leg = ConcreteLeg(
        side=Side.BUY,
        right=OptionRight.CE,
        strike=22500,
        premium=220,
        qty=50,
        expiry=expiry,
        iv=0.2,
    )
    nifty = compute_strategy_greeks(spot=22500, legs=[leg], underlying="NSE:NIFTY50-INDEX")
    bank = compute_strategy_greeks(spot=22500, legs=[leg], underlying="NSE:NIFTYBANK-INDEX")
    assert abs(nifty.delta - bank.delta) > 0.001


def test_ai_best_picks_skips_zero_premium_templates():
    original_get_chain = fyers_client.get_option_chain
    try:
        fyers_client.get_option_chain = lambda _symbol: {
            "symbol": "NSE:NIFTY50-INDEX",
            "spot": 22500,
            "expiry": (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "lot_size": 50,
            "chain": [
                {
                    "strike": 22400,
                    "CE": {"premium": 0, "iv": 15, "delta": 0.55, "gamma": 0.001, "theta": -9, "vega": 8},
                    "PE": {"premium": 0, "iv": 15, "delta": -0.45, "gamma": 0.001, "theta": -10, "vega": 9},
                },
                {
                    "strike": 22500,
                    "CE": {"premium": 0, "iv": 15, "delta": 0.5, "gamma": 0.001, "theta": -10, "vega": 9},
                    "PE": {"premium": 0, "iv": 15, "delta": -0.5, "gamma": 0.001, "theta": -10, "vega": 9},
                },
                {
                    "strike": 22600,
                    "CE": {"premium": 0, "iv": 15, "delta": 0.45, "gamma": 0.001, "theta": -11, "vega": 10},
                    "PE": {"premium": 0, "iv": 15, "delta": -0.55, "gamma": 0.001, "theta": -9, "vega": 8},
                },
            ],
        }
        result = ai_best_picks("NIFTY")
        assert result["picks"] == []
    finally:
        fyers_client.get_option_chain = original_get_chain


if __name__ == "__main__":
    tests = [
        test_chain_context_includes_gamma_columns,
        test_build_legs_context_keeps_zero_delta,
        test_dividend_yield_inference_changes_greeks,
        test_ai_best_picks_skips_zero_premium_templates,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    if failed:
        raise SystemExit(1)
