"""
Quant Engine v1
================
Implements a practical first version of:
1) Semi-autonomous approvals + managed actions
2) Live portfolio Greek optimizer
3) Regime-adaptive strategy selection
4) Auto-adjustment logic for stressed positions
5) Execution intelligence (slicing, slippage, liquidity)
6) Personalized quant profile
7) Confidence + stress scoring
8) Journal + learning summary loop
9) Multi-asset universe with hedge routing
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
import math
import threading
from typing import Any
from uuid import uuid4

from .db import QuantEngineDB
from .models import (
    ConcreteLeg,
    OptionRight,
    Side,
    StrategyCategory,
    StrategyTemplate,
    PayoffType,
)
from .pricing_engine import (
    compute_strategy_greeks,
    compute_strategy_metrics,
    compute_enhanced_metrics,
    scenario_analysis,
)
from .strategies import get_strategy_by_id
from .market_schedule import market_status


SUPPORTED_ASSETS: dict[str, dict[str, Any]] = {
    "NSE:NIFTY50-INDEX": {
        "display": "NIFTY 50",
        "asset_class": "INDEX_OPTION",
        "lot_size": 65,
        "hedge_symbol": "NSE:NIFTY50-INDEX",
    },
    "NSE:NIFTYBANK-INDEX": {
        "display": "BANKNIFTY",
        "asset_class": "INDEX_OPTION",
        "lot_size": 30,
        "hedge_symbol": "NSE:NIFTYBANK-INDEX",
    },
    "NSE:FINNIFTY-INDEX": {
        "display": "FINNIFTY",
        "asset_class": "INDEX_OPTION",
        "lot_size": 40,
        "hedge_symbol": "NSE:FINNIFTY-INDEX",
    },
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize_underlying(symbol: str) -> str:
    s = str(symbol or "").upper()
    if "BANK" in s:
        return "NSE:NIFTYBANK-INDEX"
    if "FIN" in s:
        return "NSE:FINNIFTY-INDEX"
    if "NIFTY" in s:
        return "NSE:NIFTY50-INDEX"
    return symbol


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


@dataclass
class _Action:
    action_type: str
    reason: str
    payload: dict[str, Any]


class QuantEngineService:
    def __init__(self, fyers_client: Any, paper_engine: Any):
        self.fyers_client = fyers_client
        self.paper_engine = paper_engine
        self.db = QuantEngineDB()
        self._lock = threading.Lock()

        self.profile = self.db.get_profile() or self._default_profile()
        self.autopilot_state = self.db.get_autopilot_state() or self._default_autopilot_state()
        self.db.save_profile(self.profile)
        self.db.save_autopilot_state(self.autopilot_state)

    # -------------------------------------------------------------------------
    # Profile + State
    # -------------------------------------------------------------------------
    def _default_profile(self) -> dict[str, Any]:
        return {
            "user_id": "default",
            "risk_mode": "balanced",  # conservative | balanced | aggressive
            "capital_limit": 1_000_000,
            "preferred_dte_min": 3,
            "preferred_dte_max": 14,
            "preferred_underlyings": [
                "NSE:NIFTY50-INDEX",
                "NSE:NIFTYBANK-INDEX",
            ],
            "target_delta": 0.0,
            "target_vega": 0.0,
            "max_margin_utilization_pct": 65.0,
            "repair_loss_trigger_pct": 0.02,
            "max_spread_pct": 0.03,
            "min_oi": 50_000,
            "min_volume": 500,
            "max_slice_lots": 2,
            "slippage_tolerance_bps": 25.0,
            "allow_live_execution": False,
            "updated_at": _now_iso(),
        }

    def _default_autopilot_state(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "mode": "paper",  # paper | live
            "approval_id": "",
            "approval_note": "",
            "approved_at": None,
            "rebalance_interval_sec": 30,
            "allow_strategy_switch": True,
            "allow_live_execution": False,
            "max_active_rebalance_per_symbol": 1,
            "last_run_at": None,
            "last_result": None,
        }

    def get_profile(self) -> dict[str, Any]:
        return dict(self.profile)

    def update_profile(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "risk_mode",
            "capital_limit",
            "preferred_dte_min",
            "preferred_dte_max",
            "preferred_underlyings",
            "target_delta",
            "target_vega",
            "max_margin_utilization_pct",
            "repair_loss_trigger_pct",
            "max_spread_pct",
            "min_oi",
            "min_volume",
            "max_slice_lots",
            "slippage_tolerance_bps",
            "allow_live_execution",
        }
        for k, v in (patch or {}).items():
            if k not in allowed:
                continue
            self.profile[k] = v

        self.profile["preferred_underlyings"] = [
            _normalize_underlying(s)
            for s in self.profile.get("preferred_underlyings", [])
            if isinstance(s, str) and s.strip()
        ] or ["NSE:NIFTY50-INDEX"]

        self.profile["capital_limit"] = float(max(_safe_float(self.profile.get("capital_limit"), 1_000_000), 50_000))
        self.profile["preferred_dte_min"] = int(max(0, _safe_float(self.profile.get("preferred_dte_min"), 3)))
        self.profile["preferred_dte_max"] = int(max(self.profile["preferred_dte_min"], _safe_float(self.profile.get("preferred_dte_max"), 14)))
        self.profile["max_margin_utilization_pct"] = _clamp(_safe_float(self.profile.get("max_margin_utilization_pct"), 65.0), 1.0, 100.0)
        self.profile["repair_loss_trigger_pct"] = _clamp(_safe_float(self.profile.get("repair_loss_trigger_pct"), 0.02), 0.001, 0.2)
        self.profile["max_spread_pct"] = _clamp(_safe_float(self.profile.get("max_spread_pct"), 0.03), 0.001, 0.2)
        self.profile["min_oi"] = int(max(0, _safe_float(self.profile.get("min_oi"), 50_000)))
        self.profile["min_volume"] = int(max(0, _safe_float(self.profile.get("min_volume"), 500)))
        self.profile["max_slice_lots"] = int(max(1, _safe_float(self.profile.get("max_slice_lots"), 2)))
        self.profile["slippage_tolerance_bps"] = _clamp(_safe_float(self.profile.get("slippage_tolerance_bps"), 25.0), 1.0, 500.0)
        self.profile["updated_at"] = _now_iso()

        self.db.save_profile(self.profile)
        self.db.append_journal("profile_updated", {"profile": self.profile})
        return self.get_profile()

    def get_autopilot_state(self) -> dict[str, Any]:
        return dict(self.autopilot_state)

    def approve_autopilot(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = config or {}
        state = dict(self.autopilot_state)
        state["enabled"] = True
        state["mode"] = "live" if str(cfg.get("mode", "paper")).lower() == "live" else "paper"
        state["approval_id"] = str(uuid4())[:12]
        state["approval_note"] = str(cfg.get("approval_note", "user-approved-autopilot"))
        state["approved_at"] = _now_iso()
        state["rebalance_interval_sec"] = int(max(10, _safe_float(cfg.get("rebalance_interval_sec", state.get("rebalance_interval_sec", 30)))))
        state["allow_strategy_switch"] = bool(cfg.get("allow_strategy_switch", state.get("allow_strategy_switch", True)))
        state["allow_live_execution"] = bool(cfg.get("allow_live_execution", state.get("allow_live_execution", False)))
        state["max_active_rebalance_per_symbol"] = int(_clamp(
            _safe_float(
                cfg.get(
                    "max_active_rebalance_per_symbol",
                    state.get("max_active_rebalance_per_symbol", 1),
                ),
                1.0,
            ),
            1.0,
            10.0,
        ))
        state["last_result"] = None
        self.autopilot_state = state
        self.db.save_autopilot_state(self.autopilot_state)
        self.db.append_journal("autopilot_approved", {"state": self.autopilot_state})
        return self.get_autopilot_state()

    def pause_autopilot(self, reason: str = "manual pause") -> dict[str, Any]:
        self.autopilot_state["enabled"] = False
        self.autopilot_state["approval_note"] = str(reason or "manual pause")
        self.autopilot_state["last_result"] = {"status": "paused", "reason": reason}
        self.db.save_autopilot_state(self.autopilot_state)
        self.db.append_journal("autopilot_paused", {"reason": reason})
        return self.get_autopilot_state()

    # -------------------------------------------------------------------------
    # Capability #9 Multi-Asset universe
    # -------------------------------------------------------------------------
    def get_supported_assets(self) -> list[dict[str, Any]]:
        rows = []
        for symbol, meta in SUPPORTED_ASSETS.items():
            rows.append({
                "symbol": symbol,
                "display": meta["display"],
                "asset_class": meta["asset_class"],
                "default_lot_size": meta["lot_size"],
                "hedge_symbol": meta["hedge_symbol"],
            })
        return rows

    # -------------------------------------------------------------------------
    # Capability #3 Adaptive regime + strategy mapping
    # -------------------------------------------------------------------------
    def analyze_regime(self, underlying: str, chain_data: dict | None = None) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
        chain = chain_data.get("chain", []) or []
        spot = _safe_float(chain_data.get("spot"), 0.0)

        if not chain or spot <= 0:
            out = {
                "symbol": symbol,
                "regime": "NO_DATA",
                "confidence": 0.2,
                "metrics": {},
                "recommended_strategy_ids": [19],
            }
            self.db.append_journal("regime_scan", out, symbol=symbol)
            return out

        strikes = sorted([_safe_float(r.get("strike"), 0.0) for r in chain if _safe_float(r.get("strike"), 0.0) > 0])
        atm = min(strikes, key=lambda s: abs(s - spot))
        row_map = {int(round(_safe_float(r.get("strike"), 0.0))): r for r in chain}
        atm_row = row_map.get(int(round(atm)), {})
        atm_ce = atm_row.get("CE", {}) or {}
        atm_pe = atm_row.get("PE", {}) or {}
        atm_iv = (_safe_float(atm_ce.get("iv")) + _safe_float(atm_pe.get("iv"))) / 2.0

        total_ce_oi = sum(int(_safe_float((r.get("CE", {}) or {}).get("oi"), 0.0)) for r in chain)
        total_pe_oi = sum(int(_safe_float((r.get("PE", {}) or {}).get("oi"), 0.0)) for r in chain)
        pcr_oi = (total_pe_oi / max(total_ce_oi, 1))

        idx = strikes.index(atm)
        put_idx = max(0, idx - 2)
        call_idx = min(len(strikes) - 1, idx + 2)
        put_row = row_map.get(int(round(strikes[put_idx])), {})
        call_row = row_map.get(int(round(strikes[call_idx])), {})
        otm_put_iv = _safe_float((put_row.get("PE", {}) or {}).get("iv"), atm_iv)
        otm_call_iv = _safe_float((call_row.get("CE", {}) or {}).get("iv"), atm_iv)
        skew = otm_put_iv - otm_call_iv

        if atm_iv >= 24 and abs(skew) >= 2.0:
            regime = "EVENT_VOLATILE"
        elif atm_iv <= 12 and 0.9 <= pcr_oi <= 1.1:
            regime = "RANGE_LOW_VOL"
        elif pcr_oi >= 1.15:
            regime = "TREND_UP"
        elif pcr_oi <= 0.85:
            regime = "TREND_DOWN"
        elif atm_iv >= 20:
            regime = "HIGH_VOL_MEAN_REVERT"
        else:
            regime = "BALANCED"

        strategy_ids = self._strategy_ids_for_regime(regime, self.profile.get("risk_mode", "balanced"))
        confidence = _clamp(
            0.55
            + (0.15 if regime != "BALANCED" else 0.0)
            + (0.10 if abs(skew) >= 1.5 else 0.0)
            + (0.10 if atm_iv >= 16 else -0.05),
            0.2,
            0.95,
        )

        out = {
            "symbol": symbol,
            "regime": regime,
            "confidence": round(confidence, 3),
            "metrics": {
                "spot": round(spot, 2),
                "atm_strike": int(round(atm)),
                "atm_iv": round(atm_iv, 2),
                "pcr_oi": round(pcr_oi, 3),
                "skew_put_minus_call": round(skew, 3),
            },
            "recommended_strategy_ids": strategy_ids,
        }
        self.db.append_journal("regime_scan", out, symbol=symbol)
        return out

    def _strategy_ids_for_regime(self, regime: str, risk_mode: str) -> list[int]:
        conservative = {
            "RANGE_LOW_VOL": [19, 10, 9],
            "EVENT_VOLATILE": [12, 14, 20],
            "TREND_UP": [8, 10, 1],
            "TREND_DOWN": [11, 9, 3],
            "HIGH_VOL_MEAN_REVERT": [19, 10, 9],
            "BALANCED": [19, 8, 11],
        }
        aggressive = {
            "RANGE_LOW_VOL": [15, 13, 19],
            "EVENT_VOLATILE": [12, 14, 23],
            "TREND_UP": [1, 23, 8],
            "TREND_DOWN": [3, 24, 11],
            "HIGH_VOL_MEAN_REVERT": [15, 19, 9],
            "BALANCED": [19, 15, 8],
        }
        selected = conservative if str(risk_mode).lower().startswith("con") else aggressive if str(risk_mode).lower().startswith("agg") else {
            "RANGE_LOW_VOL": [19, 15, 10],
            "EVENT_VOLATILE": [12, 14, 20],
            "TREND_UP": [8, 1, 10],
            "TREND_DOWN": [11, 3, 9],
            "HIGH_VOL_MEAN_REVERT": [19, 10, 9],
            "BALANCED": [19, 8, 11],
        }
        return selected.get(regime, [19, 8, 11])

    # -------------------------------------------------------------------------
    # Capability #3 + #7 + #5 Combined recommendation payload
    # -------------------------------------------------------------------------
    def build_adaptive_recommendation(self, underlying: str, num_lots: int = 1) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = self.fyers_client.get_option_chain(symbol)
        regime = self.analyze_regime(symbol, chain_data=chain_data)
        picked_id = regime["recommended_strategy_ids"][0]
        template = get_strategy_by_id(int(picked_id))
        if not template:
            return {
                "error": f"Strategy template {picked_id} unavailable",
                "regime": regime,
            }

        legs = self._resolve_template_to_legs(template, chain_data, num_lots=max(1, int(num_lots)))
        spot = _safe_float(chain_data.get("spot"), 0.0)
        decision = self.score_decision(symbol, legs, chain_data=chain_data, spot=spot)
        execution = self.build_execution_plan(symbol, legs, chain_data=chain_data)

        payload = {
            "symbol": symbol,
            "regime": regime,
            "strategy": {
                "id": template.id,
                "name": template.name,
                "category": template.category.value,
                "description": template.primary_view,
            },
            "legs": [l.model_dump() for l in legs],
            "decision": decision,
            "execution_plan": execution,
        }
        self.db.append_journal("adaptive_recommendation", payload, symbol=symbol)
        return payload

    def _resolve_template_to_legs(self, template: StrategyTemplate, chain_data: dict, num_lots: int = 1) -> list[ConcreteLeg]:
        chain = chain_data.get("chain", []) or []
        spot = _safe_float(chain_data.get("spot"), 0.0)
        expiry = str(chain_data.get("expiry", "") or "")
        lot_size = int(_safe_float(chain_data.get("lot_size"), self._lot_size_for_symbol(chain_data.get("symbol", ""))))
        if not chain:
            return []
        strikes = sorted({_safe_float(r.get("strike"), 0.0) for r in chain if _safe_float(r.get("strike"), 0.0) > 0})
        if not strikes:
            return []

        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        row_map = {int(round(_safe_float(r.get("strike"), 0.0))): r for r in chain}

        out: list[ConcreteLeg] = []
        for leg_tmpl in template.legs:
            idx = max(0, min(len(strikes) - 1, atm_idx + int(leg_tmpl.strike_offset)))
            strike = strikes[idx]
            row = row_map.get(int(round(strike)), {})
            side_data = row.get(leg_tmpl.right.value, {}) or {}
            premium = _safe_float(side_data.get("premium"), 0.0)
            iv_raw = _safe_float(side_data.get("iv"), 0.0)
            iv = iv_raw / 100.0 if iv_raw > 1.0 else iv_raw

            out.append(ConcreteLeg(
                side=leg_tmpl.side,
                right=leg_tmpl.right,
                strike=float(strike),
                premium=float(max(premium, 0.0)),
                qty=max(1, lot_size * max(1, int(num_lots)) * max(1, int(leg_tmpl.qty_multiplier))),
                expiry=expiry,
                iv=iv if iv > 0 else 0.18,
                delta=side_data.get("delta"),
                gamma=side_data.get("gamma"),
                vega=side_data.get("vega"),
                theta=side_data.get("theta"),
            ))
        return out

    # -------------------------------------------------------------------------
    # Capability #5 Execution intelligence
    # -------------------------------------------------------------------------
    def build_execution_plan(
        self,
        underlying: str,
        legs: list[ConcreteLeg],
        chain_data: dict | None = None,
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
        profile = profile or self.profile
        chain = chain_data.get("chain", []) or []
        lot_size = int(_safe_float(chain_data.get("lot_size"), self._lot_size_for_symbol(symbol)))
        min_oi = int(_safe_float(profile.get("min_oi"), 50_000))
        min_vol = int(_safe_float(profile.get("min_volume"), 500))
        max_spread_pct = _clamp(_safe_float(profile.get("max_spread_pct"), 0.03), 0.001, 0.2)
        slip_bps = _clamp(_safe_float(profile.get("slippage_tolerance_bps"), 25.0), 1.0, 500.0)
        slip = slip_bps / 10_000.0
        max_slice_lots = int(max(1, _safe_float(profile.get("max_slice_lots"), 2)))
        max_slice_qty = max(1, lot_size * max_slice_lots)

        row_map = {int(round(_safe_float(r.get("strike"), 0.0))): r for r in chain}
        order_slices: list[dict[str, Any]] = []
        leg_checks: list[dict[str, Any]] = []
        warnings: list[str] = []
        execution_ready = True
        notional = 0.0

        for leg in legs:
            leg_info = {
                "side": leg.side.value,
                "right": leg.right.value,
                "strike": leg.strike,
                "qty": leg.qty,
                "liquidity_ok": True,
                "spread_pct": 0.0,
                "oi": 0,
                "volume": 0,
            }
            symbol_hint = ""
            premium = float(max(_safe_float(leg.premium), 0.0))
            bid = ask = 0.0

            if leg.right != OptionRight.FUT:
                row = row_map.get(int(round(_safe_float(leg.strike))), {})
                opt = row.get(leg.right.value, {}) if row else {}
                if not opt:
                    execution_ready = False
                    leg_info["liquidity_ok"] = False
                    warnings.append(f"Missing chain quote for {leg.strike} {leg.right.value}")
                    leg_checks.append(leg_info)
                    continue

                symbol_hint = str(opt.get("symbol", "") or "")
                premium = _safe_float(opt.get("ltp"), _safe_float(opt.get("premium"), premium))
                bid = _safe_float(opt.get("bid"), 0.0)
                ask = _safe_float(opt.get("ask"), 0.0)
                oi = int(_safe_float(opt.get("oi"), 0.0))
                vol = int(_safe_float(opt.get("volume"), 0.0))
                spread_pct = ((ask - bid) / max(premium, 1.0)) if bid > 0 and ask > 0 else 0.0

                liquid = oi >= min_oi and vol >= min_vol and (spread_pct <= max_spread_pct if spread_pct > 0 else True)
                if not liquid:
                    execution_ready = False
                    leg_info["liquidity_ok"] = False
                    warnings.append(
                        f"Liquidity guard failed for {leg.strike} {leg.right.value}: OI={oi}, VOL={vol}, spread={spread_pct:.3f}"
                    )
                leg_info["oi"] = oi
                leg_info["volume"] = vol
                leg_info["spread_pct"] = round(spread_pct, 4)
            else:
                symbol_hint = symbol

            qty_left = int(max(1, leg.qty))
            slice_no = 0
            while qty_left > 0:
                qty = min(qty_left, max_slice_qty)
                qty_left -= qty
                slice_no += 1

                if leg.side == Side.BUY:
                    limit_price = ask if ask > 0 else premium * (1 + slip)
                    limit_price = min(limit_price * (1 + slip), premium * (1 + (2 * slip)))
                else:
                    limit_price = bid if bid > 0 else premium * (1 - slip)
                    limit_price = max(limit_price * (1 - slip), premium * (1 - (2 * slip)))

                limit_price = round(max(limit_price, 0.05), 2)
                notional += limit_price * qty
                order_slices.append({
                    "slice_no": slice_no,
                    "symbol": symbol_hint,
                    "side": leg.side.value,
                    "right": leg.right.value,
                    "strike": leg.strike,
                    "qty": qty,
                    "order_type": "LIMIT",
                    "limit_price": limit_price,
                    "slippage_bps": slip_bps,
                })

            leg_checks.append(leg_info)

        return {
            "execution_ready": execution_ready,
            "symbol": symbol,
            "estimated_notional": round(notional, 2),
            "order_slices": order_slices,
            "liquidity_checks": leg_checks,
            "warnings": warnings,
        }

    # -------------------------------------------------------------------------
    # Capability #7 Probabilistic scoring + stress testing
    # -------------------------------------------------------------------------
    def score_decision(
        self,
        underlying: str,
        legs: list[ConcreteLeg],
        chain_data: dict | None = None,
        spot: float | None = None,
    ) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
        spot = float(spot if spot is not None else _safe_float(chain_data.get("spot"), 0.0))
        if spot <= 0:
            return {"confidence": 0.0, "grade": "D", "reason": "No live spot/chain data"}

        metrics = compute_strategy_metrics(spot, legs)
        dte = self._infer_dte_from_legs(legs, fallback=7)
        enhanced = compute_enhanced_metrics(spot, legs, dte=dte, underlying=symbol)
        greeks = compute_strategy_greeks(spot=spot, legs=legs, underlying=symbol)
        stress = self._run_stress_suite(spot, legs, symbol)

        liq_score = self._liquidity_score(legs, chain_data)
        pop_score = _clamp(_safe_float(enhanced.get("pop"), 50.0) / 100.0, 0.0, 1.0)
        lot_size = int(_safe_float(chain_data.get("lot_size"), self._lot_size_for_symbol(symbol)))
        delta_score = _clamp(1.0 - (abs(greeks.delta) / max(lot_size * 6, 1)), 0.0, 1.0)

        max_loss = abs(_safe_float(metrics.get("max_loss"), 0.0))
        draw_ratio = 0.0 if max_loss <= 1e-6 else max(0.0, -_safe_float(stress.get("worst_pnl"), 0.0)) / max_loss
        stress_score = _clamp(1.0 - draw_ratio, 0.0, 1.0)

        confidence = round(
            (0.35 * pop_score) + (0.30 * stress_score) + (0.20 * delta_score) + (0.15 * liq_score),
            3,
        )
        grade = "A" if confidence >= 0.8 else "B" if confidence >= 0.65 else "C" if confidence >= 0.5 else "D"

        return {
            "confidence": confidence,
            "grade": grade,
            "components": {
                "pop_score": round(pop_score, 3),
                "stress_score": round(stress_score, 3),
                "delta_balance_score": round(delta_score, 3),
                "liquidity_score": round(liq_score, 3),
            },
            "stress": stress,
            "metrics": metrics,
            "enhanced": enhanced,
            "greeks": greeks.model_dump(),
        }

    def _run_stress_suite(self, spot: float, legs: list[ConcreteLeg], underlying: str) -> dict[str, Any]:
        scenarios = [
            ("spot_-2_iv_+2", -2.0, +2.0, 0),
            ("spot_+2_iv_+2", +2.0, +2.0, 0),
            ("spot_-4_iv_+5_day+1", -4.0, +5.0, 1),
            ("spot_+4_iv_+5_day+1", +4.0, +5.0, 1),
            ("spot_0_iv_-3_day+2", 0.0, -3.0, 2),
        ]
        rows: list[dict[str, Any]] = []
        for name, ds, di, dd in scenarios:
            out = scenario_analysis(
                spot_price=spot,
                legs=legs,
                delta_spot_pct=ds,
                delta_iv_points=di,
                delta_days=dd,
                underlying=underlying,
            )
            rows.append({
                "scenario": name,
                "pnl_at_scenario": _safe_float(out.get("pnl_at_scenario"), 0.0),
            })

        pnls = [r["pnl_at_scenario"] for r in rows] or [0.0]
        return {
            "scenarios": rows,
            "worst_pnl": round(min(pnls), 2),
            "best_pnl": round(max(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
        }

    def _liquidity_score(self, legs: list[ConcreteLeg], chain_data: dict) -> float:
        chain = chain_data.get("chain", []) or []
        row_map = {int(round(_safe_float(r.get("strike"), 0.0))): r for r in chain}
        scores = []
        for leg in legs:
            if leg.right == OptionRight.FUT:
                scores.append(1.0)
                continue
            row = row_map.get(int(round(_safe_float(leg.strike))), {})
            opt = row.get(leg.right.value, {}) if row else {}
            oi = _safe_float(opt.get("oi"), 0.0)
            vol = _safe_float(opt.get("volume"), 0.0)
            oi_score = _clamp(oi / 100_000.0, 0.0, 1.0)
            vol_score = _clamp(vol / 3_000.0, 0.0, 1.0)
            scores.append((oi_score * 0.6) + (vol_score * 0.4))
        return float(sum(scores) / len(scores)) if scores else 0.0

    # -------------------------------------------------------------------------
    # Capability #2 Portfolio optimizer
    # -------------------------------------------------------------------------
    def optimize_portfolio(
        self,
        underlying: str,
        target_delta: float | None = None,
        target_vega: float | None = None,
        chain_data: dict | None = None,
    ) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
        spot = _safe_float(chain_data.get("spot"), 0.0)
        active = [s for s in self.paper_engine.strategies if s.status == "active"]
        active_legs = [l for s in active for l in s.legs]
        if not active_legs or spot <= 0:
            return {
                "symbol": symbol,
                "rebalancing_required": False,
                "reason": "No active portfolio legs",
                "current_greeks": {"delta": 0.0, "vega": 0.0, "theta": 0.0, "gamma": 0.0},
                "rebalancing_legs": [],
            }

        target_delta = _safe_float(target_delta, _safe_float(self.profile.get("target_delta"), 0.0))
        target_vega = _safe_float(target_vega, _safe_float(self.profile.get("target_vega"), 0.0))
        lot_size = int(_safe_float(chain_data.get("lot_size"), self._lot_size_for_symbol(symbol)))
        expiry = str(chain_data.get("expiry", "") or "")

        current = compute_strategy_greeks(spot=spot, legs=active_legs, underlying=symbol)
        delta_gap = current.delta - target_delta
        vega_gap = current.vega - target_vega

        hedge_legs: list[ConcreteLeg] = []
        reasons: list[str] = []

        # Delta hedge with futures for low-friction balancing.
        if abs(delta_gap) > lot_size * 0.75:
            qty = int(math.ceil(abs(delta_gap) / max(lot_size, 1)) * max(lot_size, 1))
            hedge_side = Side.SELL if delta_gap > 0 else Side.BUY
            hedge_legs.append(ConcreteLeg(
                side=hedge_side,
                right=OptionRight.FUT,
                strike=float(spot),
                premium=float(spot),
                qty=qty,
                expiry=expiry,
                iv=0.0,
            ))
            reasons.append(f"Delta gap {delta_gap:.2f} beyond threshold; future hedge qty {qty}")

        # Vega hedge with ATM straddle unit when imbalance is high.
        if abs(vega_gap) > 50:
            chain = chain_data.get("chain", []) or []
            if chain:
                strikes = sorted({_safe_float(r.get("strike"), 0.0) for r in chain if _safe_float(r.get("strike"), 0.0) > 0})
                atm = min(strikes, key=lambda s: abs(s - spot))
                row_map = {int(round(_safe_float(r.get("strike"), 0.0))): r for r in chain}
                row = row_map.get(int(round(atm)), {})
                ce = row.get("CE", {}) or {}
                pe = row.get("PE", {}) or {}
                side = Side.SELL if vega_gap > 0 else Side.BUY
                for right, point in ((OptionRight.CE, ce), (OptionRight.PE, pe)):
                    hedge_legs.append(ConcreteLeg(
                        side=side,
                        right=right,
                        strike=float(atm),
                        premium=_safe_float(point.get("premium"), _safe_float(point.get("ltp"), 0.0)),
                        qty=lot_size,
                        expiry=expiry,
                        iv=(_safe_float(point.get("iv"), 18.0) / 100.0),
                        delta=point.get("delta"),
                        gamma=point.get("gamma"),
                        vega=point.get("vega"),
                        theta=point.get("theta"),
                    ))
                reasons.append(f"Vega gap {vega_gap:.2f} beyond threshold; added ATM straddle hedge")

        projected = compute_strategy_greeks(
            spot=spot,
            legs=active_legs + hedge_legs,
            underlying=symbol,
        )

        execution = self.build_execution_plan(symbol, hedge_legs, chain_data=chain_data) if hedge_legs else {
            "execution_ready": True,
            "order_slices": [],
            "liquidity_checks": [],
            "warnings": [],
        }

        payload = {
            "symbol": symbol,
            "spot": round(spot, 2),
            "rebalancing_required": bool(hedge_legs),
            "reasons": reasons,
            "target": {"delta": target_delta, "vega": target_vega},
            "current_greeks": current.model_dump(),
            "projected_greeks": projected.model_dump(),
            "rebalancing_legs": [l.model_dump() for l in hedge_legs],
            "execution_plan": execution,
        }
        self.db.append_journal("portfolio_optimizer", payload, symbol=symbol)
        return payload

    # -------------------------------------------------------------------------
    # Capability #4 Auto-adjustment engine
    # -------------------------------------------------------------------------
    def generate_adjustments(self, underlying: str, chain_data: dict | None = None) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
        spot = _safe_float(chain_data.get("spot"), 0.0)
        lot_size = int(_safe_float(chain_data.get("lot_size"), self._lot_size_for_symbol(symbol)))
        loss_trigger = abs(_safe_float(self.profile.get("capital_limit"), 1_000_000)) * _clamp(
            _safe_float(self.profile.get("repair_loss_trigger_pct"), 0.02),
            0.001,
            0.2,
        )

        actions: list[dict[str, Any]] = []
        for strat in self.paper_engine.strategies:
            if strat.status != "active":
                continue
            if _normalize_underlying(strat.underlying) != symbol:
                continue
            greeks = compute_strategy_greeks(spot=spot, legs=strat.legs, underlying=strat.underlying)
            dte = self._infer_dte_from_legs(strat.legs, fallback=7)

            # Trigger 1: Portfolio-preserving hedge under stress.
            if strat.unrealized_pnl <= -loss_trigger and abs(greeks.delta) > lot_size * 0.75:
                hedge_qty = int(math.ceil(abs(greeks.delta) / max(lot_size, 1)) * max(lot_size, 1))
                hedge_side = Side.SELL if greeks.delta > 0 else Side.BUY
                leg = ConcreteLeg(
                    side=hedge_side,
                    right=OptionRight.FUT,
                    strike=float(spot),
                    premium=float(spot),
                    qty=hedge_qty,
                    expiry=str(chain_data.get("expiry", "") or ""),
                    iv=0.0,
                )
                actions.append({
                    "strategy_id": strat.id,
                    "strategy_name": strat.template_name,
                    "action_type": "add_delta_hedge",
                    "reason": (
                        f"Unrealized P&L {strat.unrealized_pnl:.2f} breached loss trigger {-loss_trigger:.2f}; "
                        f"delta={greeks.delta:.2f} requires hedge."
                    ),
                    "legs": [leg.model_dump()],
                })
                continue

            # Trigger 2: Pin-risk flatten close to expiry.
            if dte <= 0 and abs(greeks.gamma) > 10:
                actions.append({
                    "strategy_id": strat.id,
                    "strategy_name": strat.template_name,
                    "action_type": "close_strategy",
                    "reason": f"Expiry-day pin risk detected (gamma={greeks.gamma:.2f}).",
                    "legs": [],
                })
                continue

            # Trigger 3: Deep stress with no clear hedge -> reduce risk by close.
            if strat.unrealized_pnl <= -loss_trigger and abs(greeks.delta) <= lot_size * 0.75:
                actions.append({
                    "strategy_id": strat.id,
                    "strategy_name": strat.template_name,
                    "action_type": "close_strategy",
                    "reason": f"Loss trigger breached (PnL={strat.unrealized_pnl:.2f}); close to preserve capital.",
                    "legs": [],
                })

        payload = {
            "symbol": symbol,
            "loss_trigger_abs": round(loss_trigger, 2),
            "actions": actions,
        }
        self.db.append_journal("adjustment_scan", payload, symbol=symbol)
        return payload

    # -------------------------------------------------------------------------
    # Capability #1 Semi-autonomous engine (approve once, then manage)
    # -------------------------------------------------------------------------
    def run_autopilot_cycle(
        self,
        underlying: str = "NSE:NIFTY50-INDEX",
        *,
        force: bool = False,
        chain_data: dict | None = None,
    ) -> dict[str, Any]:
        symbol = _normalize_underlying(underlying)
        with self._lock:
            state = dict(self.autopilot_state)
            if not state.get("enabled"):
                return {
                    "status": "disabled",
                    "symbol": symbol,
                    "state": state,
                }

            interval = int(max(10, _safe_float(state.get("rebalance_interval_sec"), 30)))
            last_run = state.get("last_run_at")
            if not force and last_run:
                try:
                    elapsed = (datetime.now() - datetime.fromisoformat(str(last_run))).total_seconds()
                    if elapsed < interval:
                        return {
                            "status": "cooldown",
                            "symbol": symbol,
                            "next_run_in_sec": int(interval - elapsed),
                            "state": state,
                        }
                except Exception:
                    pass

            chain_data = chain_data or self.fyers_client.get_option_chain(symbol)
            spot = _safe_float(chain_data.get("spot"), 0.0)
            if spot > 0:
                self.paper_engine.update_mtm(
                    spot,
                    chain=chain_data.get("chain", []),
                    underlying=symbol,
                    chain_expiry=chain_data.get("expiry", ""),
                )

            optimizer = self.optimize_portfolio(
                symbol,
                target_delta=_safe_float(self.profile.get("target_delta"), 0.0),
                target_vega=_safe_float(self.profile.get("target_vega"), 0.0),
                chain_data=chain_data,
            )
            adjustments = self.generate_adjustments(symbol, chain_data=chain_data)

            queued_actions: list[_Action] = []
            if optimizer.get("rebalancing_required") and optimizer.get("rebalancing_legs"):
                queued_actions.append(_Action(
                    action_type="rebalance_portfolio",
                    reason="Greek optimizer requested hedge rebalance.",
                    payload={"legs": optimizer["rebalancing_legs"]},
                ))
            for action in adjustments.get("actions", []):
                queued_actions.append(_Action(
                    action_type=action.get("action_type", "unknown"),
                    reason=str(action.get("reason", "")),
                    payload=action,
                ))

            mode = "live" if str(state.get("mode", "paper")).lower() == "live" else "paper"
            allow_live = bool(state.get("allow_live_execution", False))
            market = market_status()
            market_open = bool(market.get("is_open"))
            if market_open:
                execution_report = self._execute_actions(
                    symbol=symbol,
                    spot=spot,
                    mode=mode,
                    allow_live_execution=allow_live,
                    chain_data=chain_data,
                    actions=queued_actions,
                )
            else:
                execution_report = {
                    "executed_count": 0,
                    "skipped_count": len(queued_actions),
                    "executed": [],
                    "skipped": [
                        {
                            "action": action.action_type,
                            "reason": f"Market {market.get('status', 'CLOSED')} - execution blocked",
                        }
                        for action in queued_actions
                    ],
                    "market_gate": {
                        "is_open": False,
                        "status": market.get("status", "CLOSED"),
                        "message": market.get("message", ""),
                    },
                }

            result = {
                "status": "ran",
                "symbol": symbol,
                "mode": mode,
                "market": market,
                "actions_queued": len(queued_actions),
                "optimizer": optimizer,
                "adjustments": adjustments,
                "execution_report": execution_report,
                "ran_at": _now_iso(),
            }
            self.autopilot_state["last_run_at"] = result["ran_at"]
            self.autopilot_state["last_result"] = {
                "status": result["status"],
                "actions_queued": result["actions_queued"],
                "executed": execution_report.get("executed_count", 0),
                "skipped": execution_report.get("skipped_count", 0),
                "mode": mode,
                "symbol": symbol,
            }
            self.db.save_autopilot_state(self.autopilot_state)
            self.db.append_journal("autopilot_cycle", result, symbol=symbol)
            return result

    def _execute_actions(
        self,
        *,
        symbol: str,
        spot: float,
        mode: str,
        allow_live_execution: bool,
        chain_data: dict,
        actions: list[_Action],
    ) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for action in actions:
            if action.action_type == "close_strategy":
                strategy_id = str(action.payload.get("strategy_id", ""))
                if not strategy_id:
                    skipped.append({"action": action.action_type, "reason": "missing strategy_id"})
                    continue

                if mode != "paper":
                    skipped.append({
                        "action": action.action_type,
                        "strategy_id": strategy_id,
                        "reason": "close strategy auto-live not enabled in v1",
                    })
                    continue

                result = self.paper_engine.close_strategy(strategy_id, float(spot))
                executed.append({
                    "action": action.action_type,
                    "strategy_id": strategy_id,
                    "result": result,
                })
                self.db.append_journal(
                    "autopilot_action",
                    {
                        "action": action.action_type,
                        "strategy_id": strategy_id,
                        "result": result,
                        "reason": action.reason,
                    },
                    symbol=symbol,
                )
                continue

            legs_data = action.payload.get("legs") or action.payload.get("payload", {}).get("legs") or []
            legs = [ConcreteLeg(**l) for l in legs_data] if legs_data else []
            if not legs:
                skipped.append({"action": action.action_type, "reason": "no legs to execute"})
                continue

            if mode == "paper" and action.action_type == "rebalance_portfolio":
                max_active = int(_clamp(
                    _safe_float(self.autopilot_state.get("max_active_rebalance_per_symbol"), 1.0),
                    1.0,
                    10.0,
                ))
                active_rebalances = self._active_autopilot_strategies(
                    symbol=symbol,
                    action_type=action.action_type,
                )
                if len(active_rebalances) >= max_active:
                    reason = (
                        "active AUTOPILOT-rebalance_portfolio already open for symbol; "
                        "close/adjust existing hedge before opening another"
                    )
                    skipped.append({
                        "action": action.action_type,
                        "reason": reason,
                        "active_count": len(active_rebalances),
                        "limit": max_active,
                    })
                    self.db.append_journal(
                        "autopilot_action",
                        {
                            "action": action.action_type,
                            "mode": "paper",
                            "status": "skipped",
                            "reason": reason,
                            "active_count": len(active_rebalances),
                            "limit": max_active,
                        },
                        symbol=symbol,
                    )
                    continue

            if mode == "paper":
                opened = self._open_paper_custom(
                    symbol=symbol,
                    spot=spot,
                    legs=legs,
                    strategy_name=f"AUTOPILOT-{action.action_type}",
                )
                executed.append({
                    "action": action.action_type,
                    "result": opened,
                    "mode": "paper",
                })
                self.db.append_journal(
                    "autopilot_action",
                    {
                        "action": action.action_type,
                        "mode": "paper",
                        "reason": action.reason,
                        "result": opened,
                    },
                    symbol=symbol,
                )
                continue

            if mode == "live" and allow_live_execution and self.fyers_client.is_authenticated:
                execution = self.build_execution_plan(symbol, legs, chain_data=chain_data)
                if not execution.get("execution_ready"):
                    skipped.append({
                        "action": action.action_type,
                        "reason": "execution guard blocked live order",
                        "warnings": execution.get("warnings", []),
                    })
                    continue
                broker_legs = [
                    {
                        "symbol": slice_order.get("symbol", ""),
                        "side": slice_order["side"],
                        "right": slice_order["right"],
                        "strike": slice_order["strike"],
                        "qty": slice_order["qty"],
                        "premium": slice_order["limit_price"],
                    }
                    for slice_order in execution.get("order_slices", [])
                ]
                result = self.fyers_client.deploy_strategy(broker_legs, symbol)
                executed.append({
                    "action": action.action_type,
                    "mode": "live",
                    "result": result,
                })
                self.db.append_journal(
                    "autopilot_action",
                    {
                        "action": action.action_type,
                        "mode": "live",
                        "reason": action.reason,
                        "result": result,
                    },
                    symbol=symbol,
                )
            else:
                skipped.append({
                    "action": action.action_type,
                    "reason": "live execution not allowed or broker not connected",
                })

        return {
            "executed_count": len(executed),
            "skipped_count": len(skipped),
            "executed": executed,
            "skipped": skipped,
        }

    def _active_autopilot_strategies(self, *, symbol: str, action_type: str) -> list[Any]:
        normalized = _normalize_underlying(symbol)
        strategy_name = f"AUTOPILOT-{action_type}"
        active: list[Any] = []
        for strat in self.paper_engine.strategies:
            if getattr(strat, "status", "") != "active":
                continue
            if str(getattr(strat, "template_name", "")) != strategy_name:
                continue
            if _normalize_underlying(str(getattr(strat, "underlying", ""))) != normalized:
                continue
            active.append(strat)
        return active

    def _open_paper_custom(
        self,
        *,
        symbol: str,
        spot: float,
        legs: list[ConcreteLeg],
        strategy_name: str,
    ) -> dict[str, Any]:
        template = StrategyTemplate(
            id=0,
            name=strategy_name,
            category=StrategyCategory.NEUTRAL,
            subcategory="Autopilot",
            legs=[],
            description="Autopilot generated strategy",
            primary_view="Autonomous risk-managed action",
            payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
            max_risk="Dynamic",
            max_reward="Dynamic",
            breakeven_formula="Dynamic",
            tags=["autopilot"],
        )
        instance = self.paper_engine.open_strategy(
            template=template,
            legs=legs,
            underlying=symbol,
            spot_price=float(spot),
            tags=["autopilot"],
        )
        return {
            "status": "opened",
            "instance_id": instance.id,
            "strategy_name": instance.template_name,
            "legs": [l.model_dump() for l in legs],
        }

    # -------------------------------------------------------------------------
    # Capability #8 Journal + learning loop
    # -------------------------------------------------------------------------
    def get_journal(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.get_journal(limit=limit)

    def learning_summary(self, limit: int = 200) -> dict[str, Any]:
        rows = self.get_journal(limit=limit)
        by_type: dict[str, int] = {}
        close_events = 0
        wins = 0
        losses = 0
        total_realized = 0.0

        for row in rows:
            event_type = str(row.get("event_type", "unknown"))
            by_type[event_type] = by_type.get(event_type, 0) + 1
            payload = row.get("payload", {}) or {}
            if event_type == "autopilot_action" and str(payload.get("action")) == "close_strategy":
                close_events += 1
                realized = _safe_float((payload.get("result") or {}).get("realized_pnl"), 0.0)
                total_realized += realized
                if realized > 0:
                    wins += 1
                elif realized < 0:
                    losses += 1

        win_rate = (wins / close_events * 100.0) if close_events else 0.0
        return {
            "sample_size": len(rows),
            "event_counts": by_type,
            "close_events": close_events,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 2),
            "realized_pnl_sum": round(total_realized, 2),
            "notes": [
                "Learning loop uses journaled autopilot close actions.",
                "Expand with slippage attribution and regime-conditioned performance in next version.",
            ],
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _lot_size_for_symbol(self, symbol: str) -> int:
        s = _normalize_underlying(symbol)
        if s in SUPPORTED_ASSETS:
            return int(SUPPORTED_ASSETS[s]["lot_size"])
        if "BANK" in s.upper():
            return 30
        if "NIFTY" in s.upper():
            return 65
        return 1

    def _infer_dte_from_legs(self, legs: list[ConcreteLeg], fallback: int = 7) -> int:
        if not legs:
            return fallback
        dtes = []
        today = datetime.now().date()
        for leg in legs:
            exp = _parse_date(leg.expiry)
            if not exp:
                continue
            dtes.append(max((exp - today).days, 0))
        if not dtes:
            return fallback
        return int(round(sum(dtes) / len(dtes)))
