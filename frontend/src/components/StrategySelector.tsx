import React, { useState, useEffect } from 'react';
import axios from 'axios';
import type { StrategyTemplate } from '../types';

interface AIPick {
    strategy_id: number;
    strategy_name: string;
    score: number;
    signal_score?: number;
    quant_score?: number;
    pop_estimate: number;
    max_profit: number;
    max_loss: number;
    risk_reward: number;
    theta: number;
    description: string;
    signal_rationale?: string;
    signal_direction?: string;
    signal_vol_bias?: string;
}

interface SignalSnapshot {
    combined?: {
        direction?: string;
        volatility_bias?: string;
        confidence?: number;
        rationale?: string;
    };
    oi?: {
        put_call_ratio?: number;
        dominant_put_strike?: number | null;
        dominant_call_strike?: number | null;
    };
    recommended_strategy_ids?: number[];
}

interface BestPicksResponse {
    picks?: AIPick[];
    signals?: SignalSnapshot;
}

interface Props {
    strategies: StrategyTemplate[];
    selectedId: number | null;
    underlying: string;
    onSelect: (strategy: StrategyTemplate) => void;
}

const CATS = [
    { key: 'Bullish', color: '#00e676', icon: '▲' },
    { key: 'Bearish', color: '#ff1744', icon: '▼' },
    { key: 'Neutral', color: '#ffab00', icon: '◆' },
    { key: 'Hedge', color: '#00bcd4', icon: '◼' },
];

