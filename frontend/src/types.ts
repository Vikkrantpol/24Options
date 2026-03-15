/* Shared types for the 24 Options Strategies Platform frontend */

export interface LegTemplate {
    side: 'BUY' | 'SELL';
    right: 'CE' | 'PE' | 'FUT';
    qty_multiplier: number;
    strike_offset: number;
    expiry_offset: number;
    is_stock_leg: boolean;
}

export interface StrategyTemplate {
    id: number;
    name: string;
    category: string;
    subcategory: string;
    legs: LegTemplate[];
    description: string;
    primary_view: string;
    payoff_type: string;
    max_risk: string;
    max_reward: string;
    breakeven_formula: string;
    tags: string[];
}

export interface ConcreteLeg {
    id?: string;
    side: 'BUY' | 'SELL';
    right: 'CE' | 'PE' | 'FUT';
    strike: number;
    premium: number;
    qty: number;
    expiry: string;
    iv?: number;
    delta?: number;
    gamma?: number;
    vega?: number;
    theta?: number;
}

export interface GreeksSummary {
    delta: number;
    gamma: number;
    vega: number;
    theta: number;
    rho: number;
    iv_avg: number;
}

export interface PayoffDataPoint {
    underlying_price: number;
    pnl: number;
}

export interface StrategyMetrics {
    max_profit: number;
    max_loss: number;
    breakevens: number[];
    net_premium: number;
}

export interface ChainRow {
    strike: number;
    CE: {
        ltp?: number;
        premium: number;
        iv: number;
        delta: number;
        gamma: number;
        theta: number;
        vega: number;
        oi: number;
        volume: number;
        bid?: number;
        ask?: number;
        symbol?: string;
        iv_source?: string;
        greeks_source?: string;
    };
    PE: {
        ltp?: number;
        premium: number;
        iv: number;
        delta: number;
        gamma: number;
        theta: number;
        vega: number;
        oi: number;
        volume: number;
        bid?: number;
        ask?: number;
        symbol?: string;
        iv_source?: string;
        greeks_source?: string;
    };
}

export interface ChainData {
    symbol: string;
    spot: number;
    expiry: string;
    expiries?: string[];
    strike_step: number;
    lot_size: number;
    chain: ChainRow[];
    source?: string;
    quote_feed?: 'live-stream' | 'live-poll' | 'mock';
    tick_count?: number;
    tick_age_ms?: number | null;
    last_tick_age_ms?: number | null;
    live_error?: string;
}

export interface AIMessage {
    role: 'user' | 'assistant';
    content: string;
}
