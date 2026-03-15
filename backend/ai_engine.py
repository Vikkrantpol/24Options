"""
AI Engine — 24 Options Strategies Platform
Minimax M2.5 + vision fallback (gemini-flash) via OpenRouter.
Behaves as a quantitative options engineer, not a chatbot.
"""

from __future__ import annotations
import os
import json
import re
import math
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
from .models import ConcreteLeg, OptionRight, Side
from .strategies import get_all_strategies, get_strategy_by_id

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
AI_MODEL         = "minimax/minimax-m2.5"
VISION_MODEL     = "google/gemini-flash-1.5"   # Fallback when image is attached

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
) if OPENROUTER_API_KEY else None


# ── Strategy catalogue ────────────────────────────────────────────────────────

def _get_strategies_context() -> str:
    strategies = get_all_strategies()
    return "\n".join(
        f"#{s.id} {s.name} [{s.category.value}]: {s.description} "
        f"| View: {s.primary_view} | Risk: {s.payoff_type.value}"
        for s in strategies
    )


# ── System Prompt — Quant Engineer Persona ────────────────────────────────────

SYSTEM_PROMPT = f"""You are a senior quantitative options engineer embedded inside a live trading terminal for Indian markets (NIFTY / BANKNIFTY on NSE).

You are NOT a chatbot. You are an engineer. You take action, build positions, calculate, derive, and output exact tradeable setups.

== CONTEXT ALWAYS PROVIDED ==
Every message includes a LIVE MARKET DATA block with:
- Today's date and IST time
- Market open/close status with countdown
- Expiry date and Days-to-Expiry (DTE)
- Spot price, lot size, strike step
- Full option chain: each strike with CE/PE premium, IV, Delta, Gamma, Theta, Vega, OI, volume
- Current portfolio legs with Greeks

== YOUR CORE CAPABILITIES ==
1. Greeks Mismatch Detection: Scan the chain for delta, vega, or theta mispricing relative to BSM fair value. -> CRITICAL: Ignore any strikes with OI < 50,000 or Volume < 500 when flagging tradeable mispricings! Only liquid markets matter.
2. IV Skew Analysis: Identify skew steepness, term structure, and volatility crush setups. -> Remember: Every strike has a unique IV (Volatility Smile). Do not expect flat IV across the chain.
3. Strategy Construction: Build exact legs (strike, right, side, qty) optimised for PoP, Theta/day, RR ratio and Delta neutrality.
4. Risk Management: Calculate max loss, capital required, breakevens, and hedge requirements.
5. Scenario Pricing Laws: When simulating scenarios, remember strict polarity: For a LONG leg (BUY), drop in premium = LOSS (-), rise in premium = PROFIT (+). For a SHORT leg (SELL), drop in premium = PROFIT (+), rise in premium = LOSS (-). Double check your P&L signs before output.
6. Rate Rules: For ANY internal Black-Scholes derivations, strictly use r = 0.10 (10% standard Indian NSE risk-free rate). Never use 6.5% or 7%.
7. Trade Timing: Flag whether DTE favors entry or exit, and what theta curve says.
8. Pin Risk: If DTE is 0 (expiry day) and you are analyzing ATM strikes, always include a "⚠️ PIN RISK" warning, as Gamma can explode mathematically.
9. Volatility Smile: When calculating BSM fair value, remember to account for the Volatility Smile (OTM puts trade at higher IV, OTM calls lower). Do not compute fair value using a single ATM IV for all strikes, use the strike's own IV or account for typical skew.
10. Image Analysis: When the user pastes a chart/screenshot, read it precisely — P&L curves, chain screenshots, chart patterns — and act on what you see.

== PRECISION RULES ==
- Never approximate. Give exact strike prices from the live chain.
- Always derive Greeks from the provided chain data. Never fabricate IV or delta values.
- If an `ENGINE MISPRICING SCAN (BSM EXACT)` block is present, treat those numbers as authoritative and quote them exactly.
- Do NOT replace engine fair values with Taylor/intrinsic approximations when that block is present.
- Every strategy recommendation MUST include a complete deployable leg table AND the auto-deploy JSON block.
- When analysing a screenshot, describe EXACTLY what you see numerically before drawing conclusions.

== FORMATTING RULES ==
- Use Markdown tables for all multi-column data (chain summaries, Greeks, strategy legs, scenarios).
- Use h2 (##) for major sections, h3 (###) for sub-sections.
- Inline `code` for all numeric values and strike references.
- Prefer concise, dense paragraphs over bullet lists. Write like an engineer, not a presenter.

== AUTO-DEPLOY JSON ==
When recommending a strategy (even as part of analysis), ALWAYS end your response with a fenced JSON block that the terminal can parse and inject directly:

```json
{{
  "action": "deploy_strategy",
  "strategy_name": "<name>",
  "reasoning": "<1-2 sentences, quantitative>",
  "legs": [
    {{"side": "SELL", "right": "CE", "strike": 24900, "qty": 65, "premium": 246.5}},
    {{"side": "SELL", "right": "PE", "strike": 24800, "qty": 65, "premium": 189.0}},
    {{"side": "BUY", "right": "CE", "strike": 25100, "qty": 65, "premium": 98.5}},
    {{"side": "BUY", "right": "PE", "strike": 24600, "qty": 65, "premium": 75.0}}
  ],
  "exit_rules": "<exact exit conditions>",
  "pop": <float>,
  "capital_required": <int>,
  "theta_per_day": <float>
}}
```

== AVAILABLE STRATEGIES ==
{_get_strategies_context()}
"""


