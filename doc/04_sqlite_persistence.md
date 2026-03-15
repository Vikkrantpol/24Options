# SQLite Database Persistence
**Date**: March 3, 2026

## The Risk
The simulated OMS (Order Management System) inside `paper_trade.py` was relying entirely upon Python lists (`self.strategies`, `self.positions`). Every time the fastAPI web server restarted (from code edits or crashes), users experienced catastrophic dataloss, wiping out their historical P&L and open positions.

## Implementation Structure
### 1. `db.py` Adapter
We constructed a lightweight, native `sqlite3` driver holding two relational tables:
- `strategies`: (id, template_id, template_name, underlying, spot_at_entry, net_premium, status, unrealized_pnl, realized_pnl).
- `legs`: Foreign-key attached storage for discrete options parameters (strike, right, execution price, side).

### 2. Paper Engine Synchronisation
We surgically modified `paper_trade.py`:
- `__init__`: Hydrates the active array by querying `load_active_strategies()` explicitly, ensuring positions survive boots.
- `update_mtm`: Synchronously overrides the `unrealized_pnl` rows upon every Black-Scholes pricing tick.
- `close_strategy`: Finalizes absolute Net capital shifts to the SQLite schema natively.
