"""
Canonical catalog of all 24 options strategies.
Categorized into: Bullish, Bearish, Neutral, Hedge.
The AI-picked "Best for This Week" is computed dynamically.
"""

from .models import (
    StrategyTemplate, LegTemplate, StrategyCategory, PayoffType,
    Side, OptionRight,
)


def get_all_strategies() -> list[StrategyTemplate]:
    """Returns all 24 canonical options strategies."""
    return list(STRATEGY_CATALOG.values())


def get_strategy_by_id(strategy_id: int) -> StrategyTemplate | None:
    return STRATEGY_CATALOG.get(strategy_id)


def get_strategies_by_category(category: StrategyCategory) -> list[StrategyTemplate]:
    return [s for s in STRATEGY_CATALOG.values() if s.category == category]


# ──────────────────────────────────────────────────────────────
# STRATEGY CATALOG — Remapped to Bullish / Bearish / Neutral / Hedge
# ──────────────────────────────────────────────────────────────

STRATEGY_CATALOG: dict[int, StrategyTemplate] = {

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # BULLISH — Strategies that profit from upside
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1: StrategyTemplate(
        id=1, name="Long Call", category=StrategyCategory.BULLISH,
        subcategory="Single Leg",
        description="Buy a call to profit from upside with limited downside risk.",
        primary_view="Bullish with limited risk, levered upside",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="Premium paid", max_reward="Unlimited",
        breakeven_formula="Strike + Premium paid",
        tags=["bullish", "leverage", "simple"],
        legs=[LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=1)],
    ),

    4: StrategyTemplate(
        id=4, name="Short Put (Cash-Secured)", category=StrategyCategory.BULLISH,
        subcategory="Single Leg",
        description="Sell a put to collect premium; mildly bullish or neutral.",
        primary_view="Moderately bullish / neutral; generate income",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Strike × Lot − Premium", max_reward="Premium received",
        breakeven_formula="Strike − Premium received",
        tags=["bullish", "income", "cash-secured"],
        legs=[LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=0, qty_multiplier=1)],
    ),

    8: StrategyTemplate(
        id=8, name="Bull Call Spread", category=StrategyCategory.BULLISH,
        subcategory="Vertical Spread",
        description="Buy call at lower strike, sell call at higher strike. Defined risk bullish.",
        primary_view="Moderately bullish; defined risk and profit",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Net premium paid", max_reward="(Strike B − A) − Net premium",
        breakeven_formula="Strike A + Net premium paid",
        tags=["bullish", "debit-spread", "defined-risk"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    10: StrategyTemplate(
        id=10, name="Bull Put Spread (Credit)", category=StrategyCategory.BULLISH,
        subcategory="Vertical Spread",
        description="Sell put higher, buy put lower. Bullish credit spread.",
        primary_view="Moderately bullish; high probability income",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="(Strike B − A) − Premium", max_reward="Net premium received",
        breakeven_formula="Strike B − Net premium",
        tags=["bullish", "credit-spread", "defined-risk", "income"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
        ],
    ),

    21: StrategyTemplate(
        id=21, name="Ratio Call Spread", category=StrategyCategory.BULLISH,
        subcategory="Ratio Spread",
        description="Buy 1 call A, sell 2 calls B. Mildly bullish, cheap entry.",
        primary_view="Mildly bullish with cheap/credit entry; tail risk on large rally",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Unlimited (above B)", max_reward="(B − A) − Net premium",
        breakeven_formula="A + Net premium (lower) & 2B − A − Net premium (upper)",
        tags=["bullish", "ratio", "cheap-entry"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=2),
        ],
    ),

    23: StrategyTemplate(
        id=23, name="Call Backspread", category=StrategyCategory.BULLISH,
        subcategory="Backspread",
        description="Sell 1 call A, buy 2 calls B. Strongly bullish + long vol.",
        primary_view="Strongly bullish + long volatility; unlimited upside",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="(B − A) − Net premium", max_reward="Unlimited",
        breakeven_formula="B + Max risk",
        tags=["bullish", "volatility", "backspread"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=1, qty_multiplier=2),
        ],
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # BEARISH — Strategies that profit from downside
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    2: StrategyTemplate(
        id=2, name="Short Call (Naked)", category=StrategyCategory.BEARISH,
        subcategory="Single Leg",
        description="Sell a call to collect premium; bearish or neutral view.",
        primary_view="Moderately to strongly bearish; premium income",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Unlimited", max_reward="Premium received",
        breakeven_formula="Strike + Premium received",
        tags=["bearish", "income", "naked", "high-risk"],
        legs=[LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=1)],
    ),

    3: StrategyTemplate(
        id=3, name="Long Put", category=StrategyCategory.BEARISH,
        subcategory="Single Leg",
        description="Buy a put to profit from downside with limited risk.",
        primary_view="Bearish with limited risk; levered downside",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="Premium paid", max_reward="Strike − Premium",
        breakeven_formula="Strike − Premium paid",
        tags=["bearish", "leverage", "simple"],
        legs=[LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1)],
    ),

    9: StrategyTemplate(
        id=9, name="Bear Call Spread (Credit)", category=StrategyCategory.BEARISH,
        subcategory="Vertical Spread",
        description="Sell call lower, buy call higher. Bearish credit spread.",
        primary_view="Moderately bearish; collect credit with limited risk",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="(Strike B − A) − Premium", max_reward="Net premium received",
        breakeven_formula="Strike A + Net premium",
        tags=["bearish", "credit-spread", "defined-risk"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    11: StrategyTemplate(
        id=11, name="Bear Put Spread", category=StrategyCategory.BEARISH,
        subcategory="Vertical Spread",
        description="Buy put higher, sell put lower. Bearish debit spread.",
        primary_view="Moderately bearish; cheaper than outright long put",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Net premium paid", max_reward="(Strike B − A) − Premium",
        breakeven_formula="Strike B − Net premium",
        tags=["bearish", "debit-spread", "defined-risk"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
        ],
    ),

    22: StrategyTemplate(
        id=22, name="Ratio Put Spread", category=StrategyCategory.BEARISH,
        subcategory="Ratio Spread",
        description="Buy 1 put B, sell 2 puts A. Mildly bearish, cheap entry.",
        primary_view="Mildly bearish with cheap/credit entry",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Unlimited (below A)", max_reward="(B − A) − Premium",
        breakeven_formula="B − Premium (upper) & 2A − B + Premium (lower)",
        tags=["bearish", "ratio", "cheap-entry"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=-1, qty_multiplier=2),
        ],
    ),

    24: StrategyTemplate(
        id=24, name="Put Backspread", category=StrategyCategory.BEARISH,
        subcategory="Backspread",
        description="Sell 1 put B, buy 2 puts A. Strongly bearish + long vol.",
        primary_view="Strongly bearish + long volatility; profit on crash",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="(B − A) − Net premium", max_reward="Large on crash",
        breakeven_formula="A − Max risk",
        tags=["bearish", "volatility", "backspread"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=2),
        ],
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NEUTRAL — Range-bound / Volatility / Income
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    12: StrategyTemplate(
        id=12, name="Long Straddle", category=StrategyCategory.NEUTRAL,
        subcategory="Straddle",
        description="Buy call + put at ATM. Bet on big move, direction unknown.",
        primary_view="Long volatility; expect big move",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="Total premium paid", max_reward="Unlimited",
        breakeven_formula="Strike ± Total premium",
        tags=["volatility", "event-play", "earnings"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
        ],
    ),

    13: StrategyTemplate(
        id=13, name="Short Straddle", category=StrategyCategory.NEUTRAL,
        subcategory="Straddle",
        description="Sell call + put at ATM. Profit if price stays flat.",
        primary_view="Short volatility; expect price to pin",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Unlimited", max_reward="Total premium received",
        breakeven_formula="Strike ± Total premium",
        tags=["income", "theta", "short-vol", "high-risk"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
        ],
    ),

    14: StrategyTemplate(
        id=14, name="Long Strangle", category=StrategyCategory.NEUTRAL,
        subcategory="Strangle",
        description="Buy OTM put + OTM call. Cheaper straddle, needs bigger move.",
        primary_view="Cheaper long-vol; need larger move to profit",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="Total premium paid", max_reward="Unlimited",
        breakeven_formula="Put strike − Premium OR Call strike + Premium",
        tags=["volatility", "event-play"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    15: StrategyTemplate(
        id=15, name="Short Strangle", category=StrategyCategory.NEUTRAL,
        subcategory="Strangle",
        description="Sell OTM put + OTM call. Income from range-bound.",
        primary_view="Income from range-bound markets",
        payoff_type=PayoffType.UNLIMITED_RISK_LIMITED_REWARD,
        max_risk="Unlimited", max_reward="Total premium received",
        breakeven_formula="Put strike − Premium OR Call strike + Premium",
        tags=["income", "theta", "short-vol", "range-bound"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    16: StrategyTemplate(
        id=16, name="Long Call Butterfly", category=StrategyCategory.NEUTRAL,
        subcategory="Butterfly",
        description="Buy 1 A, sell 2 B, buy 1 C. Pin near middle, low cost.",
        primary_view="Market expected to pin near middle strike",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Net premium paid", max_reward="(B − A) − Net premium",
        breakeven_formula="A + Premium OR C − Premium",
        tags=["neutral", "pinning", "low-cost"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=2),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    17: StrategyTemplate(
        id=17, name="Short Butterfly", category=StrategyCategory.NEUTRAL,
        subcategory="Butterfly",
        description="Short 1 A, long 2 B, short 1 C. Bet price moves away.",
        primary_view="Bet on price moving away from middle",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="(B − A) − Net premium", max_reward="Net premium received",
        breakeven_formula="A + Premium OR C − Premium",
        tags=["volatility", "movement"],
        legs=[
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=2),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    18: StrategyTemplate(
        id=18, name="Iron Butterfly", category=StrategyCategory.NEUTRAL,
        subcategory="Butterfly",
        description="Short straddle + long wings. Safer short straddle.",
        primary_view="Range-bound income with defined risk wings",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Wing width − Net premium", max_reward="Net premium received",
        breakeven_formula="B ± Net premium",
        tags=["income", "defined-risk", "neutral"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=0, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    19: StrategyTemplate(
        id=19, name="Iron Condor", category=StrategyCategory.NEUTRAL,
        subcategory="Condor",
        description="Short put B + short call C + long wings. Classic neutral income.",
        primary_view="Classic neutral / low-volatility income trade",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Wing width − Net premium", max_reward="Net premium received",
        breakeven_formula="B − Premium OR C + Premium",
        tags=["income", "defined-risk", "neutral", "popular"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-2, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=2, qty_multiplier=1),
        ],
    ),

    20: StrategyTemplate(
        id=20, name="Long Call Condor", category=StrategyCategory.NEUTRAL,
        subcategory="Condor",
        description="Long 1 A, short 1 B, short 1 C, long 1 D. Range-bound.",
        primary_view="Range-bound view using only calls",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Net premium paid", max_reward="(B − A) − Premium",
        breakeven_formula="A + Premium OR D − Premium",
        tags=["neutral", "defined-risk", "range-bound"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=-2, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=2, qty_multiplier=1),
        ],
    ),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HEDGE — Stock + options protective combinations
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    5: StrategyTemplate(
        id=5, name="Covered Call", category=StrategyCategory.HEDGE,
        subcategory="Stock + Option",
        description="Long stock + short call. Income on existing stock.",
        primary_view="Mildly bullish/neutral; capped upside income",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Stock price − Premium", max_reward="(Strike − Stock) + Premium",
        breakeven_formula="Stock price − Premium received",
        tags=["income", "stock-required", "conservative"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.CE, strike_offset=0, qty_multiplier=1, is_stock_leg=True),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),

    6: StrategyTemplate(
        id=6, name="Protective Put", category=StrategyCategory.HEDGE,
        subcategory="Stock + Option",
        description="Long stock + long put. Portfolio insurance with defined downside.",
        primary_view="Long-term bullish with defined downside hedge",
        payoff_type=PayoffType.LIMITED_RISK_UNLIMITED_REWARD,
        max_risk="(Stock − Strike) + Premium", max_reward="Unlimited",
        breakeven_formula="Stock price + Premium paid",
        tags=["hedge", "insurance", "stock-required"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1, is_stock_leg=True),
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
        ],
    ),

    7: StrategyTemplate(
        id=7, name="Collar", category=StrategyCategory.HEDGE,
        subcategory="Stock + Options",
        description="Long stock + long put + short call. Insurance + income.",
        primary_view="Cap downside and upside around a range",
        payoff_type=PayoffType.LIMITED_RISK_LIMITED_REWARD,
        max_risk="Stock − Put strike + Net premium", max_reward="Call strike − Stock + Net premium",
        breakeven_formula="Stock price + Net premium paid",
        tags=["hedge", "income", "conservative", "stock-required"],
        legs=[
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=0, qty_multiplier=1, is_stock_leg=True),
            LegTemplate(side=Side.BUY, right=OptionRight.PE, strike_offset=-1, qty_multiplier=1),
            LegTemplate(side=Side.SELL, right=OptionRight.CE, strike_offset=1, qty_multiplier=1),
        ],
    ),
}
