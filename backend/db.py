import sqlite3
import json
from pathlib import Path
from typing import Any
from contextlib import closing
from .models import StrategyInstance, ConcreteLeg, Side, OptionRight
from datetime import datetime

DB_PATH = Path("data/portfolio.db")

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True, parents=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                template_id INTEGER,
                template_name TEXT,
                underlying TEXT,
                spot_at_entry REAL,
                net_premium REAL,
                status TEXT,
                unrealized_pnl REAL,
                realized_pnl REAL,
                entry_time TEXT,
                exit_time TEXT,
                tags TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS legs (
                id TEXT PRIMARY KEY,
                strategy_instance_id TEXT,
                side TEXT,
                right TEXT,
                strike REAL,
                premium REAL,
                qty INTEGER,
                expiry TEXT,
                iv REAL,
                FOREIGN KEY(strategy_instance_id) REFERENCES strategies(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS quant_profiles (
                user_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS quant_autopilot_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS quant_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                symbol TEXT,
                payload_json TEXT NOT NULL
            )
        ''')
        conn.commit()

class PortfolioDB:
    def __init__(self):
        init_db()
        
    def _connect(self):
        return sqlite3.connect(DB_PATH)

    def save_strategy(self, instance: StrategyInstance):
        with closing(self._connect()) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO strategies 
                (id, template_id, template_name, underlying, spot_at_entry, net_premium, 
                 status, unrealized_pnl, realized_pnl, entry_time, exit_time, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                instance.id, instance.template_id, instance.template_name,
                instance.underlying, instance.spot_at_entry, instance.net_premium,
                instance.status, instance.unrealized_pnl, instance.realized_pnl,
                instance.entry_time.isoformat() if instance.entry_time else None,
                instance.exit_time.isoformat() if instance.exit_time else None,
                json.dumps(instance.tags)
            ))
            
            for leg in instance.legs:
                conn.execute('''
                    INSERT OR REPLACE INTO legs
                    (id, strategy_instance_id, side, right, strike, premium, qty, expiry, iv)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    leg.id, instance.id, leg.side.value, leg.right.value,
                    leg.strike, leg.premium, leg.qty, leg.expiry, leg.iv
                ))
            conn.commit()

    def update_strategy_pnl(self, instance: StrategyInstance):
        with closing(self._connect()) as conn:
            conn.execute('''
                UPDATE strategies 
                SET status = ?, unrealized_pnl = ?, realized_pnl = ?, exit_time = ?
                WHERE id = ?
            ''', (
                instance.status, instance.unrealized_pnl, instance.realized_pnl,
                instance.exit_time.isoformat() if instance.exit_time else None,
                instance.id
            ))
            conn.commit()

    def load_active_strategies(self) -> list[StrategyInstance]:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM strategies WHERE status = "active"').fetchall()
            
            instances = []
            for row in rows:
                leg_rows = conn.execute('SELECT * FROM legs WHERE strategy_instance_id = ?', (row['id'],)).fetchall()
                legs = []
                for lr in leg_rows:
                    legs.append(ConcreteLeg(
                        id=lr['id'], 
                        side=Side(lr['side']), 
                        right=OptionRight(lr['right']),
                        strike=lr['strike'], 
                        premium=lr['premium'], 
                        qty=lr['qty'],
                        expiry=lr['expiry'], 
                        iv=lr['iv']
                    ))
                
                instances.append(StrategyInstance(
                    id=row['id'],
                    template_id=row['template_id'],
                    template_name=row['template_name'],
                    underlying=row['underlying'],
                    spot_at_entry=row['spot_at_entry'],
                    legs=legs,
                    net_premium=row['net_premium'],
                    status=row['status'],
                    unrealized_pnl=row['unrealized_pnl'],
                    realized_pnl=row['realized_pnl'],
                    entry_time=datetime.fromisoformat(row['entry_time']) if row['entry_time'] else None,
                    exit_time=datetime.fromisoformat(row['exit_time']) if row['exit_time'] else None,
                    tags=json.loads(row['tags']) if row['tags'] else []
                ))
            return instances

    def get_portfolio_summary_stats(self) -> dict:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            active = conn.execute('SELECT COUNT(*) as c, SUM(unrealized_pnl) as up FROM strategies WHERE status = "active"').fetchone()
            closed = conn.execute('SELECT COUNT(*) as c, SUM(realized_pnl) as rp FROM strategies WHERE status = "closed"').fetchone()
            
            return {
                "active_count": active['c'] or 0,
                "closed_count": closed['c'] or 0,
                "unrealized_pnl": active['up'] or 0.0,
                "realized_pnl": closed['rp'] or 0.0,
            }


class QuantEngineDB:
    """Persistence for quant profile, autopilot state, and journal records."""

    def __init__(self):
        init_db()

    def _connect(self):
        return sqlite3.connect(DB_PATH)

    def get_profile(self, user_id: str = "default") -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT profile_json FROM quant_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["profile_json"])
            except Exception:
                return None

    def save_profile(self, profile: dict[str, Any], user_id: str = "default"):
        with closing(self._connect()) as conn:
            conn.execute(
                '''
                INSERT INTO quant_profiles(user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                ''',
                (user_id, json.dumps(profile), datetime.now().isoformat()),
            )
            conn.commit()

    def get_autopilot_state(self) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT state_json FROM quant_autopilot_state WHERE id = 1"
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["state_json"])
            except Exception:
                return None

    def save_autopilot_state(self, state: dict[str, Any]):
        with closing(self._connect()) as conn:
            conn.execute(
                '''
                INSERT INTO quant_autopilot_state(id, state_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                ''',
                (json.dumps(state), datetime.now().isoformat()),
            )
            conn.commit()

    def append_journal(self, event_type: str, payload: dict[str, Any], symbol: str | None = None):
        with closing(self._connect()) as conn:
            conn.execute(
                '''
                INSERT INTO quant_journal(created_at, event_type, symbol, payload_json)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    datetime.now().isoformat(),
                    event_type,
                    symbol,
                    json.dumps(payload),
                ),
            )
            conn.commit()

    def get_journal(self, limit: int = 100) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 500))
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT id, created_at, event_type, symbol, payload_json
                FROM quant_journal
                ORDER BY id DESC
                LIMIT ?
                ''',
                (capped,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    payload = {}
                out.append({
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "event_type": row["event_type"],
                    "symbol": row["symbol"],
                    "payload": payload,
                })
            return out
