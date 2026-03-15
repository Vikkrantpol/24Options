# Project Overview & Architecture
**Date**: March 3, 2026

## Objective
The 24 Options Strategies Platform is a sophisticated algorithmic and paper-trading workspace built on top of the Fyers API v3. Today, we undertook a massive upgrade to shift the platform from a simple options builder to a professional-grade Quantitative Trading suite.

## Tech Stack
- **Frontend**: React, TypeScript, Recharts (for dynamic payoff graphing), Axios, CSS Variables for seamless Terminal-grade styling.
- **Backend**: FastAPI, Python 3, Pydantic (data models), SQLite (persistence).
- **External Services**: MiniMax M2.5 (AI Copilot via OpenRouter), Fyers API v3 (Live options data, Greeks, order routing).

## Key Accomplishments Today
We rebuilt major segments of the application across five distinct phases:
1. **Futures Native Support**: Extending the strategy builder beyond merely Calls (CE) and Puts (PE).
2. **AI Quant Personality**: Forcing the AI to analyze live Greek loopholes and adopt an elite algorithmic trader persona.
3. **SQLite Persistence**: Migrating the P&L monitoring engine from volatile RAM to disk storage.
4. **UI Expansions**: Constructing drag-to-resize sidebars and resolving graphical contrast constraints.
5. **Backend Data Normalization**: Securing the Fyers API symbol routing for BankNifty.