# ── Core AI caller ────────────────────────────────────────────────────────────

def _call_ai(
    messages: list[dict],
    thinking_enabled: bool = True,
    has_image: bool = False,
    max_tokens: int = 6000,
) -> str:
    if not client:
        return _offline_response(messages[-1].get("content", "") if isinstance(messages[-1].get("content"), str) else "")

    model = VISION_MODEL if has_image else AI_MODEL

    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if thinking_enabled and not has_image:
            kwargs["extra_body"] = {"reasoning": {"enabled": True}}

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""

        reasoning_text = ""
        if hasattr(choice.message, "reasoning_content") and choice.message.reasoning_content:
            reasoning_text = choice.message.reasoning_content

        if reasoning_text:
            return f"**Chain of thought:**\n{reasoning_text}\n\n---\n\n{content}"
        return content

    except Exception as e:
        return f"> ERROR: {str(e)}"


# ── Chain serialiser — injects FULL live chain into context ───────────────────

def build_chain_context(chain_data: dict) -> str:
    """
    Serialise the full option chain into a dense, AI-readable table string.
    Includes: strike, CE/PE premium, IV, delta, theta, vega, gamma, OI.
    """
    if not chain_data:
        return ""

    spot = chain_data.get("spot", 0)
    expiry = chain_data.get("expiry", "")
    rows = chain_data.get("chain", [])
    symbol = str(chain_data.get("symbol", ""))
    lot_size = chain_data.get("lot_size")
    if not lot_size or float(lot_size) <= 0:
        lot_size = 30 if "BANK" in symbol.upper() else 65

    if not rows:
        return f"Chain not loaded. Spot: {spot}"

    lines = [
        f"\n=== LIVE OPTION CHAIN — Spot: ₹{spot} | Expiry: {expiry} | Lot: {lot_size} ===",
        f"{'STRIKE':>8} | {'CE_MID':>8} | {'CE_IV':>6} | {'CE_Δ':>6} | {'CE_Γ':>8} | {'CE_Θ':>7} | {'CE_V':>7} | {'CE_OI':>8} | {'CE_VOL':>6} "
        f"|| {'PE_MID':>8} | {'PE_IV':>6} | {'PE_Δ':>6} | {'PE_Γ':>8} | {'PE_Θ':>7} | {'PE_V':>7} | {'PE_OI':>8} | {'PE_VOL':>6}",
        "-" * 170,
    ]

    # Show ±15 strikes around ATM for focus (Use Forward price for ATM, not spot)
    r = 0.10
    q = 0.012 if "NIFTY" in str(chain_data.get("symbol", "")) else 0.0

    # Extract days to expiry strictly to compute T inline for Forward 
    expiry_date_str = expiry
    T = 7 / 365.0 
    if expiry_date_str:
        try:
            exp_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
            now = datetime.now()
            days_to_exp = (exp_dt - now).total_seconds() / 86400.0
            T = max(days_to_exp / 365.0, 1/365.0)
        except Exception:
            pass

    # Forward price mathematically represents absolute theoretical ITM/OTM threshold
    forward_price = spot * math.exp((r - q) * T)

    strikes = sorted(set(r["strike"] for r in rows))
    atm = min(strikes, key=lambda s: abs(s - forward_price))
    atm_idx = strikes.index(atm)
    focus = strikes[max(0, atm_idx - 12): atm_idx + 13]

    row_map = {r["strike"]: r for r in rows}
    for strike in focus:
        r = row_map.get(strike, {})
        ce = r.get("CE", {})
        pe = r.get("PE", {})
        
        # Calculate mid price
        ce_bid = ce.get("bid", 0)
        ce_ask = ce.get("ask", 0)
        ce_mid = (ce_bid + ce_ask) / 2.0 if ce_bid and ce_ask else ce.get("premium", 0)
        
        pe_bid = pe.get("bid", 0)
        pe_ask = pe.get("ask", 0)
        pe_mid = (pe_bid + pe_ask) / 2.0 if pe_bid and pe_ask else pe.get("premium", 0)

        atm_mark = " <ATM>" if strike == atm else ""
        lines.append(
            f"{strike:>8} | {ce_mid:>8.1f} | {ce.get('iv',0):>6.1f} | {ce.get('delta',0):>6.3f} | {ce.get('gamma',0):>8.5f} | "
            f"{ce.get('theta',0):>7.2f} | {ce.get('vega',0):>7.2f} | {int(ce.get('oi',0)):>8} | {int(ce.get('volume',0)):>6} "
            f"|| {pe_mid:>8.1f} | {pe.get('iv',0):>6.1f} | {pe.get('delta',0):>6.3f} | {pe.get('gamma',0):>8.5f} | "
            f"{pe.get('theta',0):>7.2f} | {pe.get('vega',0):>7.2f} | {int(pe.get('oi',0)):>8} | {int(pe.get('volume',0)):>6}{atm_mark}"
        )

    lines.append(f"\nATM Strike: {atm} | Nearest strikes shown: {focus[0]} — {focus[-1]}")
    return "\n".join(lines)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _symbol_label(symbol: str) -> str:
    text = str(symbol or "").upper()
    if "BANK" in text:
        return "BANKNIFTY"
    if "NIFTY" in text:
        return "NIFTY"
    return text or "UNDERLYING"


