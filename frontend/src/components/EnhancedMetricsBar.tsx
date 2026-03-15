import React from 'react';

interface MarketStatus {
    status: 'OPEN' | 'PRE_OPEN' | 'CLOSED' | 'HOLIDAY' | 'WEEKEND';
    message: string;
    is_open: boolean;
    seconds_to_open: number | null;
    seconds_to_close: number | null;
    current_ist: string;
}

interface EnhancedData {
    capital_required: number;
    pct_return: number;
    pop: number;
    be_pct: number[];
    current_pnl: number;
    theta_daily: number;
    delta_net: number;
    vega_net: number;
    iv_avg_pct: number;
    one_sigma_up: number;
    one_sigma_down: number;
    dte: number;
}

interface Props {
    enhanced: EnhancedData | null;
    market: MarketStatus | null;
    spot: number;
}

const Pill: React.FC<{ label: string; value: string; color?: string; bg?: string }> = ({
    label, value, color = 'var(--green)', bg = 'rgba(0,230,118,0.06)'
}) => (
    <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        background: bg, border: `1px solid ${color}22`,
        borderRadius: '4px', padding: '5px 10px', minWidth: '80px',
    }}>
        <span style={{ fontSize: '9px', color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</span>
        <span style={{ fontSize: '12px', fontWeight: 700, color, fontFamily: "'JetBrains Mono', monospace", marginTop: '2px' }}>{value}</span>
    </div>
);

export const EnhancedMetricsBar: React.FC<Props> = ({ enhanced, market, spot }) => {
    const marketColor =
        market?.status === 'OPEN' ? 'var(--green)' :
            market?.status === 'PRE_OPEN' ? 'var(--amber)' : '#607080';

    const marketBg =
        market?.status === 'OPEN' ? 'rgba(0,230,118,0.06)' :
            market?.status === 'PRE_OPEN' ? 'rgba(255,171,0,0.06)' : 'rgba(96,112,128,0.06)';

    return (
        <div style={{
            display: 'flex', gap: '6px', padding: '6px 12px 8px',
            borderBottom: '1px solid var(--border)', flexWrap: 'wrap', alignItems: 'center',
            background: 'rgba(0,0,0,0.2)',
        }}>
            {/* Market Status */}
            <Pill
                label="Market"
                value={market ? `● ${market.status.replace('_', '-')}` : '...'}
                color={marketColor}
                bg={marketBg}
            />

            {enhanced ? (
                <>
                    {/* Capital Required */}
                    <Pill
                        label="Capital Reqd"
                        value={`₹${Math.round(enhanced.capital_required).toLocaleString()}`}
                        color="var(--cyan)"
                        bg="rgba(0,188,212,0.06)"
                    />

                    {/* Probability of Profit */}
                    <Pill
                        label="PoP"
                        value={`${enhanced.pop}%`}
                        color={enhanced.pop >= 60 ? 'var(--green)' : enhanced.pop >= 45 ? 'var(--amber)' : '#ff1744'}
                        bg={enhanced.pop >= 60 ? 'rgba(0,230,118,0.06)' : 'rgba(255,171,0,0.06)'}
                    />

                    {/* % Return on Capital */}
                    <Pill
                        label="% Return"
                        value={`${enhanced.pct_return > 0 ? '+' : ''}${enhanced.pct_return}%`}
                        color={enhanced.pct_return >= 0 ? 'var(--green)' : '#ff1744'}
                    />

                    {/* Live P&L */}
                    <Pill
                        label="Live P&L"
                        value={`${enhanced.current_pnl >= 0 ? '+' : ''}₹${Math.round(enhanced.current_pnl).toLocaleString()}`}
                        color={enhanced.current_pnl >= 0 ? 'var(--green)' : '#ff1744'}
                    />

                    {/* Breakeven % distances */}
                    {enhanced.be_pct.length > 0 && (
                        <Pill
                            label="BE Distance"
                            value={enhanced.be_pct.map(b => `${b > 0 ? '+' : ''}${b}%`).join(' | ')}
                            color="var(--amber)"
                            bg="rgba(255,171,0,0.06)"
                        />
                    )}

                    {/* 1σ Range */}
                    <Pill
                        label="±1σ Range"
                        value={`${Math.round(enhanced.one_sigma_down).toLocaleString()} – ${Math.round(enhanced.one_sigma_up).toLocaleString()}`}
                        color="#9c27b0"
                        bg="rgba(156,39,176,0.06)"
                    />

                    {/* Theta per day */}
                    <Pill
                        label="θ/day"
                        value={`₹${enhanced.theta_daily.toFixed(0)}`}
                        color={enhanced.theta_daily >= 0 ? 'var(--green)' : '#ff1744'}
                    />

                    {/* Net Delta */}
                    <Pill
                        label="Δ Net"
                        value={enhanced.delta_net.toFixed(3)}
                        color={Math.abs(enhanced.delta_net) < 0.1 ? 'var(--green)' : 'var(--amber)'}
                    />

                    {/* IV */}
                    <Pill
                        label="IV Avg"
                        value={`${enhanced.iv_avg_pct}%`}
                        color="#607080"
                        bg="rgba(96,112,128,0.06)"
                    />
                </>
            ) : (
                <span style={{ fontSize: '11px', color: 'var(--muted)', padding: '5px' }}>
                    Add legs to see capital requirements, PoP and live analytics
                </span>
            )}
        </div>
    );
};
