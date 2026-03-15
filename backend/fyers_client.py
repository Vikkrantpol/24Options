"""
Fyers broker connector — production-grade.
Handles OAuth authentication (auto-opens browser, prompts in terminal),
live option chain data, multi-leg order placement, and position monitoring.
"""

from __future__ import annotations
import os
import webbrowser
import math
import copy
import threading
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv

load_dotenv()


class FyersAPIClient:
    """Production-grade Fyers API v3 connector."""

    def __init__(self):
        self.client_id = os.getenv("FYERS_APP_ID", "")
        self.secret_key = os.getenv("FYERS_SECRET_KEY", "")
        self.redirect_uri = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
        self.access_token = None
        self.fyers = None
        self._chain_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._ticks_lock = threading.Lock()
        self._symbol_ticks: dict[str, dict[str, Any]] = {}
        self._tick_count = 0
        self._last_tick_at: datetime | None = None
        self._socket_lock = threading.Lock()
        self._market_socket = None
        self._socket_connected_at: datetime | None = None
        self._subscribed_symbols: set[str] = set()
        self._last_chain_error: str | None = None
        self._token_path = os.path.join(os.path.dirname(__file__), "..", "data", ".fyers_token")

        # Auto-load token if it exists from terminal run.sh authentication
        if os.path.exists(self._token_path) and self.client_id:
            try:
                with open(self._token_path, "r") as f:
                    token = f.read().strip()
                if token:
                    self._bind_fyers_client(token)
            except Exception as e:
                print(f"  ⚠  Could not load cached Fyers token: {e}")

    @property
    def is_authenticated(self) -> bool:
        return self.fyers is not None and self.access_token is not None

    def _bind_fyers_client(self, token: str):
        from fyers_apiv3 import fyersModel
        self.access_token = token
        self.fyers = fyersModel.FyersModel(
            client_id=self.client_id,
            is_async=False,
            token=self.access_token,
            log_path=os.path.join(os.path.dirname(__file__), "..", "data"),
        )

    def _persist_token(self):
        if not self.access_token:
            return
        os.makedirs(os.path.dirname(self._token_path), exist_ok=True)
        with open(self._token_path, "w") as f:
            f.write(self.access_token.strip())

    def _clear_cached_token(self):
        if os.path.exists(self._token_path):
            try:
                os.remove(self._token_path)
            except Exception:
                pass

    def _invalidate_session(self, clear_cached_token: bool = False):
        with self._socket_lock:
            if self._market_socket is not None:
                try:
                    self._market_socket.close_connection()
                except Exception:
                    pass
            self._market_socket = None
            self._subscribed_symbols.clear()
        with self._ticks_lock:
            self._symbol_ticks.clear()
            self._tick_count = 0
            self._last_tick_at = None
        self.fyers = None
        self.access_token = None
        if clear_cached_token:
            self._clear_cached_token()

    @staticmethod
    def _extract_auth_code(auth_input: str) -> str:
        value = (auth_input or "").strip()
        if not value:
            return ""

        if value.startswith("http://") or value.startswith("https://"):
            try:
                query = parse_qs(urlparse(value).query)
                for key in ("auth_code", "code"):
                    if key in query and query[key]:
                        return query[key][0].strip()
            except Exception:
                pass

        if "auth_code=" in value:
            code = value.split("auth_code=", 1)[1]
            for sep in ("&", "#", " "):
                code = code.split(sep, 1)[0]
            return code.strip()

        return value

    @staticmethod
    def _prompt_line(prompt: str) -> str:
        """
        Read interactive input, with /dev/tty fallback when stdin is not attached.
        """
        try:
            return input(prompt)
        except EOFError:
            try:
                with open("/dev/tty", "r+", encoding="utf-8", buffering=1) as tty:
                    tty.write(prompt)
                    tty.flush()
                    return tty.readline().strip()
            except Exception:
                return ""

    @staticmethod
    def _looks_like_auth_failure(response: dict | None) -> bool:
        if not isinstance(response, dict):
            return False
        code = response.get("code")
        message = str(response.get("message", "")).lower()
        if code in {-15, -16, 401, 403}:
            return True
        if "valid token" in message or "token expired" in message or "unauthor" in message:
            return True
        return False

    @staticmethod
    def _default_lot_size(symbol: str) -> int:
        s = str(symbol or "").upper()
        if "BANK" in s:
            return 30
        if "NIFTY" in s:
            return 65
        return 1

    def validate_session(self) -> bool:
        """Validate cached/current broker session with a lightweight profile call."""
        if not self.is_authenticated:
            return False
        try:
            response = self.fyers.get_profile()
        except Exception:
            return False

        if isinstance(response, dict) and response.get("s") == "ok":
            return True

        # Fyers often wraps auth failures as generic -99 bad request on SDK calls.
        if (isinstance(response, dict) and response.get("code") == -99) or self._looks_like_auth_failure(response):
            self._invalidate_session(clear_cached_token=True)
        return False

    def ensure_live_session(self, force_reauth: bool = False, interactive: bool = True) -> bool:
        """Ensure an actually valid live broker session is available."""
        if not self.client_id or not self.secret_key:
            return False
        if not force_reauth and self.validate_session():
            return True
        if not interactive:
            return False
        return self.terminal_auth_flow()

    def get_login_url(self) -> str:
        """Generate the Fyers OAuth login URL."""
        try:
            from fyers_apiv3 import fyersModel
            session = fyersModel.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            return session.generate_authcode()
        except ImportError:
            return ""
        except Exception as e:
            print(f"  ⚠  Error generating auth URL: {e}")
            return ""

    @staticmethod
    def _open_login_url(login_url: str) -> bool:
        """
        Open login URL with platform-specific fallback.
        On macOS, prefer `open` to avoid noisy osascript failures in some shells.
        """
        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["open", login_url],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return result.returncode == 0
            return bool(webbrowser.open(login_url, new=2))
        except Exception:
            return False

    def terminal_auth_flow(self):
        """
        Interactive terminal authentication flow.
        1. Generates login URL
        2. Opens it in the user's browser
        3. Prompts user to paste the auth code from the redirect URL
        4. Generates and stores access token
        """
        if not self.client_id or not self.secret_key:
            print("\n  ⚠  FYERS_APP_ID and FYERS_SECRET_KEY not set in .env")
            print("  ⚠  Running in PAPER-ONLY mode with mock data\n")
            return False

        print("\n  ┌─────────────────────────────────────────────┐")
        print("  │         FYERS BROKER AUTHENTICATION          │")
        print("  └─────────────────────────────────────────────┘")

        login_url = self.get_login_url()
        if not login_url:
            print("  ⚠  Could not generate login URL. Running in paper mode.\n")
            return False

        print(f"\n  ▶ Opening browser for Fyers login...")
        print(f"  ▶ URL: {login_url[:80]}...\n")

        if not self._open_login_url(login_url):
            print(f"  ⚠  Could not open browser. Please visit this URL manually:")
            print(f"  {login_url}\n")

        print("  After logging in, you'll be redirected to a URL containing '?auth_code=...'")
        print("  Paste the auth_code OR the full redirected URL below.\n")

        auth_input = self._prompt_line("  ▸ Enter auth code / redirect URL: ").strip()
        auth_code = self._extract_auth_code(auth_input)

        if not auth_code:
            print("  ⚠  No auth code entered. Running in paper mode.\n")
            return False

        token = self.generate_access_token(auth_code)
        if not token:
            print("  ❌ Authentication failed. Running in paper mode.\n")
            return False

        self._persist_token()
        if self.validate_session():
            print("  ✅ Authentication successful! Live broker connection active.\n")
            return True

        self._invalidate_session(clear_cached_token=True)
        print("  ❌ Token verification failed. Please retry authentication.\n")
        return False

    def generate_access_token(self, auth_code: str) -> str | None:
        """Exchange auth code for access token."""
        auth_code = self._extract_auth_code(auth_code)
        if not auth_code:
            return None
        try:
            from fyers_apiv3 import fyersModel
            session = fyersModel.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            session.set_token(auth_code)
            response = session.generate_token()
            if response.get("s") == "ok":
                self._bind_fyers_client(response["access_token"])
                return self.access_token
        except ImportError:
            print("  ⚠  fyers-apiv3 not installed")
        except Exception as e:
            print(f"  ⚠  Auth error: {e}")
        return None

    def get_profile(self) -> dict:
        if not self.is_authenticated:
            return {"error": "Not authenticated", "data": {"name": "Paper Trader", "fy_id": "PAPER"}}
        try:
            response = self.fyers.get_profile()
            if self._looks_like_auth_failure(response) or (isinstance(response, dict) and response.get("code") == -99):
                self._invalidate_session(clear_cached_token=True)
            return response
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _first_present(data: dict, keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return None

    @staticmethod
    def _normalize_iv(iv_raw: Any) -> float | None:
        iv = FyersAPIClient._to_float(iv_raw, 0.0)
        if iv <= 0:
            return None
        if iv > 3.0:
            iv /= 100.0
        if 0.001 <= iv <= 5.0:
            return iv
        return None

    @staticmethod
    def _choose_scaled_value(raw_value: Any, model_value: float, scales: tuple[float, ...], limit: float) -> float | None:
        raw = FyersAPIClient._to_float(raw_value, float("nan"))
        if math.isnan(raw):
            return None
        candidates = [raw * s for s in scales]
        best = min(candidates, key=lambda x: abs(x - model_value))
        if abs(best) > limit:
            return None
        return best

    @staticmethod
    def _compute_expiry_T(expiry_date_str: str) -> float:
        T = 7 / 365.0
        if not expiry_date_str:
            return T
        try:
            exp_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
            now = datetime.now()
            days_to_exp = (exp_dt - now).total_seconds() / 86400.0
            T = max(days_to_exp / 365.0, 1 / 365.0)
        except Exception:
            pass
        return T

    @staticmethod
    def _normalize_right(right_raw: Any) -> str | None:
        right = str(right_raw or "").strip().upper()
        if right in {"CE", "CALL", "C"}:
            return "CE"
        if right in {"PE", "PUT", "P"}:
            return "PE"
        return None

    @staticmethod
    def _normalize_symbol(symbol_raw: Any) -> str:
        return str(symbol_raw or "").strip()

    @staticmethod
    def _normalize_expiry_date(raw_value: Any) -> str:
        """
        Normalize various broker expiry formats to YYYY-MM-DD.
        """
        if raw_value is None:
            return ""
        if isinstance(raw_value, (int, float)):
            ts = float(raw_value)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                try:
                    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                except Exception:
                    return ""
            return ""
        value = str(raw_value).strip()
        if not value:
            return ""
        value_10 = value[:10]
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value_10 if fmt == "%Y-%m-%d" else value, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        try:
            return datetime.fromisoformat(value_10).strftime("%Y-%m-%d")
        except Exception:
            return ""

    @staticmethod
    def _sorted_unique_expiries(values: list[Any]) -> list[str]:
        normalized = []
        for value in values:
            exp = FyersAPIClient._normalize_expiry_date(value)
            if exp:
                normalized.append(exp)
        if not normalized:
            return []
        ordered = sorted(set(normalized))
        today = datetime.now().date()
        future = []
        for exp in ordered:
            try:
                if datetime.strptime(exp, "%Y-%m-%d").date() >= today:
                    future.append(exp)
            except Exception:
                continue
        return future or ordered

    @staticmethod
    def _choose_active_expiry(expiries: list[str], requested_expiry: str | None = None) -> str:
        if not expiries:
            return ""
        req = FyersAPIClient._normalize_expiry_date(requested_expiry) if requested_expiry else ""
        if req and req in expiries:
            return req
        today = datetime.now().date()
        for exp in expiries:
            try:
                if datetime.strptime(exp, "%Y-%m-%d").date() >= today:
                    return exp
            except Exception:
                continue
        return expiries[0]

    @staticmethod
    def _is_invalid_input_error(response: dict | None) -> bool:
        if not isinstance(response, dict):
            return False
        message = str(response.get("message", "")).lower()
        return response.get("code") in {-50, 400} and "valid input" in message

    @staticmethod
    def _extract_tick_messages(message: Any) -> list[dict]:
        """
        Normalize Fyers websocket payload variants into a flat list of tick dicts.
        Handles direct dict ticks and nested list envelopes.
        """
        ticks: list[dict] = []
        if isinstance(message, dict):
            if isinstance(message.get("symbol"), str):
                ticks.append(message)
            for key in ("d", "data"):
                nested = message.get(key)
                if not isinstance(nested, list):
                    continue
                for item in nested:
                    if isinstance(item, dict):
                        value = item.get("v")
                        if isinstance(value, dict):
                            ticks.append(value)
                        elif isinstance(item.get("symbol"), str):
                            ticks.append(item)
        elif isinstance(message, list):
            for item in message:
                ticks.extend(FyersAPIClient._extract_tick_messages(item))
        return ticks

    def _derive_premium(self, opt: dict) -> float:
        ltp = self._to_float(self._first_present(opt, ("ltp", "last_price", "premium", "lp", "close")), 0.0)
        bid = self._to_float(self._first_present(opt, ("bid", "bid_price")), 0.0)
        ask = self._to_float(self._first_present(opt, ("ask", "ask_price")), 0.0)

        premium = ltp
        reference = max(ltp, 1.0)
        if bid > 0 and ask > 0 and ask >= bid and (ask - bid) <= reference * 0.20:
            premium = (bid + ask) / 2.0
        return max(premium, 0.0)

    def _socket_access_token(self) -> str:
        if not self.access_token:
            return ""
        if ":" in self.access_token:
            return self.access_token
        return f"{self.client_id}:{self.access_token}"

    def _on_market_socket_message(self, message: dict):
        tick_messages = self._extract_tick_messages(message)
        if not tick_messages:
            return
        now = datetime.now()
        with self._ticks_lock:
            for tick in tick_messages:
                symbol = self._normalize_symbol(
                    self._first_present(tick, ("symbol", "sym", "name"))
                )
                if not symbol:
                    continue
                self._symbol_ticks[symbol] = {
                    "ltp": self._to_float(self._first_present(tick, ("ltp", "last_price", "lp")), 0.0),
                    "bid_price": self._to_float(self._first_present(tick, ("bid_price", "bid")), 0.0),
                    "ask_price": self._to_float(self._first_present(tick, ("ask_price", "ask")), 0.0),
                    "OI": self._to_float(self._first_present(tick, ("OI", "oi")), 0.0),
                    "vol_traded_today": self._to_float(self._first_present(tick, ("vol_traded_today", "volume")), 0.0),
                    "exch_feed_time": tick.get("exch_feed_time"),
                    "updated_at": now.isoformat(),
                }
                self._tick_count += 1
            self._last_tick_at = now

    def _on_market_socket_connect(self):
        self._socket_connected_at = datetime.now()
        if self._market_socket is None:
            return
        symbols = list(self._subscribed_symbols)
        if not symbols:
            return
        try:
            self._market_socket.subscribe(symbols=symbols, data_type="SymbolUpdate")
        except Exception:
            pass

    def _on_market_socket_error(self, _message):
        # Force re-creation on next subscription/check.
        with self._socket_lock:
            self._market_socket = None
            self._socket_connected_at = None
        return

    def _on_market_socket_close(self, _message):
        with self._socket_lock:
            self._market_socket = None
            self._socket_connected_at = None
        return

    def _ensure_market_socket(self):
        if not self.is_authenticated:
            return
        with self._socket_lock:
            if self._market_socket is not None:
                return
            try:
                from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket
                socket_token = self._socket_access_token()
                if not socket_token:
                    return
                self._market_socket = FyersDataSocket(
                    access_token=socket_token,
                    write_to_file=False,
                    log_path=os.path.join(os.path.dirname(__file__), "..", "data"),
                    litemode=False,
                    reconnect=True,
                    on_message=self._on_market_socket_message,
                    on_error=self._on_market_socket_error,
                    on_connect=self._on_market_socket_connect,
                    on_close=self._on_market_socket_close,
                    reconnect_retry=20,
                )
                self._market_socket.connect()
            except Exception:
                self._market_socket = None

    def _subscribe_market_symbols(self, symbols: list[str]):
        clean = {self._normalize_symbol(s) for s in symbols}
        clean = {s for s in clean if s}
        if not clean:
            return
        self._subscribed_symbols.update(clean)
        self._ensure_market_socket()
        if self._market_socket is None:
            return
        try:
            self._market_socket.subscribe(symbols=list(clean), data_type="SymbolUpdate")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────
    # Option Chain Data (live or mock)
    # ──────────────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> dict:
        """Get live quotes for given symbol list."""
        if not self.is_authenticated:
            return {}
        try:
            data = {"symbols": ",".join(symbols)}
            return self.fyers.quotes(data=data)
        except Exception as e:
            return {"error": str(e)}

    def _build_option_snapshot(
        self,
        opt: dict,
        *,
        premium: float,
        ltp: float | None,
        spot: float,
        strike: float,
        r: float,
        T: float,
        right: str,
        q: float,
    ) -> dict:
        from .pricing_engine import implied_volatility, delta as bsd, gamma as bsg, theta as bst, vega as bsv

        broker_iv = self._normalize_iv(self._first_present(opt, ("iv", "implied_volatility", "impliedVolatility", "implied_vol")))
        solved_iv = implied_volatility(premium, spot, strike, r, T, right, q=q) if premium > 0.05 else 0.0
        iv_used = broker_iv if broker_iv is not None else (solved_iv if solved_iv > 0 else 0.0)

        calc_delta = calc_gamma = calc_theta = calc_vega = 0.0
        if iv_used > 0:
            calc_delta = bsd(spot, strike, r, iv_used, T, right, q)
            calc_gamma = bsg(spot, strike, r, iv_used, T, q)
            calc_theta = bst(spot, strike, r, iv_used, T, right, q)
            calc_vega = bsv(spot, strike, r, iv_used, T, q)

        broker_delta = self._choose_scaled_value(
            self._first_present(opt, ("delta", "dlt", "greek_delta")),
            calc_delta,
            scales=(1.0, 0.01, 100.0),
            limit=2.0,
        )
        broker_gamma = self._choose_scaled_value(
            self._first_present(opt, ("gamma", "gma", "greek_gamma")),
            calc_gamma,
            scales=(1.0, 0.01, 100.0, 0.0001),
            limit=1.0,
        )
        broker_theta = self._choose_scaled_value(
            self._first_present(opt, ("theta", "th", "greek_theta")),
            calc_theta,
            scales=(1.0, 1 / 365.0, 365.0),
            limit=2000.0,
        )
        broker_vega = self._choose_scaled_value(
            self._first_present(opt, ("vega", "vg", "greek_vega")),
            calc_vega,
            scales=(1.0, 0.01, 100.0),
            limit=5000.0,
        )

        # Use broker Greeks only when they are directionally consistent with BSM,
        # otherwise keep model Greeks for stability.
        use_broker_delta = broker_delta is not None and abs(broker_delta - calc_delta) <= max(0.10, abs(calc_delta) * 0.35)
        use_broker_gamma = broker_gamma is not None and abs(broker_gamma - calc_gamma) <= max(0.002, abs(calc_gamma) * 0.60)
        use_broker_theta = broker_theta is not None and abs(broker_theta - calc_theta) <= max(5.0, abs(calc_theta) * 0.75)
        use_broker_vega = broker_vega is not None and abs(broker_vega - calc_vega) <= max(5.0, abs(calc_vega) * 0.60)

        delta_out = broker_delta if use_broker_delta else calc_delta
        gamma_out = broker_gamma if use_broker_gamma else calc_gamma
        theta_out = broker_theta if use_broker_theta else calc_theta
        vega_out = broker_vega if use_broker_vega else calc_vega

        broker_greek_flags = [use_broker_delta, use_broker_gamma, use_broker_theta, use_broker_vega]
        if all(broker_greek_flags):
            greeks_source = "broker"
        elif any(broker_greek_flags):
            greeks_source = "hybrid"
        else:
            greeks_source = "bsm"

        ltp_value = self._to_float(
            ltp,
            self._to_float(self._first_present(opt, ("ltp", "last_price", "lp", "close")), premium),
        )
        if ltp_value <= 0:
            ltp_value = premium

        option_symbol = self._normalize_symbol(
            self._first_present(
                opt,
                ("symbol", "option_symbol", "tradingsymbol", "trading_symbol", "name"),
            )
        )
        if not option_symbol:
            token_like = self._normalize_symbol(self._first_present(opt, ("fyToken", "fytoken")))
            if ":" in token_like:
                option_symbol = token_like

        return {
            "ltp": round(float(ltp_value), 2),
            "premium": round(float(premium), 2),
            "iv": round(float(iv_used * 100), 2),
            "delta": round(float(delta_out), 4),
            "gamma": round(float(gamma_out), 5),
            "theta": round(float(theta_out), 2),
            "vega": round(float(vega_out), 2),
            "oi": int(self._to_float(self._first_present(opt, ("oi", "OI")), 0.0)),
            "volume": int(self._to_float(self._first_present(opt, ("volume", "vol_traded_today")), 0.0)),
            "bid": round(float(self._to_float(self._first_present(opt, ("bid", "bid_price")), 0.0)), 2),
            "ask": round(float(self._to_float(self._first_present(opt, ("ask", "ask_price")), 0.0)), 2),
            "symbol": option_symbol,
            "iv_source": "broker" if broker_iv is not None else ("solver" if solved_iv > 0 else "none"),
            "greeks_source": greeks_source,
        }

    def _apply_stream_ticks_to_chain(self, normalized: dict) -> dict:
        if normalized.get("source") != "live":
            return normalized
        chain = normalized.get("chain", [])
        if not chain:
            return normalized

        symbol = normalized.get("symbol", "")
        expiry_date_str = normalized.get("expiry", "")
        spot = self._to_float(normalized.get("spot"), 0.0)

        with self._ticks_lock:
            underlying_tick = self._symbol_ticks.get(symbol, {})
            if underlying_tick.get("ltp", 0) > 0:
                spot = float(underlying_tick["ltp"])
                normalized["spot"] = round(spot, 2)
            ticks = dict(self._symbol_ticks)

        if spot <= 0:
            return normalized

        T = self._compute_expiry_T(expiry_date_str)
        r = 0.10
        q = 0.012 if "NIFTY" in symbol else 0.0

        for row in chain:
            strike = self._to_float(row.get("strike"), 0.0)
            if strike <= 0:
                continue
            for right in ("CE", "PE"):
                point = row.get(right, {})
                sym = point.get("symbol")
                if not sym:
                    continue
                tick = ticks.get(sym)
                if not tick:
                    continue
                ltp = self._to_float(tick.get("ltp"), 0.0)
                if ltp <= 0:
                    continue
                merged = dict(point)
                merged["ltp"] = ltp
                tick_bid = self._to_float(tick.get("bid_price"), 0.0)
                tick_ask = self._to_float(tick.get("ask_price"), 0.0)
                if tick_bid > 0:
                    merged["bid"] = tick_bid
                if tick_ask > 0:
                    merged["ask"] = tick_ask

                # Preserve chain OI/volume when stream payload has missing/zero fields.
                tick_oi = int(self._to_float(tick.get("OI"), -1.0))
                tick_volume = int(self._to_float(tick.get("vol_traded_today"), -1.0))
                if tick_oi > 0:
                    merged["oi"] = tick_oi
                if tick_volume > 0:
                    merged["volume"] = tick_volume
                # Avoid treating previously computed values as fresh broker inputs.
                if merged.get("iv_source") != "broker":
                    merged.pop("iv", None)
                    merged.pop("implied_volatility", None)
                    merged.pop("impliedVolatility", None)
                if merged.get("greeks_source") != "broker":
                    for greek_key in ("delta", "gamma", "theta", "vega", "dlt", "gma", "th", "vg"):
                        merged.pop(greek_key, None)

                bid = self._to_float(merged.get("bid"), 0.0)
                ask = self._to_float(merged.get("ask"), 0.0)
                premium = ltp
                if bid > 0 and ask > 0 and (ask - bid) < max(ltp, 1.0) * 0.20:
                    premium = (bid + ask) / 2.0

                updated = self._build_option_snapshot(
                    merged,
                    premium=premium,
                    ltp=ltp,
                    spot=spot,
                    strike=strike,
                    r=r,
                    T=T,
                    right=right,
                    q=q,
                )
                updated["symbol"] = sym
                row[right] = updated
        return normalized

    def _decorate_quote_feed(self, payload: dict) -> dict:
        now = datetime.now()
        with self._ticks_lock:
            tick_count = len(self._symbol_ticks)
            last_tick_at = self._last_tick_at

        tick_age_ms: int | None = None
        if last_tick_at is not None:
            tick_age_ms = int(max((now - last_tick_at).total_seconds() * 1000.0, 0))

        source = payload.get("source", "mock")
        quote_feed = "mock"
        if source == "live":
            if tick_count > 0 and tick_age_ms is not None and tick_age_ms <= 3000:
                quote_feed = "live-stream"
            else:
                quote_feed = "live-poll"

        payload["quote_feed"] = quote_feed
        payload["tick_count"] = tick_count
        payload["tick_age_ms"] = tick_age_ms
        payload["last_tick_age_ms"] = tick_age_ms
        if self._last_chain_error:
            payload["live_error"] = self._last_chain_error
        return payload

    def get_option_chain(self, symbol: str = "NSE:NIFTY50-INDEX", strike_count: int = 15, expiry: str = None) -> dict:
        """
        Get option chain data. Uses Fyers API when authenticated, else mock data.
        Returns normalized format: {symbol, spot, expiry, expiries[], strike_step, lot_size, chain[]}
        """
        expiry_norm = self._normalize_expiry_date(expiry) if expiry else ""
        cache_key = (symbol, expiry_norm, int(strike_count))
        cache_ttl_seconds = 2
        now = datetime.now()

        if self.is_authenticated:
            self._ensure_market_socket()

        cached = self._chain_cache.get(cache_key)
        if cached and (now - cached["updated"]).total_seconds() <= cache_ttl_seconds:
            hydrated = self._apply_stream_ticks_to_chain(copy.deepcopy(cached["data"]))
            return self._decorate_quote_feed(hydrated)

        if self.is_authenticated:
            try:
                req_data = {"symbol": symbol, "strikecount": strike_count}
                if expiry_norm:
                    req_data["expe"] = expiry_norm
                result = self.fyers.optionchain(data=req_data)

                if self._is_invalid_input_error(result) and expiry_norm:
                    # Expiry can become stale or invalid; retry without forcing expe.
                    req_data.pop("expe", None)
                    result = self.fyers.optionchain(data=req_data)
                    expiry_norm = ""

                if result.get("s") == "ok" and result.get("data"):
                    normalized = self._normalize_fyers_chain(result["data"], symbol, requested_expiry=expiry_norm)
                    live_cache_key = (symbol, normalized.get("expiry", ""), int(strike_count))
                    self._chain_cache[live_cache_key] = {"updated": now, "data": normalized}
                    if live_cache_key != cache_key:
                        self._chain_cache[cache_key] = {"updated": now, "data": normalized}
                    option_symbols: list[str] = [symbol]
                    for row in normalized.get("chain", []):
                        option_symbols.append(row.get("CE", {}).get("symbol", ""))
                        option_symbols.append(row.get("PE", {}).get("symbol", ""))
                    self._subscribe_market_symbols(option_symbols)
                    self._last_chain_error = None
                    hydrated = self._apply_stream_ticks_to_chain(copy.deepcopy(normalized))
                    return self._decorate_quote_feed(hydrated)
                if self._looks_like_auth_failure(result):
                    self._invalidate_session(clear_cached_token=True)
                    self._last_chain_error = "Auth/session invalid for option chain."
                elif self._is_invalid_input_error(result):
                    self._last_chain_error = f"Broker rejected option-chain input for {symbol} (expiry={expiry_norm or 'auto'})."
                elif isinstance(result, dict) and result.get("code") == -99 and not result.get("data"):
                    # SDK can wrap expired/invalid token errors as generic -99.
                    self.validate_session()
                    self._last_chain_error = "Broker returned -99 while fetching option chain."
                else:
                    self._last_chain_error = str(result.get("message", "Live option-chain unavailable"))
            except Exception as e:
                print(f"  ⚠  Chain fetch error: {e}")
                self._last_chain_error = str(e)

        if cached:
            hydrated = self._apply_stream_ticks_to_chain(copy.deepcopy(cached["data"]))
            return self._decorate_quote_feed(hydrated)

        # Fallback to the freshest live cache for this symbol/strike_count, if available.
        live_cache_candidates = [
            v for (sym, _exp, cnt), v in self._chain_cache.items()
            if sym == symbol and cnt == int(strike_count) and isinstance(v, dict)
            and isinstance(v.get("data"), dict) and v["data"].get("source") == "live"
        ]
        if live_cache_candidates:
            latest = max(live_cache_candidates, key=lambda entry: entry.get("updated", datetime.min))
            hydrated = self._apply_stream_ticks_to_chain(copy.deepcopy(latest["data"]))
            return self._decorate_quote_feed(hydrated)

        # Fallback to mock data
        return self._decorate_quote_feed(_generate_mock_chain(symbol))

    def get_available_expiries(self, symbol: str = "NSE:NIFTY50-INDEX") -> list[str]:
        """Get available expiry dates for an underlying."""
        if self.is_authenticated:
            try:
                result = self.fyers.optionchain(
                    data={"symbol": symbol, "strikecount": 5}
                )
                if result.get("s") == "ok" and result.get("data"):
                    exp_values: list[Any] = []
                    for exp_obj in result["data"].get("expiryData", []) or result["data"].get("expiry_data", []):
                        if isinstance(exp_obj, dict):
                            exp_values.append(exp_obj.get("date"))
                        else:
                            exp_values.append(exp_obj)
                    expiries = self._sorted_unique_expiries(exp_values)
                    if expiries:
                        return expiries
            except Exception:
                pass
            try:
                chain = self.get_option_chain(symbol=symbol, strike_count=15, expiry=None)
                expiries = self._sorted_unique_expiries(chain.get("expiries", []))
                if expiries:
                    return expiries
            except Exception:
                pass

        # Mock expiries
        return _generate_mock_expiries(symbol)

    def _normalize_fyers_chain(self, data: dict, symbol: str, requested_expiry: str | None = None) -> dict:
        """Normalize Fyers option chain response and reconcile broker Greeks/IV with BSM."""
        options_chain = data.get("optionsChain", []) or data.get("options_chain", [])

        # Extract expiry candidates
        exp_data = data.get("expiryData", []) or data.get("expiry_data", []) or []
        expiry_values: list[Any] = []
        for exp_obj in exp_data:
            if isinstance(exp_obj, dict):
                expiry_values.append(exp_obj.get("date"))
            else:
                expiry_values.append(exp_obj)
        if not expiry_values and options_chain:
            for opt in options_chain:
                expiry_raw = self._first_present(opt, ("expiry", "expiry_date", "expiryDate", "date"))
                if expiry_raw:
                    expiry_values.append(expiry_raw)
        sorted_expiries = self._sorted_unique_expiries(expiry_values)
        expiry_date_str = self._choose_active_expiry(sorted_expiries, requested_expiry=requested_expiry)

        spot = self._to_float(
            self._first_present(
                data,
                ("ltp", "underlyingLtp", "underlying_ltp", "spot", "underlyingValue"),
            ),
            0.0,
        )
        if spot <= 0 and options_chain:
            mid = len(options_chain) // 2
            spot = self._to_float(
                self._first_present(options_chain[mid], ("strike_price", "strike", "strikePrice")),
                0.0,
            )

        lot_size_raw = self._first_present(data, ("lot_size", "lotSize", "lotsize", "default_lot_size"))
        default_lot_size = self._default_lot_size(symbol)
        if "NIFTY" in str(symbol).upper():
            lot_size = default_lot_size
        elif lot_size_raw is None:
            lot_size = default_lot_size
        else:
            lot_size = max(int(self._to_float(lot_size_raw, float(default_lot_size))), 1)

        if not options_chain:
            return {
                "symbol": symbol,
                "spot": round(spot, 2) if spot > 0 else (24200.0 if "BANK" not in symbol else 51500.0),
                "expiry": expiry_date_str,
                "expiries": sorted_expiries,
                "strike_step": 50 if "BANK" not in symbol else 100,
                "lot_size": lot_size,
                "chain": [],
                "source": "live",
            }

        T = self._compute_expiry_T(expiry_date_str)
        r = 0.10
        q = 0.012 if "NIFTY" in symbol else 0.0

        def _empty_side() -> dict:
            return {
                "ltp": 0.0,
                "premium": 0.0,
                "iv": 0.0,
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "oi": 0,
                "volume": 0,
                "bid": 0.0,
                "ask": 0.0,
                "symbol": "",
                "iv_source": "none",
                "greeks_source": "bsm",
            }

        strikes_map: dict[float, dict[str, Any]] = {}
        for opt in options_chain:
            strike = self._to_float(self._first_present(opt, ("strike_price", "strike", "strikePrice")), 0.0)
            if strike <= 0:
                continue
            right = self._normalize_right(
                self._first_present(opt, ("option_type", "right", "type", "optionType"))
            )
            if right is None:
                continue

            premium = self._derive_premium(opt)
            row = strikes_map.setdefault(
                strike,
                {"strike": int(round(strike)), "CE": _empty_side(), "PE": _empty_side()},
            )
            row[right] = self._build_option_snapshot(
                opt,
                premium=premium,
                ltp=self._to_float(self._first_present(opt, ("ltp", "last_price", "lp")), premium),
                spot=spot if spot > 0 else strike,
                strike=strike,
                r=r,
                T=T,
                right=right,
                q=q,
            )

        chain = sorted(strikes_map.values(), key=lambda x: x["strike"])
        if spot <= 0 and chain:
            spot = float(chain[len(chain) // 2]["strike"])

        unique_strikes = sorted({float(r["strike"]) for r in chain})
        if len(unique_strikes) >= 2:
            diffs = [abs(unique_strikes[i] - unique_strikes[i - 1]) for i in range(1, len(unique_strikes))]
            strike_step = int(round(min(d for d in diffs if d > 0), 0)) if any(d > 0 for d in diffs) else 100
        else:
            strike_step = 100

        return {
            "symbol": symbol,
            "spot": round(spot, 2) if spot > 0 else (chain[len(chain) // 2]["strike"] if chain else 22500),
            "expiry": expiry_date_str,
            "expiries": sorted_expiries,
            "strike_step": strike_step,
            "lot_size": lot_size,
            "chain": chain,
            "source": "live",
        }

    # ──────────────────────────────────────────────────────────
    # Order Placement & Monitoring
    # ──────────────────────────────────────────────────────────

    def place_order(self, order_data: dict) -> dict:
        """Place a single order via Fyers."""
        if not self.is_authenticated:
            return {"error": "Not authenticated", "status": "rejected"}
        try:
            return self.fyers.place_order(data=order_data)
        except Exception as e:
            return {"error": str(e), "status": "rejected"}

    def place_basket_order(self, orders: list[dict]) -> list[dict]:
        """Place a multi-leg basket order for strategy deployment."""
        if not self.is_authenticated:
            return [{"error": "Not authenticated"}]
        results = []
        for order in orders:
            result = self.place_order(order)
            results.append(result)
        return results

    def deploy_strategy(self, legs: list[dict], underlying: str = "NIFTY") -> dict:
        """
        Deploy a complete strategy to the broker.
        Converts our leg format to Fyers order format and places as basket.
        """
        if not self.is_authenticated:
            return {"error": "Not authenticated. Connect broker first.", "status": "rejected"}

        orders = []
        for leg in legs:
            symbol = leg.get("symbol", "")
            if not symbol:
                # Build symbol from components
                symbol = f"NSE:{underlying}-OPT-{leg['strike']}-{leg['right']}"

            order = {
                "symbol": symbol,
                "qty": leg["qty"],
                "type": 2,  # Market order
                "side": 1 if leg["side"] == "BUY" else -1,
                "productType": "INTRADAY",
                "limitPrice": 0,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
            }
            orders.append(order)

        results = self.place_basket_order(orders)
        return {
            "status": "deployed",
            "orders": results,
            "num_legs": len(orders),
            "timestamp": datetime.now().isoformat(),
        }

    def get_positions(self) -> dict:
        """Get current positions from broker."""
        if not self.is_authenticated:
            return {"error": "Not authenticated", "positions": []}
        try:
            response = self.fyers.positions()
            if self._looks_like_auth_failure(response):
                self._invalidate_session(clear_cached_token=True)
            elif isinstance(response, dict) and response.get("code") == -99:
                self.validate_session()
            return response
        except Exception as e:
            return {"error": str(e), "positions": []}

    def get_orders(self) -> dict:
        """Get order book from broker."""
        if not self.is_authenticated:
            return {"error": "Not authenticated", "orders": []}
        try:
            response = self.fyers.orderbook()
            if self._looks_like_auth_failure(response):
                self._invalidate_session(clear_cached_token=True)
            elif isinstance(response, dict) and response.get("code") == -99:
                self.validate_session()
            return response
        except Exception as e:
            return {"error": str(e), "orders": []}

    def get_funds(self) -> dict:
        """Get available funds from broker."""
        if not self.is_authenticated:
            return {"error": "Not authenticated", "fund_limit": []}
        try:
            response = self.fyers.funds()
            if self._looks_like_auth_failure(response):
                self._invalidate_session(clear_cached_token=True)
            elif isinstance(response, dict) and response.get("code") == -99:
                self.validate_session()
            return response
        except Exception as e:
            return {"error": str(e), "fund_limit": []}


# ──────────────────────────────────────────────────────────────
# Mock Data Generator (for paper mode)
# ──────────────────────────────────────────────────────────────

def _mock_expiry_weekday(symbol: str) -> int:
    """
    Return weekly expiry weekday index (Mon=0).
    NIFTY: Tuesday, BANKNIFTY: Wednesday, fallback: Thursday.
    """
    s = str(symbol or "").upper()
    if "BANK" in s:
        return 2
    if "NIFTY" in s:
        return 1
    return 3


def _generate_mock_expiries(symbol: str, count: int = 6) -> list[str]:
    today = datetime.now()
    target_weekday = _mock_expiry_weekday(symbol)
    expiries: list[str] = []
    days_until_target = (target_weekday - today.weekday()) % 7
    for i in range(count):
        exp = today + timedelta(days=days_until_target + (7 * i))
        expiries.append(exp.strftime("%Y-%m-%d"))
    return expiries


def _generate_mock_chain(symbol: str = "NSE:NIFTY50-INDEX") -> dict:
    """Generate realistic mock option chain data for paper trading."""
    # Use realistic current market spot prices for mock data
    spot = 24200.0
    if "BANK" in symbol:
        spot = 51500.0
    strike_step = 50 if "BANK" not in symbol else 100
    num_strikes = 15
    base_iv = 0.14
    lot_size = 65 if "BANK" not in symbol else 30

    # Generate weekly expiries
    expiries = _generate_mock_expiries(symbol, count=6)

    chain = []
    for i in range(-num_strikes, num_strikes + 1):
        strike = round(spot + i * strike_step)
        moneyness = (strike - spot) / spot

        iv_adjust = 0.03 * abs(moneyness) * 10
        ce_iv = base_iv + iv_adjust + (0.008 if moneyness > 0 else 0)
        pe_iv = base_iv + iv_adjust + (0.008 if moneyness < 0 else 0)

        T = 7 / 365.0
        ce_premium = max(spot - strike, 0) + spot * ce_iv * math.sqrt(T) * 0.4
        pe_premium = max(strike - spot, 0) + spot * pe_iv * math.sqrt(T) * 0.4

        ce_delta = max(0.05, min(0.95, 0.5 - moneyness * 3))
        pe_delta = ce_delta - 1.0

        base_oi = 80000
        oi_factor = max(0.15, 1.0 - abs(moneyness) * 4)

        chain.append({
            "strike": strike,
            "CE": {
                "ltp": round(ce_premium, 2),
                "premium": round(ce_premium, 2),
                "iv": round(ce_iv * 100, 2),
                "delta": round(ce_delta, 3),
                "gamma": round(0.001 * max(0, 1 - abs(moneyness) * 3), 5),
                "theta": round(-spot * ce_iv / (2 * math.sqrt(T) * 365), 2),
                "vega": round(spot * math.sqrt(T) * 0.01, 2),
                "oi": int(base_oi * oi_factor),
                "volume": int(base_oi * oi_factor * 0.3),
                "bid": round(ce_premium * 0.98, 2),
                "ask": round(ce_premium * 1.02, 2),
            },
            "PE": {
                "ltp": round(pe_premium, 2),
                "premium": round(pe_premium, 2),
                "iv": round(pe_iv * 100, 2),
                "delta": round(pe_delta, 3),
                "gamma": round(0.001 * max(0, 1 - abs(moneyness) * 3), 5),
                "theta": round(-spot * pe_iv / (2 * math.sqrt(T) * 365), 2),
                "vega": round(spot * math.sqrt(T) * 0.01, 2),
                "oi": int(base_oi * oi_factor),
                "volume": int(base_oi * oi_factor * 0.25),
                "bid": round(pe_premium * 0.98, 2),
                "ask": round(pe_premium * 1.02, 2),
            },
        })

    return {
        "symbol": symbol,
        "spot": spot,
        "expiry": expiries[0] if expiries else _generate_mock_expiries(symbol, count=1)[0],
        "expiries": expiries,
        "strike_step": strike_step,
        "lot_size": lot_size,
        "chain": chain,
        "source": "mock",
    }