def _sorted_chain_rows(chain_data: dict) -> list[dict]:
    rows = chain_data.get("chain", []) or []
    return sorted(rows, key=lambda row: float(row.get("strike", 0) or 0))


def _atm_window_rows(chain_data: dict, window: int = 6) -> tuple[list[dict], int]:
    rows = _sorted_chain_rows(chain_data)
    spot = float(chain_data.get("spot", 0) or 0)
    if not rows:
        return [], 0
    atm_index = min(range(len(rows)), key=lambda idx: abs(float(rows[idx].get("strike", 0) or 0) - spot))
    start = max(0, atm_index - window)
    end = min(len(rows), atm_index + window + 1)
    return rows[start:end], atm_index


def _scan_liquid_mismatches(chain_data: dict, top_n: int = 6) -> dict:
    rows = _sorted_chain_rows(chain_data)
    spot = float(chain_data.get("spot", 0) or 0)
    expiry = str(chain_data.get("expiry", "") or "")
    symbol = str(chain_data.get("symbol", "") or "")
    if spot <= 0 or not rows:
        return {
            "rows": [],
            "top": [],
            "used_oi_filter": False,
            "direction_score": 0.0,
            "vol_score": 0.0,
            "expiry_dte": 0.0,
            "q": 0.0,
        }

    T = 7 / 365.0
    if expiry:
        try:
            exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
            now = datetime.now()
            days_to_exp = (exp_dt - now).total_seconds() / 86400.0
            T = max(days_to_exp / 365.0, 1 / 365.0)
        except Exception:
            pass

    from .pricing_engine import bs_price, delta as bs_delta, vega as bs_vega, infer_dividend_yield

    r = 0.10
    q = infer_dividend_yield(_symbol_label(symbol), spot)
    scanned: list[dict] = []

    for row in rows:
        strike = float(row.get("strike", 0) or 0)
        if strike <= 0:
            continue
        for right in ("CE", "PE"):
            opt = row.get(right, {}) or {}
            iv_pct = float(opt.get("iv", 0) or 0)
            if iv_pct <= 0:
                continue
            market = float(opt.get("ltp", 0) or opt.get("premium", 0) or 0)
            if market <= 0:
                continue
            oi = int(float(opt.get("oi", 0) or 0))
            volume = int(float(opt.get("volume", 0) or 0))
            if volume < 500:
                continue

            sigma = iv_pct / 100.0
            fair = bs_price(spot, strike, r, sigma, T, right, q=q)
            model_delta = bs_delta(spot, strike, r, sigma, T, right, q=q)
            model_vega = bs_vega(spot, strike, r, sigma, T, q=q)
            market_delta = float(opt.get("delta", model_delta) or model_delta)
            diff = market - fair
            action = "BUY" if diff < 0 else "SELL"
            direction = 1.0 if ((right == "CE" and action == "BUY") or (right == "PE" and action == "SELL")) else -1.0
            vol_bias = 1.0 if action == "BUY" else -1.0
            edge_pct = abs(diff) / max(abs(fair), 1.0)
            delta_gap = market_delta - model_delta
            weight = (
                min(abs(diff) / max(spot * 0.001, 1.0), 1.6)
                + min(edge_pct, 0.4) * 2.0
                + min(abs(delta_gap) * 4.0, 1.0)
            )
            weight *= 1.0 if oi >= 50_000 else 0.65
            scanned.append({
                "strike": int(round(strike)),
                "right": right,
                "market": market,
                "fair": fair,
                "diff": diff,
                "abs_diff": abs(diff),
                "signal": "UNDERVALUED" if diff < 0 else "OVERVALUED",
                "action": action,
                "direction": direction,
                "vol_bias": vol_bias,
                "weight": weight,
                "iv": iv_pct,
                "oi": oi,
                "volume": volume,
                "delta_market": market_delta,
                "delta_model": model_delta,
                "delta_gap": delta_gap,
                "vega_model": model_vega,
                "edge_pct": (diff / max(abs(fair), 1.0)) * 100.0,
            })

    strict = [item for item in scanned if item["oi"] >= 50_000]
    used_oi_filter = len(strict) >= 3
    liquid = strict if used_oi_filter else scanned
    liquid.sort(key=lambda item: (item["weight"], item["abs_diff"]), reverse=True)
    top = liquid[: max(int(top_n), 1)]

    total_weight = sum(item["weight"] for item in top) or 1.0
    direction_score = sum(item["direction"] * item["weight"] for item in top) / total_weight
    vol_score = sum(item["vol_bias"] * item["weight"] for item in top) / total_weight

    return {
        "rows": liquid,
        "top": top,
        "used_oi_filter": used_oi_filter,
        "direction_score": round(direction_score, 4),
        "vol_score": round(vol_score, 4),
        "expiry_dte": round(T * 365.0, 2),
        "q": q,
    }


