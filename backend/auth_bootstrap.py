"""
Run.sh authentication bootstrap helper.
Keeps stdin interactive (unlike heredoc-based Python invocation).
"""

from __future__ import annotations

import os
import sys

from .fyers_client import FyersAPIClient


def main() -> int:
    force_reauth = os.getenv("FORCE_FYERS_REAUTH", "0") == "1"
    client = FyersAPIClient()

    if client.ensure_live_session(force_reauth=force_reauth, interactive=True):
        print("  ✅ Broker live session verified.")
        return 0

    print("  ⚠  Broker authentication unavailable. Falling back to paper mode.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

