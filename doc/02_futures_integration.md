# Futures Native Integration
**Date**: March 3, 2026

## The Problem
Initially, the `StrategyBuilder` and underlying recursive pricing engine were strictly hardcoded to process non-linear derivatives (Calls and Puts). Quantitative users needed a way to synthesize delta-one hedges, such as directly trading the Nifty/BankNifty Futures.

## Implementation Steps
### 1. Data Models (`types.ts`, `models.py`)
- Broadened the `OptionRight` Enum from `'CE' | 'PE'` to include `'FUT'`.

### 2. UI Builder Lockdowns (`App.tsx`)
- When a user selects `FUT` inside the Custom Leg builder, the `Strike` input actively disables itself.
- We auto-populate the theoretical premium textbox directly with the realtime Spot price, as Future strikes are mathematically identically to the spot price at initiation.

### 3. Pricing & Payoff Math (`pricing_engine.py`)
- We engineered an override inside the Black-Scholes module. When `bs_price` or `calculate_payoff` detects a leg of type `FUT`, it bypasses the exponential curves.
- The intrinsic P&L formula converts to a strictly linear 1:1 scaling matrix. 
- **Greeks Modification**: Futures default to `Delta = 1.0`. All non-linear Greeks (`Gamma`, `Theta`, `Vega`) are statically zeroed out to prevent skewing the wider portfolio's volatility metrics.