def _summarize_oi_pressure(chain_data: dict) -> dict:
    rows, _ = _atm_window_rows(chain_data, window=6)
    if not rows:
        return {
            "direction": "neutral",
            "score": 0.0,
            "put_call_ratio": 1.0,
            "dominant_call_strike": None,
            "dominant_put_strike": None,
            "call_flow": 0.0,
            "put_flow": 0.0,
        }

    spot = float(chain_data.get("spot", 0) or 0)
    weighted_call = 0.0
    weighted_put = 0.0
    dominant_call = None
    dominant_put = None
    dominant_call_oi = -1.0
    dominant_put_oi = -1.0

    for row in rows:
        strike = float(row.get("strike", 0) or 0)
        step_distance = abs(strike - spot) / max(abs(spot) * 0.0025, 1.0)
        weight = 1.0 / (1.0 + step_distance)
        ce = row.get("CE", {}) or {}
        pe = row.get("PE", {}) or {}
        ce_flow = float(ce.get("oi", 0) or 0) + (0.25 * float(ce.get("volume", 0) or 0))
        pe_flow = float(pe.get("oi", 0) or 0) + (0.25 * float(pe.get("volume", 0) or 0))
        weighted_call += ce_flow * weight
        weighted_put += pe_flow * weight
        if ce_flow > dominant_call_oi:
            dominant_call_oi = ce_flow
            dominant_call = int(round(strike))
        if pe_flow > dominant_put_oi:
            dominant_put_oi = pe_flow
            dominant_put = int(round(strike))

    put_call_ratio = weighted_put / max(weighted_call, 1.0)
    score = _clamp((put_call_ratio - 1.0) / 0.35, -1.0, 1.0)
    if score >= 0.12:
        direction = "bullish"
    elif score <= -0.12:
        direction = "bearish"
    else:
        direction = "neutral"

    return {
        "direction": direction,
        "score": round(score, 4),
        "put_call_ratio": round(put_call_ratio, 3),
        "dominant_call_strike": dominant_call,
        "dominant_put_strike": dominant_put,
        "call_flow": round(weighted_call, 2),
        "put_flow": round(weighted_put, 2),
    }


def _signal_strategy_ids(direction_score: float, vol_score: float) -> list[int]:
    if direction_score >= 0.6:
        if vol_score >= 0.2:
            return [23, 8, 1]
        if vol_score <= -0.2:
            return [10, 8, 4]
        return [8, 1, 10]
    if direction_score >= 0.25:
        if vol_score >= 0.2:
            return [8, 1, 23]
        if vol_score <= -0.2:
            return [10, 8, 19]
        return [8, 10, 1]
    if direction_score <= -0.6:
        if vol_score >= 0.2:
            return [24, 11, 3]
        if vol_score <= -0.2:
            return [9, 11, 2]
        return [11, 3, 9]
    if direction_score <= -0.25:
        if vol_score >= 0.2:
            return [11, 3, 24]
        if vol_score <= -0.2:
            return [9, 11, 19]
        return [11, 9, 3]
    if vol_score >= 0.2:
        return [12, 14, 17]
    if vol_score <= -0.2:
        return [19, 18, 15]
    return [19, 18, 12]


