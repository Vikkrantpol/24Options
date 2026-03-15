# 24 Options — Strategy Studio

**AI-powered options strategy platform for NIFTY / BANKNIFTY.** Build, analyze, and deploy 24 pre-built strategies with automatic position sizing, risk calculation, and strike optimization.

---

## Why 24 Options?

- **24 pre-built options strategies** — Bullish, bearish, neutral, and hedge. From single legs (Long Call, Long Put) to spreads (Iron Condor, Straddles, Butterflies) and backspreads. Pick a template, resolve to live strikes, deploy in one click.
- **AI is at the core** — Used for **positions and recommendations**, not just chat. The AI scores all 24 strategies against live market data (Greeks, IV, expiry), suggests the best fit, and **calculates positions and risk automatically**. It can **improve probability of profit** by moving to the best strike prices (ATM/OTM selection, width tuning) so you get tradeable, deployable setups.
- **Paper or live** — Paper trading with full P&L and Greeks, or connect Fyers for live data and execution. Risk limits and portfolio-level checks are built in.

---

## Screenshots

*(Add your 5 screenshots below. Replace the placeholder image paths with your files, e.g. `docs/screenshot1.png`.)*

| Screenshot | Description |
|------------|-------------|
| 1 | *(Add screenshot 1 — e.g. Strategy Studio / option chain)* |
| 2 | *(Add screenshot 2 — e.g. AI Copilot / recommendations)* |
| 3 | *(Add screenshot 3 — e.g. 24 strategies list / payoff)* |
| 4 | *(Add screenshot 4 — e.g. Quant Engine / risk panel)* |
| 5 | *(Add screenshot 5 — e.g. Paper trading / positions)* |

<!--
Example after you add images:
![Strategy Studio](docs/screenshot1.png)
![AI Copilot](docs/screenshot2.png)
![24 Strategies](docs/screenshot3.png)
![Quant Engine](docs/screenshot4.png)
![Paper Trading](docs/screenshot5.png)
-->

---

## Quick start

**Requirements:** Python 3.10+, Node.js 18+

```bash
# Clone and run
git clone https://github.com/YOUR_USERNAME/24Options.git
cd 24Options
./run.sh
```

Then open **http://localhost:8000**. The launcher sets up the venv, installs backend/frontend deps, builds the UI, and starts the server. For live broker data, add Fyers credentials to `.env` (see `.env.example`).

---

## Features

- **24 canonical strategies** — Single legs, verticals, straddles/strangles, butterflies, iron condor, ratio and backspreads.
- **AI-driven recommendations** — Strategy scoring and strike selection from live option chain; natural-language “build me a bear put spread” → deployable legs.
- **Automatic risk & Greeks** — Per-strategy and portfolio Delta, Gamma, Theta, Vega; max loss/breakeven; risk manager with configurable limits.
- **Paper trading** — Simulated OMS with P&L, positions, and journaling.
- **Fyers integration** — OAuth, live option chain, multi-leg order placement (optional).

---

## Tech stack

- **Backend:** Python, FastAPI, SQLite (portfolio/quant DB), BSM pricing, Fyers API v3.
- **Frontend:** React, TypeScript, Vite, Recharts.
- **AI:** OpenRouter (e.g. Minimax M2.5) for copilot and strategy generation; signal/regime logic for “best strategy for this week”.

---

## Project layout

```
24Options/
├── backend/          # FastAPI app, pricing, AI engine, Fyers client, quant engine
├── frontend/         # React SPA (Strategy Studio, Option Chain, AI Copilot, Quant panel)
├── data/             # Local DBs, tokens, logs (gitignored)
├── run.sh            # One-command launcher
└── .env.example      # Copy to .env and add Fyers / OpenRouter keys
```

---

## License

MIT (or your chosen license).
