"""
market_schedule.py — NSE Market Timing & Holiday Calendar
Provides market open/close awareness for the 24 Options Platform.
All times in IST (UTC+5:30).
"""
from __future__ import annotations
from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE session boundaries (IST)
MARKET_OPEN   = time(9, 15)
MARKET_CLOSE  = time(15, 30)
PRE_OPEN_START = time(9, 0)
PRE_OPEN_END   = time(9, 15)

# NSE Holidays 2025–2026
NSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 19),   # Chhatrapati Shivaji Maharaj Jayanti
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan Id)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 20),  # Diwali - Laxmi Puja (Muhurat Trading)
    date(2025, 10, 21),  # Diwali - Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi (approximate — update when NSE confirms)
    date(2026, 4, 3),    # Good Friday (approximate)
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 12, 25),  # Christmas
}


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


def is_trading_day(d: date | None = None) -> bool:
    """Returns True if the given date (default today IST) is a trading day."""
    d = d or now_ist().date()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in NSE_HOLIDAYS


def market_status() -> dict:
    """
    Returns a comprehensive market status dict:
      status: 'OPEN' | 'PRE_OPEN' | 'CLOSED' | 'HOLIDAY' | 'WEEKEND'
      message: human-readable string
      seconds_to_open / seconds_to_close: countdown integers
      next_trading_day: date string if today is non-trading
    """
    now = now_ist()
    today = now.date()
    current_time = now.time()

    # Weekend
    if today.weekday() >= 5:
        nxt = _next_trading_day(today)
        return {
            "status": "WEEKEND",
            "message": f"Market closed — Weekend. Opens {nxt.strftime('%a %d %b')} at 09:15 IST",
            "is_open": False,
            "seconds_to_open": _seconds_until(now, nxt, MARKET_OPEN),
            "seconds_to_close": None,
            "next_trading_day": nxt.isoformat(),
            "current_ist": now.strftime("%H:%M:%S"),
        }

    # Holiday
    if today in NSE_HOLIDAYS:
        nxt = _next_trading_day(today)
        return {
            "status": "HOLIDAY",
            "message": f"Market Holiday today. Opens {nxt.strftime('%a %d %b')} at 09:15 IST",
            "is_open": False,
            "seconds_to_open": _seconds_until(now, nxt, MARKET_OPEN),
            "seconds_to_close": None,
            "next_trading_day": nxt.isoformat(),
            "current_ist": now.strftime("%H:%M:%S"),
        }

    # Pre-open session
    if PRE_OPEN_START <= current_time < PRE_OPEN_END:
        secs = _seconds_until_same_day(now, MARKET_OPEN)
        return {
            "status": "PRE_OPEN",
            "message": f"Pre-Open session. Market opens in {_fmt_seconds(secs)}",
            "is_open": False,
            "seconds_to_open": secs,
            "seconds_to_close": None,
            "next_trading_day": today.isoformat(),
            "current_ist": now.strftime("%H:%M:%S"),
        }

    # Market open
    if MARKET_OPEN <= current_time <= MARKET_CLOSE:
        secs_close = _seconds_until_same_day(now, MARKET_CLOSE)
        return {
            "status": "OPEN",
            "message": f"Market LIVE ✅ — Closes in {_fmt_seconds(secs_close)}",
            "is_open": True,
            "seconds_to_open": 0,
            "seconds_to_close": secs_close,
            "next_trading_day": today.isoformat(),
            "current_ist": now.strftime("%H:%M:%S"),
        }

    # After close or before pre-open
    if current_time < PRE_OPEN_START:
        secs = _seconds_until_same_day(now, PRE_OPEN_START)
        nxt = today
    else:
        nxt = _next_trading_day(today)
        secs = _seconds_until(now, nxt, MARKET_OPEN)

    return {
        "status": "CLOSED",
        "message": f"Market closed. Opens {nxt.strftime('%a %d %b')} at 09:15 IST — in {_fmt_seconds(secs)}",
        "is_open": False,
        "seconds_to_open": secs,
        "seconds_to_close": None,
        "next_trading_day": nxt.isoformat(),
        "current_ist": now.strftime("%H:%M:%S"),
    }


def days_to_expiry(expiry_str: str) -> int:
    """
    Calculate calendar days from today (IST) to expiry date string.
    Accepts formats: 'YYYY-MM-DD', 'DD-MM-YYYY', 'DD-Mon-YYYY'.
    """
    today = now_ist().date()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            exp = datetime.strptime(expiry_str, fmt).date()
            return max((exp - today).days, 0)
        except ValueError:
            continue
    return 7  # safe fallback


def trading_days_to_expiry(expiry_str: str) -> int:
    """Count actual NSE trading days remaining until expiry."""
    today = now_ist().date()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            exp = datetime.strptime(expiry_str, fmt).date()
            count = 0
            d = today
            while d <= exp:
                if is_trading_day(d):
                    count += 1
                d += timedelta(days=1)
            return max(count - 1, 0)
        except ValueError:
            continue
    return 5


# ── Private helpers ────────────────────────────────────────────

def _next_trading_day(from_date: date) -> date:
    d = from_date + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def _seconds_until_same_day(now: datetime, t: time) -> int:
    target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return max(int((target - now).total_seconds()), 0)


def _seconds_until(now: datetime, target_date: date, target_time: time) -> int:
    target_dt = datetime.combine(target_date, target_time, tzinfo=IST)
    return max(int((target_dt - now).total_seconds()), 0)


def _fmt_seconds(secs: int) -> str:
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