def build_signal_strategy_profile(chain_data: dict, top_n: int = 6) -> dict:
    mismatch = _scan_liquid_mismatches(chain_data, top_n=top_n)
    oi = _summarize_oi_pressure(chain_data)

    mismatch_direction_score = float(mismatch.get("direction_score", 0.0))
    oi_direction_score = float(oi.get("score", 0.0))
    combined_direction = _clamp((mismatch_direction_score * 0.65) + (oi_direction_score * 0.35), -1.0, 1.0)
    vol_score = _clamp(float(mismatch.get("vol_score", 0.0)), -1.0, 1.0)
    agreement = 1.0 - min(abs(mismatch_direction_score - oi_direction_score), 2.0) / 2.0
    confidence = _clamp(
        (abs(combined_direction) * 0.45) + (abs(vol_score) * 0.25) + (agreement * 0.30),
        0.0,
        1.0,
    )

    if combined_direction >= 0.12:
        direction = "bullish"
    elif combined_direction <= -0.12:
        direction = "bearish"
    else:
        direction = "neutral"

    if vol_score >= 0.15:
        volatility_bias = "long_vol"
    elif vol_score <= -0.15:
        volatility_bias = "short_vol"
    else:
        volatility_bias = "balanced"

    recommended_strategy_ids = _signal_strategy_ids(combined_direction, vol_score)
    top_edges = [{
        "strike": item["strike"],
        "right": item["right"],
        "action": item["action"],
        "signal": item["signal"],
        "diff": round(float(item["diff"]), 2),
        "edge_pct": round(float(item["edge_pct"]), 2),
        "oi": item["oi"],
        "volume": item["volume"],
    } for item in mismatch.get("top", [])]

    direction_reason = {
        "bullish": "put-side support dominates near ATM and the liquid mismatch set leans bullish.",
        "bearish": "call-side resistance dominates near ATM and the liquid mismatch set leans bearish.",
        "neutral": "OI is balanced near ATM and the mismatch set does not show a clean directional edge.",
    }[direction]
    vol_reason = {
        "long_vol": "The richest liquid edges are on option buying, so long-vol structures are preferred.",
        "short_vol": "The richest liquid edges are on option selling, so premium-selling structures are preferred.",
        "balanced": "Mismatch edges are mixed, so defined-risk directional structures are preferred over pure vol bets.",
    }[volatility_bias]

    return {
        "symbol": str(chain_data.get("symbol", "") or ""),
        "underlying": _symbol_label(chain_data.get("symbol", "")),
        "spot": float(chain_data.get("spot", 0) or 0),
        "expiry": str(chain_data.get("expiry", "") or ""),
        "lot_size": int(float(chain_data.get("lot_size", 0) or 0)) if chain_data.get("lot_size") else (30 if "BANK" in str(chain_data.get("symbol", "")).upper() else 65),
        "oi": oi,
        "mismatch": {
            "direction_score": mismatch_direction_score,
            "vol_score": float(mismatch.get("vol_score", 0.0)),
            "used_oi_filter": bool(mismatch.get("used_oi_filter")),
            "expiry_dte": float(mismatch.get("expiry_dte", 0.0)),
            "top_edges": top_edges,
        },
        "combined": {
            "direction": direction,
            "direction_score": round(combined_direction, 4),
            "volatility_bias": volatility_bias,
            "vol_score": round(vol_score, 4),
            "confidence": round(confidence, 4),
            "agreement": round(agreement, 4),
            "rationale": f"{direction_reason} {vol_reason}",
        },
        "recommended_strategy_ids": recommended_strategy_ids,
    }


def _resolve_strategy_to_live_legs(template_id: int, chain_data: dict, num_lots: int = 1) -> dict | None:
    template = get_strategy_by_id(int(template_id))
    if not template:
        return None

    rows = _sorted_chain_rows(chain_data)
    spot = float(chain_data.get("spot", 0) or 0)
    expiry = str(chain_data.get("expiry", "") or "")
    lot_size = int(float(chain_data.get("lot_size", 0) or 0)) if chain_data.get("lot_size") else (30 if "BANK" in str(chain_data.get("symbol", "")).upper() else 65)
    if not rows or spot <= 0:
        return None

    strikes = [int(round(float(row.get("strike", 0) or 0))) for row in rows if float(row.get("strike", 0) or 0) > 0]
    if not strikes:
        return None
    atm_idx = min(range(len(strikes)), key=lambda idx: abs(strikes[idx] - spot))
    row_map = {int(round(float(row.get("strike", 0) or 0))): row for row in rows}

    legs: list[dict] = []
    for leg_template in template.legs:
        idx = max(0, min(len(strikes) - 1, atm_idx + int(leg_template.strike_offset)))
        strike = strikes[idx]
        row = row_map.get(strike)
        if not row:
            return None
        point = row.get(leg_template.right.value, {}) or {}
        premium = float(point.get("ltp", 0) or point.get("premium", 0) or 0)
        iv_raw = float(point.get("iv", 0) or 0)
        if premium <= 0 or iv_raw <= 0:
            return None
        legs.append({
            "side": leg_template.side.value,
            "right": leg_template.right.value,
            "strike": strike,
            "qty": max(lot_size, 1) * max(int(leg_template.qty_multiplier), 1) * max(int(num_lots), 1),
            "premium": round(premium, 2),
            "expiry": expiry,
            "iv": iv_raw / 100.0 if iv_raw > 1 else iv_raw,
            "delta": point.get("delta"),
            "gamma": point.get("gamma"),
            "vega": point.get("vega"),
            "theta": point.get("theta"),
        })

    return {
        "template": template,
        "legs": legs,
        "lot_size": lot_size,
        "expiry": expiry,
        "spot": spot,
    }


