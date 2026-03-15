# UI/UX Refinements & Bug Fixes
**Date**: March 3, 2026

## Major Polish Objectives
We performed heavy tactical adjustments to ensure the workspace operated transparently and flawlessly.

### 1. Collapsible & Resizable Sidebars
The user requested full control over the AI Copilot spatial footprint.
- **Logic**: Implemented `startResizingRight` tracking `MouseEvent.clientX` deltas.
- **Display**: Bound the calculated `rightWidth` straight to the inline styles of `.right-panel`, creating a smooth, un-laggy drag handle (`.resizer-left`), scalable between 250px and 800px.

### 2. BankNifty Symbol Fyers Bug
**Bug**: The Payoff Chart was snapping to `Spot: 49,000` inside dummy data instead of the true BankNifty spot (~`59,800`).
**Root Cause**: The string formatter in `main.py` was forcibly attaching "50-INDEX" to the routed BankNifty HTTP body (`NSE:NSE:NIFTYBANK-INDEX50-INDEX`).
**Fix**: Spliced off the formatter, allowing the UI's verified symbol selector string to transmit cleanly to the Fyers API. 

### 3. Payoff Graphical Contrast
**Issue**: Dark theme opacity rendered the profit zone unreadable.
**Fix**: Increased the `stopOpacity` attribute on the Recharts `<linearGradient>` from `0.3` to `0.5`, multiplied the `strokeWidth` border thickness, and boldly formatted the Spot tooltip reference line.
