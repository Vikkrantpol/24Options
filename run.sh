#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 24 Options Strategies Platform — Production Launcher
# ══════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FORCE_FYERS_REAUTH="${FORCE_FYERS_REAUTH:-0}"
if [ "${1:-}" = "--reauth" ]; then
    FORCE_FYERS_REAUTH="1"
fi

if [ -t 1 ] && [ -n "${TERM:-}" ]; then
    clear || true
fi
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │                                                         │"
echo "  │   ██████╗ ██╗  ██╗     ██████╗ ██████╗ ████████╗ ██████╗│"
echo "  │   ╚════██╗██║  ██║    ██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝│"
echo "  │    █████╔╝███████║    ██║   ██║██████╔╝   ██║   ╚█████╗ │"
echo "  │   ██╔═══╝ ╚════██║    ██║   ██║██╔═══╝    ██║    ╚═══██╗│"
echo "  │   ███████╗     ██║    ╚██████╔╝██║        ██║   ██████╔╝│"
echo "  │   ╚══════╝     ╚═╝     ╚═════╝ ╚═╝        ╚═╝   ╚═════╝ │"
echo "  │                                                         │"
echo "  │            OPTIONS STRATEGY STUDIO v2.0                 │"
echo "  │          Professional Trading Platform                  │"
echo -e "  │          \033[38;5;208mBuild by Vikkrant\033[0m                              │"
echo "  └─────────────────────────────────────────────────────────┘"
echo ""

# 1. Python virtual environment
echo "  ▶ Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "    ✓ Created virtual environment"
fi
source venv/bin/activate

# 2. Backend dependencies
echo "  ▶ Installing backend dependencies..."
pip install -q -r backend/requirements.txt 2>/dev/null
echo "    ✓ Backend ready"

# 3. Frontend dependencies + build
echo "  ▶ Building frontend..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm install --silent 2>/dev/null
fi
npx vite build 2>/dev/null
cd ..
echo "    ✓ Frontend built"

# 4. Create data directory
mkdir -p data exports

# 5. Fyers Broker Authentication
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BROKER CONNECTION"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FYERS_APP_ID="$(grep '^FYERS_APP_ID=' .env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '[:space:]')"
FYERS_SECRET_KEY="$(grep '^FYERS_SECRET_KEY=' .env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '[:space:]')"

if [ ! -f .env ] || [ -z "$FYERS_APP_ID" ] || [ -z "$FYERS_SECRET_KEY" ] || [[ "$FYERS_APP_ID" == your* ]] || [[ "$FYERS_SECRET_KEY" == your* ]]; then
    echo ""
    echo "  ⚠  Fyers broker credentials not configured in .env"
    echo "  ⚠  Running in PAPER TRADING mode with mock data"
    echo ""
    echo "  To enable live trading, add your credentials to .env:"
    echo "    FYERS_APP_ID=your_app_id"
    echo "    FYERS_SECRET_KEY=your_secret_key"
    echo ""
else
    echo ""
    if [ "$FORCE_FYERS_REAUTH" = "1" ]; then
        echo "  ⚠  Forced broker re-auth requested (--reauth)."
    fi

    if [ -t 0 ] && [ -r /dev/tty ]; then
        AUTH_BOOTSTRAP_CMD=(FORCE_FYERS_REAUTH="$FORCE_FYERS_REAUTH" ./venv/bin/python -m backend.auth_bootstrap)
        if env "${AUTH_BOOTSTRAP_CMD[@]}" < /dev/tty
        then
            echo "  ✓ Live data enabled."
        else
            echo "  ⚠  Running in PAPER mode."
        fi
    elif FORCE_FYERS_REAUTH="$FORCE_FYERS_REAUTH" ./venv/bin/python -m backend.auth_bootstrap
    then
        echo "  ✓ Live data enabled."
    else
        echo "  ⚠  Running in PAPER mode."
    fi
    echo ""
fi

# 6. Start the server
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Server starting at http://localhost:8000"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  📊 Strategy Studio    │ http://localhost:8000"
echo "  🤖 AI Copilot (M2.5)  │ Minimax with Thinking"
echo "  📈 24 Strategies      │ Build, Analyze, Deploy"
echo "  💰 Paper Trading      │ Risk-free simulation"
echo ""

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