export const StrategySelector: React.FC<Props> = ({ strategies, selectedId, underlying, onSelect }) => {
    const [search, setSearch] = useState('');
    const [aiPicks, setAiPicks] = useState<AIPick[]>([]);
    const [signals, setSignals] = useState<SignalSnapshot | null>(null);
    const [loadingPicks, setLoadingPicks] = useState(true);

    // Fetch AI best picks on mount
    useEffect(() => {
        const fetchPicks = async () => {
            try {
                const sym = underlying.includes('BANK') ? 'BANKNIFTY' : 'NIFTY';
                const res = await axios.get<BestPicksResponse>(`/api/ai/best-picks?underlying=${encodeURIComponent(sym)}`);
                setAiPicks(res.data.picks || []);
                setSignals(res.data.signals || null);
            } catch {
                setAiPicks([]);
                setSignals(null);
            } finally {
                setLoadingPicks(false);
            }
        };
        setLoadingPicks(true);
        fetchPicks();
    }, [underlying]);

    const filtered = strategies.filter(s =>
        search === '' ||
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.id.toString() === search
    );

    const grouped = CATS.map(c => ({
        ...c,
        items: filtered.filter(s => s.category === c.key),
    })).filter(g => g.items.length > 0);
    const recommendedNames = (signals?.recommended_strategy_ids || [])
        .map(id => strategies.find(s => s.id === id))
        .filter((strategy): strategy is StrategyTemplate => Boolean(strategy))
        .slice(0, 3);
    const confidencePct = typeof signals?.combined?.confidence === 'number'
        ? `${(signals.combined.confidence * 100).toFixed(1)}%`
        : '--';

    return (
        <div className="strat-selector">
            <div className="strat-selector__header">
                <h3>▸ STRATEGIES [24]</h3>
            </div>
            <div className="strat-selector__search">
                <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="search..."
                />
            </div>
            {signals && (
                <div className="signal-readout">
                    <div className="signal-readout__head">
                        <span className="signal-readout__title">LIVE SIGNAL READOUT</span>
                        <span className={`signal-readout__badge signal-readout__badge--${signals.combined?.direction || 'neutral'}`}>
                            {signals.combined?.direction || 'neutral'}
                        </span>
                    </div>
                    <div className="signal-readout__grid">
                        <div className="signal-readout__cell">
                            <span className="signal-readout__label">Vol Bias</span>
                            <strong>{signals.combined?.volatility_bias || '--'}</strong>
                        </div>
                        <div className="signal-readout__cell">
                            <span className="signal-readout__label">Confidence</span>
                            <strong>{confidencePct}</strong>
                        </div>
                        <div className="signal-readout__cell">
                            <span className="signal-readout__label">PCR</span>
                            <strong>{typeof signals.oi?.put_call_ratio === 'number' ? signals.oi.put_call_ratio.toFixed(3) : '--'}</strong>
                        </div>
                        <div className="signal-readout__cell">
                            <span className="signal-readout__label">Support / Resist</span>
                            <strong>{signals.oi?.dominant_put_strike || '--'} / {signals.oi?.dominant_call_strike || '--'}</strong>
                        </div>
                    </div>
                    {recommendedNames.length > 0 && (
                        <div className="signal-readout__list">
                            {recommendedNames.map(strategy => (
                                <button
                                    key={`signal-${strategy.id}`}
                                    type="button"
                                    className="signal-readout__item"
                                    onClick={() => onSelect(strategy)}
                                >
                                    <span>#{strategy.id}</span>
                                    <span>{strategy.name}</span>
                                </button>
                            ))}
                        </div>
                    )}
                    {signals.combined?.rationale && (
                        <p className="signal-readout__note">{signals.combined.rationale}</p>
                    )}
                </div>
            )}
            <div className="strat-list">
                {/* ── AI BEST PICKS ──────────────── */}
                <div className="strat-cat">
                    <div className="strat-cat__label" style={{ color: '#b388ff' }}>
                        ★ AI BEST THIS WEEK
                    </div>
                    {loadingPicks ? (
                        <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--text-3)' }}>
                            {'>'} scoring strategies...
                        </div>
                    ) : aiPicks.length === 0 ? (
                        <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--text-3)' }}>
                            {'>'} no picks available
                        </div>
                    ) : (
                        aiPicks.map(pick => {
                            const strat = strategies.find(s => s.id === pick.strategy_id);
                            if (!strat) return null;
                            return (
                                <button
                                    key={`ai-${pick.strategy_id}`}
                                    className={`strat-item ${selectedId === pick.strategy_id ? 'strat-item--active' : ''}`}
                                    onClick={() => onSelect(strat)}
                                    title={`Score: ${pick.score} | Signal: ${pick.signal_score ?? '-'} | Quant: ${pick.quant_score ?? '-'} | PoP: ${pick.pop_estimate}% | R:R ${pick.risk_reward} | θ: ${pick.theta}${pick.signal_rationale ? ` | ${pick.signal_rationale}` : ''}`}
                                >
                                    <span className="strat-item__id" style={{ color: '#b388ff' }}>★</span>
                                    <span style={{ flex: 1 }}>{pick.strategy_name}</span>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        {pick.signal_direction && (
                                            <span style={{ fontSize: 8, color: '#607080', textTransform: 'uppercase' }}>
                                                {pick.signal_direction}
                                            </span>
                                        )}
                                        <span style={{ fontSize: 9, color: '#b388ff', fontWeight: 700 }}>
                                            {pick.score.toFixed(0)}
                                        </span>
                                    </span>
                                </button>
                            );
                        })
                    )}
                </div>

                {/* ── REGULAR CATEGORIES ─────────── */}
                {grouped.map(grp => (
                    <div key={grp.key} className="strat-cat">
                        <div className="strat-cat__label" style={{ color: grp.color }}>
                            {grp.icon} {grp.key.toUpperCase()}
                        </div>
                        {grp.items.map(s => (
                            <button
                                key={s.id}
                                className={`strat-item ${selectedId === s.id ? 'strat-item--active' : ''}`}
                                onClick={() => onSelect(s)}
                            >
                                <span className="strat-item__id">#{s.id}</span>
                                {s.name}
                            </button>
                        ))}
                    </div>
                ))}
            </div>
        </div>
    );
};