def build_mispricing_context(chain_data: dict, top_n: int = 8) -> str:
    """
    Deterministic BSM mispricing table for the AI to consume.
    This prevents model-side arithmetic drift when answering mismatch queries.
    """
    if not chain_data:
        return ""

    rows = chain_data.get("chain", []) or []
    spot = float(chain_data.get("spot", 0) or 0)
    expiry = str(chain_data.get("expiry", "") or "")
    symbol = str(chain_data.get("symbol", "") or "")
    if spot <= 0 or not rows:
        return ""

    # Keep T handling consistent with live chain normalization.
    T = 7 / 365.0
    if expiry:
        try:
            exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
            now = datetime.now()
            days_to_exp = (exp_dt - now).total_seconds() / 86400.0
            T = max(days_to_exp / 365.0, 1 / 365.0)
        except Exception:
            pass

    from .pricing_engine import bs_price, delta as bs_delta, vega as bs_vega, infer_dividend_yield

    r = 0.10
    underlying_hint = "BANKNIFTY" if "BANK" in symbol.upper() else ("NIFTY" if "NIFTY" in symbol.upper() else symbol)
    q = infer_dividend_yield(underlying_hint, spot)

    scanned: list[dict] = []
    for row in rows:
        strike = float(row.get("strike", 0) or 0)
        if strike <= 0:
            continue
        for right in ("CE", "PE"):
            opt = (row.get(right) or {})
            iv_pct = float(opt.get("iv", 0) or 0)
            if iv_pct <= 0:
                continue

            market = float(opt.get("ltp", 0) or opt.get("premium", 0) or 0)
            if market <= 0:
                continue

            oi = int(float(opt.get("oi", 0) or 0))
            volume = int(float(opt.get("volume", 0) or 0))
            if volume < 500:
                continue

            sigma = iv_pct / 100.0
            fair = bs_price(spot, strike, r, sigma, T, right, q=q)
            model_delta = bs_delta(spot, strike, r, sigma, T, right, q=q)
            model_vega = bs_vega(spot, strike, r, sigma, T, q=q)
            market_delta = float(opt.get("delta", model_delta) or model_delta)
            mispricing = market - fair

            scanned.append({
                "strike": int(round(strike)),
                "right": right,
                "market": market,
                "fair": fair,
                "diff": mispricing,
                "abs_diff": abs(mispricing),
                "signal": "UNDERVALUED" if mispricing < 0 else "OVERVALUED",
                "iv": iv_pct,
                "oi": oi,
                "volume": volume,
                "delta_market": market_delta,
                "delta_model": model_delta,
                "delta_gap": market_delta - model_delta,
                "vega_model": model_vega,
            })

    if not scanned:
        return (
            "\n=== ENGINE MISPRICING SCAN (BSM EXACT) ===\n"
            "No liquid strikes matched the filter (Volume >= 500)."
        )

    strict = [x for x in scanned if x["oi"] >= 50_000]
    used_oi_filter = True
    if len(strict) >= 3:
        liquid = strict
    else:
        liquid = scanned
        used_oi_filter = False

    liquid.sort(key=lambda x: x["abs_diff"], reverse=True)
    top = liquid[: max(int(top_n), 3)]

    lines = [
        "\n=== ENGINE MISPRICING SCAN (BSM EXACT) ===",
        (
            f"Assumptions: r=0.10 | q={q:.4f} | T_days={T*365:.2f} | "
            f"filter {'OI>=50000 + ' if used_oi_filter else 'OI unavailable -> '}Volume>=500"
        ),
        "Rank | Strike | Type | Market | Fair | Diff(mkt-fair) | Signal | IV | OI | Vol | Delta(mkt/model/gap) | Vega(model)",
    ]
    for idx, item in enumerate(top, start=1):
        lines.append(
            f"{idx:>2} | {item['strike']} | {item['right']} | {item['market']:.2f} | {item['fair']:.2f} | "
            f"{item['diff']:+.2f} | {item['signal']} | {item['iv']:.2f}% | {item['oi']} | {item['volume']} | "
            f"{item['delta_market']:.4f}/{item['delta_model']:.4f}/{item['delta_gap']:+.4f} | {item['vega_model']:.3f}"
        )

    lines.append("Use this table directly for mismatch ranking and trade direction. Do not recompute fair values.")
    return "\n".join(lines)


