import React, { useState } from 'react';
import type { ChainRow, ConcreteLeg } from '../types';

interface Props {
    chain: ChainRow[];
    spot: number;
    expiry: string;
    lotSize: number;
    lotMultiplier?: number;
    onAddLeg: (leg: ConcreteLeg) => void;
}

export const OptionChainViewer: React.FC<Props> = ({ chain, spot, expiry, lotSize, lotMultiplier = 1, onAddLeg }) => {
    const [strikeWindow, setStrikeWindow] = useState(12);

    const handleAdd = (strike: number, right: 'CE' | 'PE', side: 'BUY' | 'SELL') => {
        const row = chain.find(c => c.strike === strike);
        if (!row) return;
        const d = right === 'CE' ? row.CE : row.PE;
        const entryPrice = d.ltp && d.ltp > 0 ? d.ltp : d.premium;
        onAddLeg({
            side, right, strike,
            premium: entryPrice,
            qty: Math.max(lotSize, 1) * Math.max(lotMultiplier, 1),
            expiry,
            iv: d.iv / 100,
            delta: d.delta,
            gamma: d.gamma,
            vega: d.vega,
            theta: d.theta,
        });
    };

    const atmIndex = chain.reduce((bestIndex, row, index) => {
        const bestDiff = Math.abs(chain[bestIndex].strike - spot);
        const nextDiff = Math.abs(row.strike - spot);
        return nextDiff < bestDiff ? index : bestIndex;
    }, 0);
    const start = Math.max(0, atmIndex - strikeWindow);
    const end = Math.min(chain.length, atmIndex + strikeWindow + 1);
    const visible = chain.slice(start, end);
    const strikeStep = chain.length >= 2 ? Math.abs(chain[1].strike - chain[0].strike) : 100;
    const visibleRange = visible.length > 0
        ? `${visible[0].strike.toLocaleString()} - ${visible[visible.length - 1].strike.toLocaleString()}`
        : 'No strikes';

    const fmtCompact = (value: number) => {
        if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
        if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
        return value.toFixed(0);
    };

    const fmtDelta = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}`;

    return (
        <div className="panel chain-panel">
            <div className="panel__header chain-panel__header">
                <div className="chain-panel__title">
                    <span className="panel__title">▸ OPTION CHAIN</span>
                    <span className="chain-panel__meta">
                        Spot ₹{spot.toLocaleString()} · {expiry || 'No expiry'} · Lot {lotSize}{lotMultiplier > 1 ? ` x ${lotMultiplier}` : ''}
                    </span>
                </div>
                <div className="chain-toolbar">
                    <span className="chain-toolbar__label">ATM Window</span>
                    {[8, 12, 20].map(size => (
                        <button
                            key={size}
                            type="button"
                            className={`chain-toolbar__btn ${strikeWindow === size ? 'chain-toolbar__btn--active' : ''}`}
                            onClick={() => setStrikeWindow(size)}
                        >
                            +/- {size}
                        </button>
                    ))}
                </div>
            </div>
            <div className="chain-overview">
                <span>Visible strikes: {visible.length}</span>
                <span>Range: {visibleRange}</span>
                <span>Action size: {(Math.max(lotSize, 1) * Math.max(lotMultiplier, 1)).toLocaleString()}</span>
            </div>
            <div className="chain-wrap">
                <table className="chain-tbl">
                    <thead>
                        <tr>
                            <th>CE OI / VOL</th>
                            <th>IV</th>
                            <th>LTP / Δ</th>
                            <th>CE</th>
                            <th style={{ background: 'rgba(0,188,212,0.06)' }}>STRIKE</th>
                            <th>PE</th>
                            <th>LTP / Δ</th>
                            <th>IV</th>
                            <th>PE OI / VOL</th>
                        </tr>
                    </thead>
                    <tbody>
                        {visible.map(row => {
                            const isATM = Math.abs(row.strike - spot) <= strikeStep / 2;
                            const ceLtp = row.CE.ltp && row.CE.ltp > 0 ? row.CE.ltp : row.CE.premium;
                            const peLtp = row.PE.ltp && row.PE.ltp > 0 ? row.PE.ltp : row.PE.premium;
                            return (
                                <tr key={row.strike} className={isATM ? 'atm' : ''}>
                                    <td className="chain-flow-cell">
                                        <strong>OI {fmtCompact(row.CE.oi)}</strong>
                                        <span>Vol {fmtCompact(row.CE.volume)}</span>
                                    </td>
                                    <td style={{ color: 'var(--text-2)' }}>{row.CE.iv.toFixed(1)}%</td>
                                    <td className="chain-price-cell">
                                        <strong>{ceLtp.toFixed(1)}</strong>
                                        <span className={row.CE.delta >= 0 ? 'val--pos' : 'val--neg'}>
                                            Δ {fmtDelta(row.CE.delta)}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="chain-actions">
                                            <button type="button" className="chain-btn chain-btn--b" onClick={() => handleAdd(row.strike, 'CE', 'BUY')}>BUY</button>
                                            <button type="button" className="chain-btn chain-btn--s" onClick={() => handleAdd(row.strike, 'CE', 'SELL')}>SELL</button>
                                        </div>
                                    </td>
                                    <td className="col-strike">{row.strike}</td>
                                    <td>
                                        <div className="chain-actions">
                                            <button type="button" className="chain-btn chain-btn--b" onClick={() => handleAdd(row.strike, 'PE', 'BUY')}>BUY</button>
                                            <button type="button" className="chain-btn chain-btn--s" onClick={() => handleAdd(row.strike, 'PE', 'SELL')}>SELL</button>
                                        </div>
                                    </td>
                                    <td className="chain-price-cell">
                                        <strong>{peLtp.toFixed(1)}</strong>
                                        <span className={row.PE.delta >= 0 ? 'val--pos' : 'val--neg'}>
                                            Δ {fmtDelta(row.PE.delta)}
                                        </span>
                                    </td>
                                    <td style={{ color: 'var(--text-2)' }}>{row.PE.iv.toFixed(1)}%</td>
                                    <td className="chain-flow-cell">
                                        <strong>OI {fmtCompact(row.PE.oi)}</strong>
                                        <span>Vol {fmtCompact(row.PE.volume)}</span>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
