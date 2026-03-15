# Quant Engine v1 Upgrade Report
**Date:** March 4, 2026  
**Project:** 24 Options Strategies Platform

## Scope Completed
Implemented the first 9 requested capability tracks in a practical v1 form:
1. Semi-autonomous management after one-time approval
2. Live portfolio optimizer (delta/vega rebalance planning)
3. Adaptive regime-based strategy recommendation
4. Auto-adjustment engine for stressed positions
5. Execution intelligence (liquidity guard + slicing + slippage limits)
6. Personalized quant profile persistence
7. Probabilistic decision scoring with stress tests
8. Journal + learning summary loop
9. Multi-asset support baseline (NIFTY/BANKNIFTY/FINNIFTY universe + hedge routing)

## Files Added / Updated
- Added: `backend/quant_engine.py`
- Updated: `backend/db.py`
- Updated: `backend/main.py`
- Added: `frontend/src/components/QuantEnginePanel.tsx`
- Added: `frontend/src/components/ActiveStrategyIntel.tsx`
- Updated: `frontend/src/App.tsx`

## What Was Implemented

### 1) Semi-autonomous trading flow
- Added an approval-gated autopilot state machine in `QuantEngineService`.
- New approval endpoint enables autopilot once (`approval_id`, `approved_at`, mode, interval).
- Autopilot cycle now runs from market stream updates with cooldown control:
  - Detects rebalance opportunities
  - Scans for stressed positions
  - Executes actions in paper mode automatically
  - Optionally supports live execution if explicitly enabled

### 2) Live portfolio optimizer
- Added optimizer that computes aggregate active portfolio Greeks and compares to targets.
- Generates hedge legs when gaps are material:
  - Delta balancing via futures legs
  - Vega balancing via ATM straddle unit
- Returns current vs projected Greeks + execution plan.

### 3) Adaptive strategy selection
- Added regime classifier from live chain:
  - Uses ATM IV, OI PCR, and skew (OTM put IV minus OTM call IV)
  - Regimes include `RANGE_LOW_VOL`, `TREND_UP`, `TREND_DOWN`, `EVENT_VOLATILE`, etc.
- Added strategy-id mappings per regime and risk mode.
- Added endpoint returning adaptive recommendation with:
  - selected strategy
  - resolved concrete legs
  - confidence/stress score
  - execution plan

### 4) Auto-adjustment engine
- Added adjustment scan on active strategies:
  - Loss-trigger-based defensive actions
  - Delta hedge insertion using futures
  - Expiry pin-risk flattening when gamma risk is elevated
- Actions are executable by autopilot in paper mode.

### 5) Execution intelligence
- Added execution planner that builds sliced order instructions with:
  - liquidity checks (`min_oi`, `min_volume`)
  - spread guard (`max_spread_pct`)
  - slippage controls (`slippage_tolerance_bps`)
  - quantity slicing (`max_slice_lots`)
- Planner returns `execution_ready`, warnings, and order slices.

### 6) Personalized quant profile
- Added persistent profile model in SQLite (`quant_profiles` table).
- Profile includes:
  - risk mode
  - capital/risk parameters
  - DTE preference band
  - delta/vega targets
  - execution constraints
  - live execution permission
- Added profile read/update APIs.

### 7) Probabilistic decision layer
- Added decision scoring for any proposed leg set:
  - Computes strategy metrics/enhanced metrics/Greeks
  - Runs deterministic stress suite (spot/IV/time shocks)
  - Produces confidence score + grade + component scores

### 8) Post-trade learning loop
- Added quant journal persistence (`quant_journal` table).
- Journal records profile updates, regime scans, recommendations, optimizer outputs, adjustment scans, autopilot cycles/actions.
- Added learning summary endpoint:
  - event distribution
  - close-action win/loss aggregates
  - realized P&L summary from logged closes

### 9) Multi-asset expansion baseline
- Added supported asset universe metadata:
  - `NSE:NIFTY50-INDEX`
  - `NSE:NIFTYBANK-INDEX`
  - `NSE:FINNIFTY-INDEX`
- Added symbol normalization + lot-size routing + hedge symbol metadata.
- Optimizer and autopilot now operate on normalized underlying symbols.

## New API Surface

### Quant Profile / Metadata
- `GET /api/quant/assets`
- `GET /api/quant/profile`
- `POST /api/quant/profile`

### Regime / Recommendation / Scoring
- `GET /api/quant/regime?underlying=...`
- `GET /api/quant/adaptive-recommendation?underlying=...&num_lots=...`
- `POST /api/quant/decision-score`
- `POST /api/quant/execution-plan`

### Portfolio Optimizer / Adjustments
- `POST /api/quant/portfolio-optimize`
- `GET /api/quant/adjustments?underlying=...`

### Autopilot
- `POST /api/quant/autopilot/approve`
- `POST /api/quant/autopilot/pause`
- `GET /api/quant/autopilot/status`
- `POST /api/quant/autopilot/run`

### Journal / Learning
- `GET /api/quant/journal?limit=...`
- `GET /api/quant/learning-summary?limit=...`

## Database Changes
Added 3 tables to `data/portfolio.db` initialization:
- `quant_profiles`
- `quant_autopilot_state`
- `quant_journal`

## Safety Notes
- Autopilot execution defaults to paper mode.
- Live execution requires explicit config (`mode=live` + `allow_live_execution=true`) and broker auth.
- Close-strategy auto-live flattening is intentionally not auto-enabled in v1.

## Validation Performed
- Python compile check: `venv/bin/python -m py_compile backend/*.py`
- App import check: `venv/bin/python -c "from backend.main import app; print('ok', len(app.routes))"`
- Quant engine unit tests: `venv/bin/python -m unittest tests/test_quant_engine_v1_unittest.py -v`
- Frontend build: `cd frontend && npm run build`

## Frontend Usage (New)
- Open **Builder** tab.
- Use the new **QUANT ENGINE v1** panel (below Scenario).
- Main actions:
  - `REGIME` to inspect live regime and confidence
  - `ADAPTIVE PICK` to fetch regime-mapped strategy
  - `SCORE CURRENT` for confidence/stress on builder legs
  - `PLAN CURRENT` for execution slicing/liquidity plan
  - `OPTIMIZE` for portfolio hedge suggestions
  - `ADJUSTMENTS` to inspect auto-repair actions
  - `APPROVE AUTO` / `RUN NOW` for autopilot controls
- AI panel now supports one-click leg injection:
  - Use the **INJECT STRATEGY** button inside AI output to load suggested legs into Builder.
- Dedicated **Quant** tab added for full-screen quant workflow controls.
- Monitor mode now includes **ACTIVE STRATEGY INTEL** for score/execution/AI odds-boost adjustments.

## Recommended Next Iteration (v1.1)
- Add user authentication/authorization before enabling live autopilot.
- Add per-user tenancy in profile/state/journal tables.
- Add automated tests for new `/api/quant/*` endpoints.
- Add explicit live order throttles and broker kill-switch flatten endpoint.
