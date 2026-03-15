import sys
import os
import math

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.pricing_engine import delta, gamma, theta, vega, rho

def test_delta_bounds_and_signs():
    # Call Delta should be (0, 1). Put Delta should be (-1, 0)
    c_delta = delta(25000, 25000, 0.10, 0.15, 30/365, "CE")
    p_delta = delta(25000, 25000, 0.10, 0.15, 30/365, "PE")
    
    assert 0 < c_delta < 1, f"Call Delta must be between 0 and 1. Got {c_delta}"
    assert -1 < p_delta < 0, f"Put Delta must be between -1 and 0. Got {p_delta}"

def test_gamma_always_positive_for_longs():
    # Gamma must be positive for any long option (call or put)
    c_gamma = gamma(25000, 26000, 0.10, 0.15, 30/365)
    p_gamma = gamma(25000, 24000, 0.10, 0.15, 30/365)
    
    assert c_gamma > 0, f"Call Gamma must be positive. Got {c_gamma}"
    assert p_gamma > 0, f"Put Gamma must be positive. Got {p_gamma}"

def test_vega_always_positive_for_longs():
    # Vega must be positive for any long option
    c_vega = vega(25000, 25000, 0.10, 0.15, 30/365)
    p_vega = vega(25000, 25000, 0.10, 0.15, 30/365)
    
    assert c_vega > 0, f"Call Vega must be positive. Got {c_vega}"
    assert p_vega > 0, f"Put Vega must be positive. Got {p_vega}"

def test_theta_sign_behaviour_for_longs():
    # ATM long call should decay, but deep ITM long put can have positive theta at higher rates.
    c_theta = theta(25000, 25000, 0.10, 0.15, 30/365, "CE")
    deep_itm_put_theta = theta(25000, 35000, 0.10, 0.15, 30/365, "PE")

    assert c_theta < 0, f"ATM Call Theta should be negative. Got {c_theta}"
    assert deep_itm_put_theta > 0, f"Deep ITM Put Theta can be positive. Got {deep_itm_put_theta}"

def test_call_put_parity_delta():
    # C_delta - P_delta should equal approx 1
    c_delta = delta(25000, 25000, 0.10, 0.15, 30/365, "CE")
    p_delta = delta(25000, 25000, 0.10, 0.15, 30/365, "PE")
    
    diff = c_delta - p_delta
    assert math.isclose(diff, 1.0, rel_tol=1e-5), f"Call Delta - Put Delta should equal 1. Got {diff}"


if __name__ == "__main__":
    tests = [
        test_delta_bounds_and_signs,
        test_gamma_always_positive_for_longs,
        test_vega_always_positive_for_longs,
        test_theta_sign_behaviour_for_longs,
        test_call_put_parity_delta
    ]
    
    failed = 0
    for test in tests:
        try:
            test()
            print(f"✅ Passed: {test.__name__}")
        except AssertionError as e:
            print(f"❌ Failed: {test.__name__}")
            print(f"   {e}")
            failed += 1
            
    if failed == 0:
        print("\n🎉 ALL THEORETICAL GREEKS TESTS PASSED!")
    else:
        print(f"\n⚠️ {failed} tests failed.")
