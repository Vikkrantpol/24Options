import React, { useState } from 'react';
import axios from 'axios';

const API = '/api';

interface StrikeCombo {
    strikes: Array<{ side: string; right: string; strike: number; premium: number }>;
    legs: any[];
    score: number;
    pop: number;
    max_profit: number;
    max_loss: number;
    capital_required: number;
    pct_return: number;
    theta_daily: number;
    delta_net: number;
    breakevens: number[];
    be_pct: number[];
    net_premium: number;
}

interface Props {
    templateId: number | null;
    underlying: string;
    spotPrice: number;
    expiry: string;
    lotSize: number;
    dte: number;
    onApply: (legs: any[]) => void;
}

export const StrikeOptimizer: React.FC<Props> = ({
    templateId, underlying, spotPrice, expiry, lotSize, dte, onApply
}) => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [combos, setCombos] = useState<StrikeCombo[]>([]);
    const [stratName, setStratName] = useState('');
    const [error, setError] = useState('');

    const optimize = async () => {
        if (!templateId) return;
        setLoading(true);
        setError('');
        setCombos([]);
        try {
            const res = await axios.post(`${API}/pricing/optimize-strikes`, {
                template_id: templateId,
                underlying,
                spot_price: spotPrice,
                expiry,
                lot_size: lotSize,
                dte,
                top_n: 3,
            });
            setCombos(res.data.combos || []);
            setStratName(res.data.template || '');
            setOpen(true);
        } catch (e) {
            setError('Optimizer failed. Ensure strategy is selected & chain loaded.');
        } finally {
            setLoading(false);
        }
    };

    const scoreColor = (score: number) =>
        score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : '#ff1744';

    return (
        <>
            <button
                onClick={optimize}
                disabled={!templateId || loading}
                style={{
                    background: 'transparent',
                    border: '1px solid var(--cyan)',
                    color: 'var(--cyan)',
                    padding: '4px 10px',
                    borderRadius: '3px',
                    fontSize: '11px',
                    cursor: templateId ? 'pointer' : 'not-allowed',
                    opacity: templateId ? 1 : 0.4,
                    fontFamily: "'JetBrains Mono', monospace",
                    display: 'flex', alignItems: 'center', gap: '5px',
                    transition: 'all 0.2s',
                }}
            >
                {loading ? '⟳ Scanning...' : '⚡ Optimize Strikes'}
            </button>

            {error && (
                <span style={{ fontSize: '10px', color: '#ff5555' }}>{error}</span>
            )}

            {/* Modal Overlay */}
            {open && (
                <div
                    onClick={() => setOpen(false)}
                    style={{
                        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
                        zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                >
                    <div
                        onClick={e => e.stopPropagation()}
                        style={{
                            background: '#0a0f12',
                            border: '1px solid rgba(0,230,118,0.3)',
                            borderRadius: '6px',
                            width: '720px',
                            maxWidth: '95vw',
                            maxHeight: '80vh',
                            overflowY: 'auto',
                            fontFamily: "'JetBrains Mono', monospace",
                        }}
                    >
                        {/* Header */}
                        <div style={{
                            padding: '12px 16px',
                            borderBottom: '1px solid rgba(255,255,255,0.06)',
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        }}>
                            <span style={{ color: 'var(--green)', fontWeight: 700, fontSize: '12px' }}>
                                ⚡ OPTIMAL STRIKES — {stratName.toUpperCase()}
                            </span>
                            <button onClick={() => setOpen(false)} style={{
                                background: 'none', border: 'none', color: 'var(--muted)',
                                cursor: 'pointer', fontSize: '16px',
                            }}>✕</button>
                        </div>

                        <div style={{ padding: '12px 16px' }}>
                            <p style={{ fontSize: '10px', color: 'var(--muted)', marginBottom: '12px' }}>
                                Ranked by composite score: 40% PoP · 25% Theta efficiency · 20% Risk-Reward · 15% Delta neutrality
                            </p>

                            {combos.length === 0 ? (
                                <p style={{ color: 'var(--muted)', fontSize: '12px', padding: '20px', textAlign: 'center' }}>
                                    No optimal combos found. Try loading live chain data.
                                </p>
                            ) : combos.map((combo, i) => (
                                <div key={i} style={{
                                    background: 'rgba(255,255,255,0.02)',
                                    border: `1px solid rgba(0,230,118,${0.25 - i * 0.07})`,
                                    borderRadius: '4px', marginBottom: '10px', padding: '12px',
                                }}>
                                    {/* Rank + Score header */}
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                        <span style={{ color: 'var(--green)', fontSize: '11px', fontWeight: 700 }}>
                                            #{i + 1} {i === 0 ? '👑 BEST' : i === 1 ? '⭐ 2ND' : '🎯 3RD'}
                                        </span>
                                        <span style={{ color: scoreColor(combo.score), fontSize: '11px', fontWeight: 700 }}>
                                            Score: {combo.score}
                                        </span>
                                    </div>

                                    {/* Strike table */}
                                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', marginBottom: '10px' }}>
                                        <thead>
                                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                                                {['Side', 'Right', 'Strike', 'Premium'].map(h => (
                                                    <th key={h} style={{ color: 'var(--muted)', padding: '4px 8px', textAlign: 'left', fontWeight: 400 }}>{h}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {combo.strikes.map((s, j) => (
                                                <tr key={j}>
                                                    <td style={{ padding: '4px 8px', color: s.side === 'BUY' ? 'var(--green)' : '#ff1744', fontWeight: 700 }}>{s.side}</td>
                                                    <td style={{ padding: '4px 8px', color: 'var(--cyan)' }}>{s.right}</td>
                                                    <td style={{ padding: '4px 8px' }}>{s.strike.toLocaleString()}</td>
                                                    <td style={{ padding: '4px 8px', color: 'var(--amber)' }}>₹{s.premium}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>

                                    {/* Metrics row */}
                                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', fontSize: '11px', marginBottom: '10px' }}>
                                        {[
                                            { l: 'PoP', v: `${combo.pop}%`, c: combo.pop >= 60 ? 'var(--green)' : 'var(--amber)' },
                                            { l: 'Capital', v: `₹${Math.round(combo.capital_required).toLocaleString()}`, c: 'var(--cyan)' },
                                            { l: '% Return', v: `${combo.pct_return}%`, c: combo.pct_return >= 0 ? 'var(--green)' : '#ff1744' },
                                            { l: 'Max Profit', v: `₹${Math.round(combo.max_profit).toLocaleString()}`, c: 'var(--green)' },
                                            { l: 'Max Loss', v: `₹${Math.round(Math.abs(combo.max_loss)).toLocaleString()}`, c: '#ff1744' },
                                            { l: 'θ/day', v: `₹${combo.theta_daily.toFixed(0)}`, c: combo.theta_daily >= 0 ? 'var(--green)' : '#ff1744' },
                                            { l: 'Δ Net', v: combo.delta_net.toFixed(3), c: 'var(--amber)' },
                                            { l: 'BE Dist', v: combo.be_pct.map(b => `${b > 0 ? '+' : ''}${b}%`).join(' | '), c: 'var(--amber)' },
                                        ].map(({ l, v, c }) => (
                                            <span key={l} style={{ color: 'var(--muted)' }}>
                                                {l}: <span style={{ color: c, fontWeight: 700 }}>{v}</span>
                                            </span>
                                        ))}
                                    </div>

                                    <button
                                        onClick={() => { onApply(combo.legs); setOpen(false); }}
                                        style={{
                                            width: '100%',
                                            background: 'rgba(0,230,118,0.08)',
                                            border: '1px solid rgba(0,230,118,0.4)',
                                            color: 'var(--green)',
                                            padding: '6px',
                                            borderRadius: '3px',
                                            cursor: 'pointer',
                                            fontSize: '11px',
                                            fontFamily: "'JetBrains Mono', monospace",
                                            fontWeight: 700,
                                        }}
                                    >
                                        ✓ USE THIS COMBINATION
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};
