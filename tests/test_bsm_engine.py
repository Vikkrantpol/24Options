import sys
import os
import math

# Add the project root to the path so we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.pricing_engine import (
    rho, gamma, theta, implied_volatility, bs_price, delta
)

def test_put_rho_polarity():
    """Verify that Put Rho is mathematically negative."""
    # S=25000, K=25000, r=0.10, sigma=0.15, T=30/365
    put_rho = rho(25000, 25000, 0.10, 0.15, 30/365, "PE")
    call_rho = rho(25000, 25000, 0.10, 0.15, 30/365, "CE")
    
    assert put_rho < 0, f"Put Rho must be negative! Got: {put_rho}"
    assert call_rho > 0, f"Call Rho must be positive! Got: {call_rho}"
    print("✅ Passed: Put Rho Polarity")


def test_iv_solver_intrinsic_bounds():
    """Verify IV solver returns 0.0 instead of crashing when market price is below intrinsic value."""
    # Deep ITM Call S=25000, K=24000. Intrinsic value is 1000.
    # We pass market_price = 950 (Below intrinsic, mathematically impossible in BSM).
    iv = implied_volatility(market_price=950, S=25000, K=24000, r=0.10, T=30/365, right="CE")
    
    assert iv == 0.0, f"IV solver should return 0.0 for below-intrinsic prices. Got: {iv}"
    print("✅ Passed: IV Solver Intrinsic Bounds")


def test_gamma_0_dte_explosion():
    """Verify ATM Gamma scales toward infinity at 0 DTE instead of defaulting to 0."""
    # S=25000, K=25000, exactly 0.0 seconds to expiry.
    gamma_0 = gamma(25000, 25000, 0.10, 0.15, 0.0)
    
    assert gamma_0 == 1e9, f"ATM Gamma at 0 DTE should explode to 1e9. Got: {gamma_0}"
    print("✅ Passed: Gamma 0 DTE Explosion Limit")


def test_theta_0_dte_epsilon():
    """Verify Theta scales to massive negative values near 0 DTE instead of zeroing out."""
    # S=25000, K=25000, T=1 second left to expiry.
    # Time decay in the last second of a 15% IV ATM option is astronomically huge.
    theta_value = theta(25000, 25000, 0.10, 0.15, 1e-6, "CE")
    
    assert theta_value < -100, f"Theta near 0 DTE should be massively negative. Got: {theta_value}"
    print("✅ Passed: Theta 0 DTE Continuous Decay Limit")


def test_custom_10_percent_risk_free_rate():
    """Verify BSM prices correctly price the forward curve using 10% interest limits."""
    # In pure BSM, Call price > Put price for identical ATM strikes 
    # when risk-free rate is high (cost of carry).
    call_price = bs_price(S=25000, K=25000, r=0.10, sigma=0.15, T=30/365, right="CE")
    put_price = bs_price(S=25000, K=25000, r=0.10, sigma=0.15, T=30/365, right="PE")
    
    assert call_price > put_price, "High interest rates (10%) should make calls more expensive than puts due to implied forward."
    print("✅ Passed: 10% Risk-Free Rate BSM Pricing Curve")


if __name__ == "__main__":
    print(f"\n{'='*40}")
    print("Running BSM Pricing Engine Tests")
    print(f"{'='*40}\n")
    
    tests = [
        test_put_rho_polarity,
        test_iv_solver_intrinsic_bounds,
        test_gamma_0_dte_explosion,
        test_theta_0_dte_epsilon,
        test_custom_10_percent_risk_free_rate,
    ]
    
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"❌ Failed: {test.__name__}")
            print(f"   Reason: {e}")
            failed += 1
            
    print(f"\n{'-'*40}")
    if failed == 0:
        print("🎉 All 5 Math Invariants Passed!")
    else:
        print(f"⚠️ {failed} tests failed. Need debugging.")
    print(f"{'='*40}\n")