def build_deterministic_mismatch_reply(chain_data: dict, top_n: int = 3) -> str:
    """
    Deterministic response for mismatch / OI signal queries.
    Produces a strategy recommendation, not just a loose basket of edges.
    """
    if not chain_data:
        return ""

    profile = build_signal_strategy_profile(chain_data, top_n=max(int(top_n), 3))
    top_edges = profile.get("mismatch", {}).get("top_edges", [])
    if not top_edges:
        return (
            "## Signal Strategy Engine\n"
            "No liquid strikes matched the filter (`Volume >= 500`)."
        )

    primary_id = int(profile["recommended_strategy_ids"][0])
    resolved = _resolve_strategy_to_live_legs(primary_id, chain_data)
    if not resolved:
        return "## Signal Strategy Engine\nUnable to resolve the recommended strategy against the current live chain."

    from .pricing_engine import compute_strategy_metrics, compute_enhanced_metrics

    legs = [ConcreteLeg(**leg) for leg in resolved["legs"]]
    metrics = compute_strategy_metrics(resolved["spot"], legs)
    enhanced = compute_enhanced_metrics(
        resolved["spot"],
        legs,
        dte=max(int(round(float(profile["mismatch"].get("expiry_dte", 0.0)))), 0),
        underlying=profile["underlying"],
    )

    combined = profile["combined"]
    oi = profile["oi"]
    alt_names = []
    for strategy_id in profile["recommended_strategy_ids"][1:3]:
        template = get_strategy_by_id(int(strategy_id))
        if template:
            alt_names.append(template.name)

    exit_rules = (
        "Take 50% of max profit or exit on 1.25x initial credit loss."
        if combined["volatility_bias"] == "short_vol"
        else "Take profit on 35-40% premium expansion or exit one session before expiry."
    )

    lines = [
        "## Signal Strategy Engine",
        "",
        "| Underlying | Spot | Expiry | DTE | Signal Bias | Vol Bias | Confidence |",
        "| :--- | ---: | :---: | ---: | :--- | :--- | ---: |",
        f"| {profile['underlying']} | {profile['spot']:.2f} | {profile['expiry']} | {profile['mismatch']['expiry_dte']:.2f}d | {combined['direction']} | {combined['volatility_bias']} | {combined['confidence'] * 100:.1f}% |",
        "",
        "### OI Positioning",
        "",
        "| PCR (ATM window) | Put Support | Call Resistance | OI Bias |",
        "| ---: | ---: | ---: | :--- |",
        f"| {oi['put_call_ratio']:.3f} | {oi['dominant_put_strike'] or '-'} | {oi['dominant_call_strike'] or '-'} | {oi['direction']} |",
        "",
        "### Top Liquid Mismatch Edges",
        "",
        "| Rank | Strike | Type | Action | Diff (mkt-fair) | Edge % | OI | Vol |",
        "| ---: | ---: | :---: | :---: | ---: | ---: | ---: | ---: |",
    ]

    for idx, edge in enumerate(top_edges[: max(int(top_n), 3)], start=1):
        lines.append(
            f"| {idx} | {edge['strike']} | {edge['right']} | {edge['action']} | {edge['diff']:+.2f} | "
            f"{edge['edge_pct']:+.2f}% | {edge['oi']} | {edge['volume']} |"
        )

    lines.extend([
        "",
        "### Best Strategy Fit",
        "",
        f"Primary recommendation: **{resolved['template'].name}**. {combined['rationale']}",
    ])
    if alt_names:
        lines.append(f"Alternatives: {', '.join(alt_names)}.")

    lines.extend([
        "",
        "| Leg | Side | Right | Strike | Qty | Entry |",
        "| ---: | :---: | :---: | ---: | ---: | ---: |",
    ])
    for idx, leg in enumerate(resolved["legs"], start=1):
        lines.append(
            f"| {idx} | {leg['side']} | {leg['right']} | {leg['strike']} | {leg['qty']} | {leg['premium']:.2f} |"
        )

    lines.extend([
        "",
        "| Max Profit | Max Loss | Breakevens | PoP | Capital | Theta/day |",
        "| ---: | ---: | :--- | ---: | ---: | ---: |",
        f"| {metrics['max_profit']:.2f} | {metrics['max_loss']:.2f} | "
        f"{', '.join(str(round(be, 2)) for be in metrics['breakevens']) or '-'} | "
        f"{float(enhanced.get('pop', 0.0)):.1f}% | {float(enhanced.get('capital_required', 0.0)):.2f} | "
        f"{float(enhanced.get('theta_daily', 0.0)):.2f} |",
        "",
        "```json",
        "{",
        '  "action": "deploy_strategy",',
        f'  "strategy_name": "{resolved["template"].name}",',
        f'  "reasoning": "{combined["rationale"]}",',
        '  "legs": [',
    ])

    for index, leg in enumerate(resolved["legs"]):
        suffix = "," if index < len(resolved["legs"]) - 1 else ""
        lines.append(
            f'    {{"side": "{leg["side"]}", "right": "{leg["right"]}", "strike": {leg["strike"]}, '
            f'"qty": {leg["qty"]}, "premium": {leg["premium"]}}}{suffix}'
        )

    lines.extend([
        "  ],",
        f'  "exit_rules": "{exit_rules}",',
        f'  "pop": {round(float(enhanced.get("pop", 0.0)), 2)},',
        f'  "capital_required": {round(float(enhanced.get("capital_required", 0.0)), 2)},',
        f'  "theta_per_day": {round(float(enhanced.get("theta_daily", 0.0)), 2)}',
        "}",
        "```",
    ])

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_with_ai(
    query: str,
    history: list[dict] | None = None,
    context: str | None = None,
    thinking_enabled: bool = True,
    image_b64: str | None = None,
    chain_data: dict | None = None,
) -> str:
    """Main AI call. Supports text + optional base64 image."""
    qtext = str(query or "").lower()
    oi_signal_query = (
        ("oi buildup" in qtext)
        or ("open interest" in qtext and "max pain" not in qtext)
        or (re.search(r"\boi\b", qtext) and any(token in qtext for token in ("bull", "bear", "strategy", "direction")))
    )
    if (
        chain_data
        and not image_b64
        and (
            "mismatch" in qtext
            or "mispriced" in qtext
            or ("delta" in qtext and "vega" in qtext and "bsm" in qtext)
            or oi_signal_query
        )
    ):
        deterministic = build_deterministic_mismatch_reply(chain_data, top_n=3)
        if deterministic:
            return deterministic

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for msg in history:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg.get("content", "")})

    # Build rich context
    full_context_parts = []
    if context:
        full_context_parts.append(context)
    if chain_data:
        full_context_parts.append(build_chain_context(chain_data))
        full_context_parts.append(build_mispricing_context(chain_data))

    full_context = "\n".join(full_context_parts)

    # Build user message — text or multimodal
    if image_b64:
        # Vision message with image
        user_content = [
            {
                "type": "text",
                "text": (
                    f"{full_context}\n\n"
                    f"---\nUser has attached an image. Analyse it precisely. "
                    f"Read every number, label, and pattern you can see.\n\n"
                    f"User query: {query}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
            },
        ]
        messages.append({"role": "user", "content": user_content})
    else:
        prompt = f"{full_context}\n\n---\nEngineer query: {query}" if full_context else query
        messages.append({"role": "user", "content": prompt})

    return _call_ai(messages, thinking_enabled=thinking_enabled, has_image=bool(image_b64))


def generate_strategy_from_description(
    description: str,
    underlying: str = "NIFTY",
    spot_price: float = 22000,
    risk_tolerance: str = "medium",
    thinking_enabled: bool = True,
) -> dict:
    """NL → Strategy JSON."""
    prompt = (
        f"Market view: {description}\nUnderlying: {underlying}\n"
        f"Spot: {spot_price}\nRisk tolerance: {risk_tolerance}\n\n"
        "Output ONLY a JSON object with keys: strategy_id (int 1-24), strategy_name, "
        "reasoning (2-3 sentences), confidence (0-1), suggested_params "
        "{strike_offset_width, num_lots, exit_rules}, alternative_strategy_id."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    result = _call_ai(messages, thinking_enabled=thinking_enabled)
    try:
        start = result.find("{"); end = result.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(result[start:end])
    except json.JSONDecodeError:
        pass
    return {
        "strategy_id": 19, "strategy_name": "Iron Condor",
        "reasoning": f"Parse error — defaulted to Iron Condor for: {description}",
        "confidence": 0.3, "raw_response": result,
    }


def build_legs_context(legs: list[ConcreteLeg]) -> str:
    if not legs:
        return "No active positions."
    lines = ["Current strategy legs:"]
    for leg in legs:
        lines.append(
            f"  {leg.side.value} {leg.qty}x {leg.strike} {leg.right.value} "
            f"@ ₹{leg.premium}"
            + (f" | IV:{leg.iv*100:.1f}%" if leg.iv is not None else "")
            + (f" | Δ:{leg.delta}" if leg.delta is not None else "")
        )
    return "\n".join(lines)


def _offline_response(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ["neutral", "sideways", "flat", "range"]):
        return "## Offline Mode\nNo OPENROUTER_API_KEY configured. For a range-bound view, Iron Condor (#19) or Short Strangle (#15) are canonical setups.\n\nSet `OPENROUTER_API_KEY` in `.env` for live quantitative analysis."
    if any(w in q for w in ["bull", "up", "rally"]):
        return "## Offline Mode\nFor a bullish view: Bull Call Spread (#8) or Bull Put Spread (#10).\n\nSet `OPENROUTER_API_KEY` in `.env` for live analysis."
    if any(w in q for w in ["bear", "down", "crash"]):
        return "## Offline Mode\nFor a bearish view: Bear Put Spread (#11) or Long Put (#3).\n\nSet `OPENROUTER_API_KEY` in `.env` for live analysis."
    return (
        "## Offline Mode\n"
        "Configure `OPENROUTER_API_KEY` in `.env` for AI-powered quantitative analysis.\n\n"
        "Available: 24 canonical options strategies covering all views (bullish/bearish/neutral/volatile)."
    )
