import React from 'react';
import type { GreeksSummary } from '../types';

interface Props {
    greeks: GreeksSummary | null;
}

export const GreeksPanel: React.FC<Props> = ({ greeks }) => {
    if (!greeks) return null;

    const items = [
        { label: 'Δ Delta', value: greeks.delta, fmt: (v: number) => v.toFixed(2) },
        { label: 'Γ Gamma', value: greeks.gamma, fmt: (v: number) => v.toFixed(4) },
        { label: 'ν Vega', value: greeks.vega, fmt: (v: number) => v.toFixed(2) },
        { label: 'Θ Theta', value: greeks.theta, fmt: (v: number) => v.toFixed(2) },
        { label: 'IV Avg', value: greeks.iv_avg * 100, fmt: (v: number) => v.toFixed(1) + '%' },
    ];

    const cls = (v: number) => Math.abs(v) < 0.001 ? 'val--zero' : v > 0 ? 'val--pos' : 'val--neg';

    return (
        <div className="panel">
            <div className="panel__header">
                <span className="panel__title">▸ GREEKS</span>
            </div>
            <div className="panel__body">
                <div className="greeks-grid">
                    {items.map(it => (
                        <div key={it.label} className="greek-cell">
                            <div className="greek-cell__label">{it.label}</div>
                            <div className={`greek-cell__val ${cls(it.value)}`}>
                                {it.value > 0 && it.label !== 'IV Avg' ? '+' : ''}{it.fmt(it.value)}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};
