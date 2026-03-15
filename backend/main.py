"""
FastAPI application — 24 Options Strategies Platform.
Production-grade REST API with strategy management, pricing, broker integration,
deployment, monitoring, and AI copilot.
"""

from __future__ import annotations
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Any
import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

from .models import (
    PayoffRequest, GreeksRequest, ScenarioRequest, ResolveRequest,
    AIChatRequest, AIStrategyRequest, ConcreteLeg, Side, OptionRight,
)
from .strategies import get_all_strategies, get_strategy_by_id
from .pricing_engine import (
    calculate_payoff, compute_strategy_greeks,
    scenario_analysis, compute_strategy_metrics,
    compute_enhanced_metrics, find_optimal_strikes, infer_dividend_yield,
)
from .market_schedule import market_status as get_market_status
from .ai_engine import (
    analyze_with_ai,
    generate_strategy_from_description,
    build_legs_context,
    build_chain_context,
    build_signal_strategy_profile,
)
from .fyers_client import FyersAPIClient
from .paper_trade import PaperTradingEngine
from .risk_manager import RiskManager
from .db import init_db
from .quant_engine import QuantEngineService

load_dotenv()

# ──────────────────────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="24 Options Strategies Platform",
    description="Professional-grade options strategy builder with AI copilot",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared broker client — will be authenticated at startup via terminal
fyers_client = FyersAPIClient()
paper_engine = PaperTradingEngine()
risk_manager = RiskManager()
quant_engine = QuantEngineService(fyers_client=fyers_client, paper_engine=paper_engine)


def _default_lot_size_for_symbol(symbol: str) -> int:
    s = str(symbol or "").upper()
    if "BANK" in s:
        return 30
    if "NIFTY" in s:
        return 65
    return 1


def _paper_state_snapshot() -> dict:
    return jsonable_encoder({
        "strategies": [s.model_dump() for s in paper_engine.strategies],
        "positions": [p.model_dump() for p in paper_engine.positions],
        "portfolio": paper_engine.get_portfolio_summary(),
    })


@app.on_event("startup")
async def startup():
    init_db()
    if fyers_client.is_authenticated:
        fyers_client.validate_session()


# ──────────────────────────────────────────────────────────────
# Health & Status
# ──────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    if fyers_client.is_authenticated:
        fyers_client.validate_session()
    return {
        "status": "ok",
        "version": "2.0.0",
        "broker_connected": fyers_client.is_authenticated,
        "mode": "LIVE" if fyers_client.is_authenticated else "PAPER",
    }


# ──────────────────────────────────────────────────────────────
# Strategy Catalog
# ──────────────────────────────────────────────────────────────

@app.get("/api/strategies")
def list_strategies():
    strategies = get_all_strategies()
    return {"count": len(strategies), "strategies": [s.model_dump() for s in strategies]}


