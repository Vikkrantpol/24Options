import React, { useMemo } from 'react';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, ReferenceLine,
} from 'recharts';
import type { PayoffDataPoint, StrategyMetrics } from '../types';

interface Props {
    data: PayoffDataPoint[];
    spotPrice: number;
    metrics: StrategyMetrics | null;
    strategyName: string;
}

export const PayoffChart: React.FC<Props> = ({ data, spotPrice, metrics, strategyName }) => {
    const gradientOffset = useMemo(() => {
        if (!data || data.length === 0) return 0;
        const pnls = data.map(d => d.pnl);
        const max = Math.max(...pnls);
        const min = Math.min(...pnls);
        if (max <= 0) return 0;
        if (min >= 0) return 1;
        return max / (max - min);
    }, [data]);

    if (!data || data.length === 0) {
        return (
            <div className="panel" style={{ height: '380px' }}>
                <div className="panel__header">
                    <span className="panel__title">▸ PAYOFF</span>
                </div>
                <div className="empty" style={{ height: '320px', justifyContent: 'center' }}>
                    <p>Select a strategy or build custom legs from the chain</p>
                </div>
            </div>
        );
    }

    return (
        <div className="panel">
            <div className="panel__header">
                <span className="panel__title">
                    ▸ PAYOFF {strategyName && `— ${strategyName}`}
                </span>
            </div>
            {metrics && (
                <div style={{ display: 'flex', gap: '16px', fontSize: '11px', padding: '2px 12px 6px', flexWrap: 'wrap' }}>
                    <span className="val--pos" style={{ fontWeight: 700 }}>
                        +₹{metrics.max_profit.toLocaleString()}
                    </span>
                    <span className="val--neg" style={{ fontWeight: 700 }}>
                        ₹{metrics.max_loss.toLocaleString()}
                    </span>
                    {metrics.breakevens.length > 0 && (
                        <span style={{ color: 'var(--amber)' }}>
                            BE: {metrics.breakevens.map(b => b.toLocaleString()).join(' | ')}
                        </span>
                    )}
                </div>
            )}
            <div style={{ height: '310px', padding: '4px 10px 10px' }}>
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data} margin={{ top: 30, right: 20, left: -10, bottom: 0 }}>
                        <defs>
                            <linearGradient id="pGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset={gradientOffset} stopColor="#00e676" stopOpacity={0.5} />
                                <stop offset={gradientOffset} stopColor="#ff1744" stopOpacity={0.5} />
                            </linearGradient>
                            <linearGradient id="sGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset={gradientOffset} stopColor="#00e676" stopOpacity={1} />
                                <stop offset={gradientOffset} stopColor="#ff1744" stopOpacity={1} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" vertical={false} />
                        <XAxis
                            dataKey="underlying_price"
                            stroke="rgba(255,255,255,0.1)"
                            tick={{ fontSize: 10, fill: '#3a4a5a', fontFamily: 'JetBrains Mono' }}
                            tickFormatter={v => Math.round(v).toString()}
                            type="number"
                            domain={['dataMin', 'dataMax']}
                        />
                        <YAxis
                            stroke="rgba(255,255,255,0.1)"
                            tick={{ fontSize: 10, fill: '#3a4a5a', fontFamily: 'JetBrains Mono' }}
                            tickFormatter={v => `₹${Math.round(v)}`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#0f1318',
                                border: '1px solid rgba(0,230,118,0.2)',
                                borderRadius: '4px',
                                fontSize: '11px',
                                fontFamily: "'JetBrains Mono', monospace",
                            }}
                            labelStyle={{ color: '#607080' }}
                            formatter={(value: number) => [
                                <span style={{ color: value >= 0 ? '#00e676' : '#ff1744', fontWeight: 700 }}>
                                    ₹{value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                </span>,
                                'P&L',
                            ]}
                            labelFormatter={label => `Spot: ₹${Math.round(label).toLocaleString()}`}
                        />
                        <ReferenceLine y={0} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
                        <ReferenceLine
                            x={spotPrice}
                            stroke="#00bcd4"
                            strokeWidth={2}
                            strokeDasharray="4 4"
                            label={{ value: `Spot: ₹${Math.round(spotPrice).toLocaleString()}`, fill: '#00bcd4', fontSize: 11, position: 'insideTopLeft', fontWeight: 600, offset: 6 }}
                        />
                        {metrics?.breakevens.map((be, i) => (
                            <ReferenceLine key={i} x={be} stroke="#ffab00" strokeDasharray="2 4" />
                        ))}
                        <Area
                            type="monotone"
                            dataKey="pnl"
                            stroke="url(#sGrad)"
                            fill="url(#pGrad)"
                            strokeWidth={3}
                            animationDuration={400}
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};
