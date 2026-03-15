# Autopilot Runaway Hedge Fix (v1.0.1)
**Date:** March 5, 2026  
**Scope:** Stop repeated nonstop position creation in paper-mode autopilot.

## What Was Observed
- `data/portfolio.db` showed repeated new `AUTOPILOT-rebalance_portfolio` strategies every ~30 seconds.
- Active strategy concentration:
  - `AUTOPILOT-rebalance_portfolio`: 43 active (at investigation time)
- Journal cadence showed repeated `portfolio_optimizer` -> `autopilot_action` loops.

## Root Cause
- `run_autopilot_cycle()` queued `rebalance_portfolio` actions on every cycle when optimizer requested rebalancing.
- `_execute_actions()` always opened a new paper strategy for those actions.
- No idempotency/active-count guard existed for already-open rebalance hedges.

## Fix Implemented
### 1) Rebalance dedupe guard in quant engine
- File: `backend/quant_engine.py`
- Added autopilot state control:
  - `max_active_rebalance_per_symbol` (default `1`)
- Added execute-time protection for paper mode:
  - If `AUTOPILOT-rebalance_portfolio` active count for the symbol already meets/exceeds the configured limit, skip opening another.
  - Write a `quant_journal` `autopilot_action` event with `status: "skipped"` and reason.

### 2) Configurable approval field
- File: `backend/quant_engine.py`
- `approve_autopilot()` now accepts `max_active_rebalance_per_symbol` (clamped 1..10).

### 3) Regression test
- File: `tests/test_quant_engine_v1_unittest.py`
- Added:
  - `test_rebalance_dedup_blocks_duplicate_active_autopilot_hedges`
- Verifies:
  - first cycle opens 1 rebalance strategy
  - second cycle skips duplicate
  - active rebalance count stays 1

## Operational Effect
- Market-closed gate remains in force (no order execution when market is closed).
- During market-open paper autopilot:
  - optimizer can still suggest rebalancing
  - duplicate rebalance openings are now blocked by guardrail
  - journal records explicit skip reason for operator visibility

## Database Cleanup Applied (March 5, 2026)
- Backup created:
  - `data/portfolio.db.bak_20260305_154128`
- Deleted runaway active rebalance rows:
  - `strategies`: 61 rows removed (`AUTOPILOT-rebalance_portfolio`, `status='active'`)
  - `legs`: 124 linked rows removed
  - `quant_journal`: 61 linked `autopilot_action` rows removed (matching deleted strategy IDs)
- Post-cleanup strategy counts:
  - `active`: 3
  - `closed`: 18

## UI Visibility Upgrade
- `Quant` panel now shows:
  - **Trading Journal** (expanded recent events with event summaries)
  - **Closed Trades** (recent closed strategy list with exit time and realized P&L)
- `Monitor` tab now always renders **Closed Trades** panel:
  - shows empty state when none exist
  - shows closed timestamp + realized P&L when present

## How To Verify Quickly
1. Approve autopilot in paper mode with:
   - `max_active_rebalance_per_symbol = 1`
2. Run two forced autopilot cycles with the same rebalance condition.
3. Check:
   - second cycle has `execution_report.executed_count = 0` for duplicate rebalance
   - `execution_report.skipped` contains "already open" reason
4. DB check:
```sql
SELECT template_name, status, COUNT(*)
FROM strategies
GROUP BY template_name, status
ORDER BY COUNT(*) DESC;
```