@app.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: int):
    s = get_strategy_by_id(strategy_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Strategy #{strategy_id} not found")
    return s.model_dump()


@app.post("/api/strategies/resolve")
def resolve_strategy(req: ResolveRequest):
    template = get_strategy_by_id(req.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Strategy #{req.template_id} not found")

    chain_data = fyers_client.get_option_chain(req.underlying)
    # Prefer the spot_price sent from the frontend (which comes from the live
    # top-bar quote) over whatever the chain normalizer extracted. The chain
    # normalizer can still misread it if Fyers changes their response schema.
    chain_spot = chain_data.get("spot", 0)
    spot = req.spot_price if req.spot_price > 0 else (chain_spot if chain_spot > 1000 else req.spot_price)
    chain = chain_data.get("chain", [])
    expiry = req.expiry or chain_data.get("expiry", "")
    lot_size = int(req.lot_size) if req.lot_size > 0 else int(chain_data.get("lot_size") or _default_lot_size_for_symbol(req.underlying))
    num_lots = max(int(req.num_lots), 1)

    if not chain:
        raise HTTPException(status_code=500, detail="No chain data available")

    strikes = sorted(set(c["strike"] for c in chain))
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

    concrete_legs = []
    for leg_tmpl in template.legs:
        target_idx = atm_idx + leg_tmpl.strike_offset
        target_idx = max(0, min(len(strikes) - 1, target_idx))
        target_strike = strikes[target_idx]

        row = next((c for c in chain if c["strike"] == target_strike), None)
        if not row:
            continue

        option_data = row.get(leg_tmpl.right.value, {})
        premium = option_data.get("premium", 0)
        iv_raw = option_data.get("iv", 18.0)
        iv = iv_raw / 100.0 if iv_raw > 1 else iv_raw

        concrete_legs.append(ConcreteLeg(
            side=leg_tmpl.side,
            right=leg_tmpl.right,
            strike=target_strike,
            premium=premium,
            qty=lot_size * num_lots * leg_tmpl.qty_multiplier,
            expiry=expiry,
            iv=iv,
            delta=option_data.get("delta"),
            gamma=option_data.get("gamma"),
            vega=option_data.get("vega"),
            theta=option_data.get("theta"),
        ))

    metrics = compute_strategy_metrics(spot, concrete_legs)
    greeks = compute_strategy_greeks(spot, concrete_legs, underlying=req.underlying)

    return {
        "template": template.model_dump(),
        "spot": spot,
        "expiry": expiry,
        "legs": [l.model_dump() for l in concrete_legs],
        "metrics": metrics,
        "greeks": greeks.model_dump(),
    }


# ──────────────────────────────────────────────────────────────
# Pricing & Analysis
# ──────────────────────────────────────────────────────────────

@app.post("/api/pricing/payoff")
def get_payoff(req: PayoffRequest):
    payoff_data = calculate_payoff(req.spot_price, req.legs)
    metrics = compute_strategy_metrics(req.spot_price, req.legs)
    return {"payoff": payoff_data, "metrics": metrics}


# ──────────────────────────────────────────────────────────────
# Market Schedule
# ──────────────────────────────────────────────────────────────

@app.get("/api/market/status")
def market_status_endpoint():
    return get_market_status()


# ──────────────────────────────────────────────────────────────
# Pricing — Enhanced Metrics
# ──────────────────────────────────────────────────────────────

class EnhancedMetricsRequest(BaseModel):
    spot_price: float
    legs: list[ConcreteLeg]
    dte: int = 7
    risk_free_rate: float = 0.10
    underlying: Optional[str] = None


@app.post("/api/pricing/enhanced-metrics")
def get_enhanced_metrics(req: EnhancedMetricsRequest):
    return compute_enhanced_metrics(
        req.spot_price,
        req.legs,
        req.dte,
        req.risk_free_rate,
        underlying=req.underlying,
    )


# ──────────────────────────────────────────────────────────────
# Strike Optimizer
# ──────────────────────────────────────────────────────────────

class OptimizeStrikesRequest(BaseModel):
    template_id: int
    underlying: str = "NSE:NIFTY50-INDEX"
    spot_price: float = 22500
    expiry: str = ""
    lot_size: int = 0
    dte: int = 7
    top_n: int = 3


@app.post("/api/pricing/optimize-strikes")
def optimize_strikes(req: OptimizeStrikesRequest):
    template = get_strategy_by_id(req.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Strategy #{req.template_id} not found")

    chain_data = fyers_client.get_option_chain(req.underlying)
    chain = chain_data.get("chain", [])
    if not chain:
        raise HTTPException(status_code=503, detail="No chain data available")

    spot = req.spot_price if req.spot_price > 1000 else chain_data.get("spot", req.spot_price)
    lot_size = int(req.lot_size) if req.lot_size > 0 else int(chain_data.get("lot_size") or _default_lot_size_for_symbol(req.underlying))

    combos = find_optimal_strikes(
        spot=spot,
        chain=chain,
        leg_templates=template.legs,
        lot_size=lot_size,
        dte=req.dte,
        top_n=req.top_n,
        underlying=req.underlying,
    )
    return {
        "template": template.name,
        "spot": spot,
        "combos": combos,
        "total_found": len(combos),
    }



@app.post("/api/pricing/greeks")
def get_greeks(req: GreeksRequest):
    greeks = compute_strategy_greeks(
        spot=req.spot_price,
        legs=req.legs,
        risk_free_rate=req.risk_free_rate,
        underlying=req.underlying,
    )
    return greeks.model_dump()


@app.post("/api/pricing/scenario")
def run_scenario(req: ScenarioRequest):
    return scenario_analysis(
        spot_price=req.spot_price, legs=req.legs,
        delta_spot_pct=req.delta_spot_pct, delta_iv_points=req.delta_iv_points,
        delta_days=req.delta_days, risk_free_rate=req.risk_free_rate,
        underlying=req.underlying,
    )


# ──────────────────────────────────────────────────────────────
# Option Chain & Expiries
# ──────────────────────────────────────────────────────────────

@app.get("/api/chain")
def get_option_chain(symbol: str = "NSE:NIFTY50-INDEX", strike_count: int = 15, expiry: str = None):
    return fyers_client.get_option_chain(symbol, strike_count, expiry)


@app.get("/api/expiries")
def get_expiries(symbol: str = "NSE:NIFTY50-INDEX"):
    expiries = fyers_client.get_available_expiries(symbol)
    return {"symbol": symbol, "expiries": expiries}


@app.websocket("/ws/market-stream")
async def market_stream(
    websocket: WebSocket,
    symbol: str = "NSE:NIFTY50-INDEX",
    strike_count: int = 15,
    expiry: str = "",
):
    await websocket.accept()
    while True:
        try:
            chain = fyers_client.get_option_chain(
                symbol=symbol,
                strike_count=strike_count,
                expiry=expiry or None,
            )
            spot = float(chain.get("spot", 0) or 0)
            if spot > 0:
                paper_engine.update_mtm(
                    spot,
                    chain=chain.get("chain", []),
                    underlying=symbol,
                    chain_expiry=chain.get("expiry", ""),
                )
                # Approved once -> autonomous paper/live management cycle.
                try:
                    quant_engine.run_autopilot_cycle(
                        symbol,
                        force=False,
                        chain_data=chain,
                    )
                except Exception:
                    # Keep market stream resilient even if autopilot action fails.
                    pass

            chain_source = str(chain.get("source", "mock")).lower()
            chain_is_live = chain_source == "live"

            await websocket.send_json({
                "type": "snapshot",
                "timestamp": datetime.now().isoformat(),
                "broker_connected": fyers_client.is_authenticated and chain_is_live,
                "chain": chain,
                "paper": _paper_state_snapshot(),
            })
            await asyncio.sleep(0.35 if chain_is_live else 1.0)
        except WebSocketDisconnect:
            break
        except Exception as e:
            try:
                await websocket.send_json({
                    "type": "error",
                    "timestamp": datetime.now().isoformat(),
                    "message": str(e),
                })
                await asyncio.sleep(1.0)
            except Exception:
                break


# ──────────────────────────────────────────────────────────────
# Strategy Deployment (Broker)
# ──────────────────────────────────────────────────────────────

class DeployRequest(BaseModel):
    legs: list[dict]
    underlying: str = "NIFTY"
    strategy_name: str = ""


@app.post("/api/broker/deploy")
def deploy_strategy(req: DeployRequest):
    """Deploy a strategy to the live broker account."""
    if not fyers_client.is_authenticated:
        raise HTTPException(status_code=401, detail="Broker not connected. Run ./run.sh to authenticate.")
    return fyers_client.deploy_strategy(req.legs, req.underlying)


@app.get("/api/broker/positions")
def broker_positions():
    return fyers_client.get_positions()


@app.get("/api/broker/orders")
def broker_orders():
    return fyers_client.get_orders()


@app.get("/api/broker/funds")
def broker_funds():
    return fyers_client.get_funds()


@app.get("/api/broker/profile")
def broker_profile():
    return fyers_client.get_profile()


# ──────────────────────────────────────────────────────────────
# Paper Trading
# ──────────────────────────────────────────────────────────────

@app.post("/api/paper/open")
def paper_open_strategy(req: ResolveRequest):
    template = get_strategy_by_id(req.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Strategy #{req.template_id} not found")
    resolved = resolve_strategy(req)
    legs = [ConcreteLeg(**l) for l in resolved["legs"]]
    instance = paper_engine.open_strategy(
        template=template, legs=legs, underlying=req.underlying, spot_price=resolved["spot"],
    )
    return {"status": "opened", "instance": instance.model_dump(), "metrics": resolved["metrics"]}


class PaperOpenCustomRequest(BaseModel):
    legs: list[ConcreteLeg]
    underlying: str = "NIFTY"
    spot_price: float = 22500
    strategy_name: str = "Custom Strategy"


@app.post("/api/paper/open-custom")
def paper_open_custom(req: PaperOpenCustomRequest):
    """Open a custom-built strategy in paper trading."""
    from .models import StrategyTemplate, StrategyCategory, PayoffType
    custom_template = StrategyTemplate(
        id=0, name=req.strategy_name, category=StrategyCategory.NEUTRAL,
        subcategory="Custom", legs=[], description="Custom built strategy",
        primary_view="User-defined", payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Custom", max_reward="Custom", breakeven_formula="Custom",
    )
    instance = paper_engine.open_strategy(
        template=custom_template, legs=req.legs,
        underlying=req.underlying, spot_price=req.spot_price,
    )
    metrics = compute_strategy_metrics(req.spot_price, req.legs)
    return {"status": "opened", "instance": instance.model_dump(), "metrics": metrics}


@app.post("/api/paper/close/{strategy_id}")
def paper_close_strategy(strategy_id: str, spot_price: float = 22500):
    return paper_engine.close_strategy(strategy_id, spot_price)


@app.get("/api/paper/portfolio")
def paper_portfolio():
    return paper_engine.get_portfolio_summary()


@app.get("/api/paper/positions")
def paper_positions():
    return {
        "strategies": [s.model_dump() for s in paper_engine.strategies],
        "positions": [p.model_dump() for p in paper_engine.positions],
    }


@app.post("/api/paper/refresh")
def paper_refresh(spot_price: Optional[float] = None, underlying: str = "NSE:NIFTY50-INDEX"):
    """Mark-to-market all paper positions; auto-pull live spot if not provided."""
    spot = spot_price if spot_price and spot_price > 0 else None
    chain_rows = None
    chain_expiry = None
    if spot is None:
        chain = fyers_client.get_option_chain(underlying)
        spot = float(chain.get("spot", 22500))
        chain_rows = chain.get("chain", [])
        chain_expiry = chain.get("expiry", "")
    paper_engine.update_mtm(
        float(spot),
        chain=chain_rows,
        underlying=underlying,
        chain_expiry=chain_expiry,
    )
    summary = paper_engine.get_portfolio_summary()
    summary["spot"] = round(float(spot), 2)
    return summary


# ──────────────────────────────────────────────────────────────
# Risk Management
# ──────────────────────────────────────────────────────────────

@app.get("/api/risk/summary")
def risk_summary(spot: float = 22500):
    summary = risk_manager.evaluate(strategies=paper_engine.strategies, spot=spot)
    return summary.model_dump()


# ──────────────────────────────────────────────────────────────
# Quant Engine v1 (Autopilot + Optimizer + Learning Loop)
# ──────────────────────────────────────────────────────────────

class QuantProfilePatchRequest(BaseModel):
    patch: dict[str, Any] = {}


class QuantLegsRequest(BaseModel):
    underlying: str = "NSE:NIFTY50-INDEX"
    spot_price: Optional[float] = None
    legs: list[ConcreteLeg] = []


class QuantPortfolioOptimizeRequest(BaseModel):
    underlying: str = "NSE:NIFTY50-INDEX"
    target_delta: Optional[float] = None
    target_vega: Optional[float] = None


class QuantAutopilotApproveRequest(BaseModel):
    mode: str = "paper"  # paper | live
    rebalance_interval_sec: int = 30
    allow_strategy_switch: bool = True
    allow_live_execution: bool = False
    max_active_rebalance_per_symbol: int = 1
    approval_note: str = ""


class QuantAutopilotRunRequest(BaseModel):
    underlying: str = "NSE:NIFTY50-INDEX"
    force: bool = False


@app.get("/api/quant/assets")
def quant_assets():
    return {"assets": quant_engine.get_supported_assets()}


@app.get("/api/quant/profile")
def quant_get_profile():
    return quant_engine.get_profile()


@app.post("/api/quant/profile")
def quant_update_profile(req: QuantProfilePatchRequest):
    return quant_engine.update_profile(req.patch)


@app.get("/api/quant/regime")
def quant_regime(underlying: str = "NSE:NIFTY50-INDEX"):
    chain = fyers_client.get_option_chain(underlying)
    return quant_engine.analyze_regime(underlying, chain_data=chain)


@app.get("/api/quant/adaptive-recommendation")
def quant_adaptive_recommendation(underlying: str = "NSE:NIFTY50-INDEX", num_lots: int = 1):
    return quant_engine.build_adaptive_recommendation(underlying, num_lots=max(1, int(num_lots)))


@app.post("/api/quant/decision-score")
def quant_decision_score(req: QuantLegsRequest):
    if not req.legs:
        raise HTTPException(status_code=400, detail="legs cannot be empty")
    chain = fyers_client.get_option_chain(req.underlying)
    spot = req.spot_price if req.spot_price and req.spot_price > 0 else float(chain.get("spot", 0))
    return quant_engine.score_decision(
        req.underlying,
        req.legs,
        chain_data=chain,
        spot=spot,
    )


@app.post("/api/quant/execution-plan")
def quant_execution_plan(req: QuantLegsRequest):
    if not req.legs:
        raise HTTPException(status_code=400, detail="legs cannot be empty")
    chain = fyers_client.get_option_chain(req.underlying)
    return quant_engine.build_execution_plan(req.underlying, req.legs, chain_data=chain)


@app.post("/api/quant/portfolio-optimize")
def quant_portfolio_optimize(req: QuantPortfolioOptimizeRequest):
    chain = fyers_client.get_option_chain(req.underlying)
    return quant_engine.optimize_portfolio(
        req.underlying,
        target_delta=req.target_delta,
        target_vega=req.target_vega,
        chain_data=chain,
    )


@app.get("/api/quant/adjustments")
def quant_adjustments(underlying: str = "NSE:NIFTY50-INDEX"):
    chain = fyers_client.get_option_chain(underlying)
    return quant_engine.generate_adjustments(underlying, chain_data=chain)


@app.post("/api/quant/autopilot/approve")
def quant_autopilot_approve(req: QuantAutopilotApproveRequest):
    return quant_engine.approve_autopilot(req.model_dump())


@app.post("/api/quant/autopilot/pause")
def quant_autopilot_pause(reason: str = "manual pause"):
    return quant_engine.pause_autopilot(reason=reason)


@app.get("/api/quant/autopilot/status")
def quant_autopilot_status():
    return quant_engine.get_autopilot_state()


@app.post("/api/quant/autopilot/run")
def quant_autopilot_run(req: QuantAutopilotRunRequest):
    chain = fyers_client.get_option_chain(req.underlying)
    return quant_engine.run_autopilot_cycle(
        req.underlying,
        force=bool(req.force),
        chain_data=chain,
    )


@app.get("/api/quant/journal")
def quant_journal(limit: int = 100):
    return {"records": quant_engine.get_journal(limit=limit)}


@app.get("/api/quant/learning-summary")
def quant_learning_summary(limit: int = 200):
    return quant_engine.learning_summary(limit=limit)


# ──────────────────────────────────────────────────────────────
# AI Copilot
# ──────────────────────────────────────────────────────────────

class AIChatRequestV2(BaseModel):
    query: str
    history: list[dict] = []
    context: Optional[str] = None
    current_legs: list[ConcreteLeg] = []
    thinking_enabled: bool = True
    image_b64: Optional[str] = None   # base64-encoded image from paste/drag
    underlying: str = "NSE:NIFTY50-INDEX"  # for live chain fetch


@app.post("/api/ai/chat")
def ai_chat(req: AIChatRequestV2):
    # Build text context
    context = req.context or ""
    if req.current_legs:
        context += "\n" + build_legs_context(req.current_legs)

    # Fetch live chain data and inject into AI context
    chain_data: dict | None = None
    try:
        chain_data = fyers_client.get_option_chain(req.underlying)
    except Exception:
        chain_data = None

    response = analyze_with_ai(
        query=req.query,
        history=req.history,
        context=context if context else None,
        thinking_enabled=req.thinking_enabled,
        image_b64=req.image_b64 if req.image_b64 else None,
        chain_data=chain_data,
    )
    return {"reply": response}


class AIStrategyRequestV2(BaseModel):
    description: str
    underlying: str = "NIFTY"
    spot_price: float = 22000
    risk_tolerance: str = "medium"
    thinking_enabled: bool = True


@app.post("/api/ai/generate-strategy")
def ai_generate_strategy(req: AIStrategyRequestV2):
    return generate_strategy_from_description(
        description=req.description, underlying=req.underlying,
        spot_price=req.spot_price, risk_tolerance=req.risk_tolerance,
        thinking_enabled=req.thinking_enabled,
    )


# ──────────────────────────────────────────────────────────────
# AI Best Picks — scored by Greeks, probability, max profit/loss
# ──────────────────────────────────────────────────────────────

@app.get("/api/ai/best-picks")
def ai_best_picks(underlying: str = "NIFTY"):
    """
    Score all 24 strategies based on current market data (Greeks, IV, expiry,
    probability of profit, max profit/loss) and return the top 5 picks.
    """
    sym_map = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX"}
    chain_data = fyers_client.get_option_chain(sym_map.get(underlying, f"NSE:{underlying}50-INDEX"))
    spot = chain_data.get("spot", 22500)
    chain = chain_data.get("chain", [])
    expiry = chain_data.get("expiry", "")
    lot_size = int(chain_data.get("lot_size") or _default_lot_size_for_symbol(underlying))

    if not chain:
        return {"picks": [], "error": "No chain data available"}

    strategies = get_all_strategies()
    scored: list[dict] = []
    signal_profile = build_signal_strategy_profile(chain_data, top_n=6)
    preferred_ids = [int(value) for value in signal_profile.get("recommended_strategy_ids", [])]
    preferred_rank = {strategy_id: index for index, strategy_id in enumerate(preferred_ids)}
    combined_signal = signal_profile.get("combined", {})
    signal_direction = str(combined_signal.get("direction", "neutral"))
    volatility_bias = str(combined_signal.get("volatility_bias", "balanced"))
    signal_confidence = float(combined_signal.get("confidence", 0.0))
    signal_rationale = str(combined_signal.get("rationale", ""))

    # Expiry-aware horizon for scoring metrics.
    dte = 7
    if expiry:
        try:
            dte = max((datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.now().date()).days, 0)
        except ValueError:
            dte = 7

    row_map = {c["strike"]: c for c in chain}
    dividend_yield = infer_dividend_yield(underlying=underlying, spot=spot)

    for template in strategies:
        try:
            # Resolve the strategy against current chain
            strikes = sorted(set(c["strike"] for c in chain))
            atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

            valid_template = True
            legs: list[ConcreteLeg] = []
            for leg_tmpl in template.legs:
                idx = max(0, min(len(strikes) - 1, atm_idx + leg_tmpl.strike_offset))
                strike = strikes[idx]
                row = row_map.get(strike)
                if not row:
                    valid_template = False
                    break
                opt = row.get(leg_tmpl.right.value, {})
                premium = float(opt.get("premium", 0) or 0)
                iv_raw = float(opt.get("iv", 0) or 0)
                iv = iv_raw / 100.0 if iv_raw > 1 else iv_raw
                if premium <= 0 or iv <= 0:
                    valid_template = False
                    break
                legs.append(ConcreteLeg(
                    side=leg_tmpl.side, right=leg_tmpl.right,
                    strike=strike, premium=premium,
                    qty=lot_size * leg_tmpl.qty_multiplier, expiry=expiry,
                    iv=iv,
                    delta=opt.get("delta"), gamma=opt.get("gamma"),
                    vega=opt.get("vega"), theta=opt.get("theta"),
                ))

            if not valid_template or len(legs) != len(template.legs):
                continue

            # Compute metrics
            metrics = compute_strategy_metrics(spot, legs)
            greeks = compute_strategy_greeks(
                spot,
                legs,
                dividend_yield=dividend_yield,
                underlying=underlying,
            )
            enhanced = compute_enhanced_metrics(
                spot,
                legs,
                dte=dte,
                dividend_yield=dividend_yield,
                underlying=underlying,
            )

            max_profit = metrics.get("max_profit", 0)
            unbounded_loss = bool(metrics.get("unbounded_loss", False))
            max_loss = abs(metrics.get("max_loss", -1))
            net_premium = metrics.get("net_premium", 0)

            # Base quant score ─ higher is better
            # 1. Risk-Reward Ratio (max_profit / max_loss)
            rr = 0.0 if unbounded_loss else (max_profit / max_loss if max_loss > 0 else 1.0)
            rr_score = min(rr * 20, 40)  # cap at 40

            # 2. Probability of Profit from shared enhanced-metrics engine
            pop = min(max(float(enhanced.get("pop", 50.0)) / 100.0, 0.0), 1.0)
            pop_score = pop * 30

            # 3. Theta advantage (positive theta is good for income)
            theta_score = max(0, min(greeks.theta * 0.3, 15))

            # 4. Defined risk bonus
            risk_defined = 1 if template.payoff_type.value.startswith("Limited Risk /") else 0
            risk_score = risk_defined * 15

            base_quant_score = round(rr_score + pop_score + theta_score + risk_score, 1)

            # Signal-fit score ─ OI pressure + Greek mismatch should dominate ranking.
            signal_fit = 10.0
            rank = preferred_rank.get(template.id)
            if rank == 0:
                signal_fit += 55.0
            elif rank == 1:
                signal_fit += 42.0
            elif rank == 2:
                signal_fit += 32.0

            if signal_direction == "bullish":
                if template.category.value == "Bullish":
                    signal_fit += 18.0 * signal_confidence
                elif template.category.value == "Bearish":
                    signal_fit -= 10.0 * signal_confidence
            elif signal_direction == "bearish":
                if template.category.value == "Bearish":
                    signal_fit += 18.0 * signal_confidence
                elif template.category.value == "Bullish":
                    signal_fit -= 10.0 * signal_confidence
            else:
                if template.category.value == "Neutral":
                    signal_fit += 12.0 * signal_confidence

            tags = {str(tag).lower() for tag in template.tags}
            if volatility_bias == "long_vol":
                if tags & {"volatility", "backspread", "event-play"}:
                    signal_fit += 12.0
                if tags & {"income", "short-vol"}:
                    signal_fit -= 8.0
            elif volatility_bias == "short_vol":
                if tags & {"income", "short-vol", "credit-spread", "range-bound"}:
                    signal_fit += 12.0
                if tags & {"volatility", "backspread", "event-play"}:
                    signal_fit -= 8.0

            signal_fit = round(max(signal_fit, 0.0), 1)
            total_score = round((base_quant_score * 0.4) + (signal_fit * 0.6), 1)

            scored.append({
                "strategy_id": template.id,
                "strategy_name": template.name,
                "category": template.category.value,
                "score": total_score,
                "signal_score": signal_fit,
                "quant_score": base_quant_score,
                "max_profit": round(max_profit),
                "max_loss": round(-max_loss),
                "net_premium": round(net_premium),
                "pop_estimate": round(pop * 100, 1),
                "risk_reward": round(rr, 2),
                "delta": round(greeks.delta, 2),
                "theta": round(greeks.theta, 2),
                "vega": round(greeks.vega, 2),
                "iv_avg": round(greeks.iv_avg * 100, 1),
                "description": template.primary_view,
                "signal_rationale": signal_rationale,
                "signal_direction": signal_direction,
                "signal_vol_bias": volatility_bias,
            })
        except Exception:
            continue

    # Sort by score descending, return top 5
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "picks": scored[:5],
        "underlying": underlying,
        "spot": spot,
        "expiry": expiry,
        "total_scored": len(scored),
        "signals": signal_profile,
    }


# ──────────────────────────────────────────────────────────────
# Fyers Auth (API-based fallback)
# ──────────────────────────────────────────────────────────────

@app.get("/api/fyers/login_url")
def fyers_login_url():
    return {"url": fyers_client.get_login_url()}


@app.post("/api/fyers/verify")
def fyers_verify(auth_code: str):
    token = fyers_client.generate_access_token(auth_code)
    if token:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to authenticate")


# ──────────────────────────────────────────────────────────────
# Static Frontend
# ──────────────────────────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
