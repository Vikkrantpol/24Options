# Quant Engine + Active Strategy AI Guide
**Date:** March 4, 2026  
**Audience:** Trader / Operator using 24 Options Strategies Platform

## What Is New
- Quant controls are available in two places:
  - **Builder tab** via `QUANT ENGINE v1` panel
  - **Dedicated `Quant` tab** for full workflow use
- **Monitor tab** now includes `ACTIVE STRATEGY INTEL`:
  - quant decision scoring
  - execution planning
  - AI odds-boost adjustment suggestions
  - one-click leg loading into Builder
- Right-side AI panel now auto-switches context:
  - Builder mode: uses Builder legs
  - Monitor mode: uses selected active strategy legs

## How To Use (Step-by-Step)

### A) Build new strategy with quant engine
1. Go to `Builder`.
2. Open `QUANT ENGINE v1`.
3. Set profile:
   - risk mode
   - target delta / target vega
   - max slice lots
4. Click `REGIME` to inspect current market regime.
5. Click `ADAPTIVE PICK` to get recommended strategy and legs.
6. Click `LOAD LEGS`.
7. Validate with:
   - `SCORE CURRENT` (confidence + grade + stress quality)
   - `PLAN CURRENT` (execution readiness + slices + warnings)
8. Deploy to paper.

### B) Run quant workflow from dedicated Quant tab
1. Go to `Quant` tab.
2. Repeat profile + regime + adaptive + scoring workflow.
3. Use `OPTIMIZE` for hedge suggestions against portfolio Greek targets.
4. Use `ADJUSTMENTS` to generate defensive repair actions.
5. Use autopilot controls:
   - `APPROVE AUTO` (recommended: paper mode first)
   - `RUN NOW` for immediate cycle
   - `PAUSE` to stop
6. Watch recent journal events in panel output.

### C) Improve active strategy winning odds (Monitor mode)
1. Go to `Monitor`.
2. Select an active strategy card.
3. In `ACTIVE STRATEGY INTEL`:
   - `SCORE` for confidence grade and stress behavior
   - `EXEC PLAN` for liquidity/slicing feasibility
   - `AI ODDS BOOST` for adjustment plan from AI
4. If AI returns deploy JSON, click `LOAD AI ADJUSTMENT LEGS`.
5. This loads proposed legs into Builder for review and deployment.

## Use Cases
- **Daily opening scan:** detect regime + pull adaptive setup quickly.
- **Risk balancing session:** neutralize drifted delta/vega with optimizer hedges.
- **Distress management:** detect stressed active trades and apply adjustment actions.
- **Execution safety check:** verify if strategy is executable under liquidity constraints.
- **Semi-automated paper trading:** approved autopilot cycles with full journal trace.
- **Post-session review:** learning summary for event distribution and close outcomes.

## Best Use Cases (Highest Edge)
- **Best #1: Builder + Quant + AI combo**
  - Regime -> Adaptive Pick -> Score -> Execution Plan -> AI cross-check -> Paper deploy.
- **Best #2: Active strategy defense loop**
  - Monitor selected strategy -> Score -> AI Odds Boost -> Load adjustment legs -> Re-evaluate.
- **Best #3: Controlled automation**
  - Start autopilot in paper mode with conservative profile, then increase complexity only after stable journal outcomes.

## Recommended Operating Discipline
- Use paper mode first for all autopilot experiments.
- Orders are now **hard-blocked when market is not open** (CLOSED/PRE_OPEN/HOLIDAY/WEEKEND).
- Do not use live mode unless:
  - broker auth is stable
  - execution plan shows `READY`
  - stress outcomes are acceptable
  - risk limits in profile are strict
- Validate any AI-suggested adjustment with `SCORE CURRENT` before deployment.

## Quick Validation Checklist
- `Builder` panel shows regime/confidence and can load adaptive legs.
- `Quant` tab can run optimizer/adjustments/autopilot actions.
- `Monitor` selected strategy can run Score + Exec Plan + AI Odds Boost.
- AI Inject buttons load legs into Builder successfully.
