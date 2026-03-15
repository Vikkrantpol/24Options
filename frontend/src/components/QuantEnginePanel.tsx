import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import type { ChainData, ConcreteLeg } from '../types';

const API = '/api';

interface Props {
    underlying: string;
    chainData: ChainData | null;
    currentLegs: ConcreteLeg[];
    onApplyLegs: (legs: ConcreteLeg[]) => void;
}

interface QuantProfile {
    risk_mode: string;
    target_delta: number;
    target_vega: number;
    max_slice_lots: number;
    allow_live_execution: boolean;
}

interface QuantRegime {
    symbol: string;
    regime: string;
    confidence: number;
    recommended_strategy_ids: number[];
}

interface QuantStrategySummary {
    id: number;
    name: string;
    category: string;
    description: string;
}

interface QuantDecision {
    confidence: number;
    grade: string;
    stress?: {
        worst_pnl: number;
        best_pnl: number;
        avg_pnl: number;
    };
}

interface QuantExecutionPlan {
    execution_ready: boolean;
    estimated_notional: number;
    order_slices: Array<Record<string, unknown>>;
    warnings: string[];
}

interface QuantAdaptive {
    strategy?: QuantStrategySummary;
    legs: ConcreteLeg[];
    decision?: QuantDecision;
    execution_plan?: QuantExecutionPlan;
}

interface QuantOptimizer {
    rebalancing_required: boolean;
    reasons: string[];
    rebalancing_legs: ConcreteLeg[];
    execution_plan?: QuantExecutionPlan;
}

interface QuantAdjustmentAction {
    strategy_id: string;
    strategy_name: string;
    action_type: string;
    reason: string;
    legs: ConcreteLeg[];
}

interface QuantAdjustments {
    actions: QuantAdjustmentAction[];
}

interface QuantAutopilotState {
    enabled: boolean;
    mode: 'paper' | 'live';
    rebalance_interval_sec: number;
    allow_live_execution: boolean;
    max_active_rebalance_per_symbol?: number;
    approval_id?: string;
    approved_at?: string | null;
    last_result?: Record<string, unknown> | null;
}

interface QuantJournalRecord {
    id: number;
    created_at: string;
    event_type: string;
    symbol?: string;
    payload?: Record<string, unknown>;
}

interface ClosedTradeRecord {
    id: string;
    template_name: string;
    underlying: string;
    entry_time: string;
    exit_time?: string | null;
    realized_pnl: number;
    status: string;
}

const asNumber = (value: unknown, fallback = 0): number => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const asString = (value: unknown, fallback = ''): string => {
    return typeof value === 'string' ? value : fallback;
};

const asObject = (value: unknown): Record<string, unknown> | null => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    return value as Record<string, unknown>;
};

const parseLeg = (value: unknown, fallbackExpiry: string): ConcreteLeg | null => {
    if (!value || typeof value !== 'object') return null;
    const row = value as Record<string, unknown>;
    const side = asString(row.side).toUpperCase();
    const right = asString(row.right).toUpperCase();
    if ((side !== 'BUY' && side !== 'SELL') || (right !== 'CE' && right !== 'PE' && right !== 'FUT')) {
        return null;
    }
    const leg: ConcreteLeg = {
        id: asString(row.id, ''),
        side: side as 'BUY' | 'SELL',
        right: right as 'CE' | 'PE' | 'FUT',
        strike: asNumber(row.strike, 0),
        premium: asNumber(row.premium, 0),
        qty: Math.max(1, Math.round(asNumber(row.qty, 1))),
        expiry: asString(row.expiry, fallbackExpiry),
        iv: row.iv !== undefined ? asNumber(row.iv, 0) : undefined,
        delta: row.delta !== undefined ? asNumber(row.delta, 0) : undefined,
        gamma: row.gamma !== undefined ? asNumber(row.gamma, 0) : undefined,
        vega: row.vega !== undefined ? asNumber(row.vega, 0) : undefined,
        theta: row.theta !== undefined ? asNumber(row.theta, 0) : undefined,
    };
    return leg;
};

export const QuantEnginePanel = ({ underlying, chainData, currentLegs, onApplyLegs }: Props) => {
    const [profile, setProfile] = useState<QuantProfile | null>(null);
    const [regime, setRegime] = useState<QuantRegime | null>(null);
    const [adaptive, setAdaptive] = useState<QuantAdaptive | null>(null);
    const [decision, setDecision] = useState<QuantDecision | null>(null);
    const [executionPlan, setExecutionPlan] = useState<QuantExecutionPlan | null>(null);
    const [optimizer, setOptimizer] = useState<QuantOptimizer | null>(null);
    const [adjustments, setAdjustments] = useState<QuantAdjustments | null>(null);
    const [autopilot, setAutopilot] = useState<QuantAutopilotState | null>(null);
    const [journal, setJournal] = useState<QuantJournalRecord[]>([]);
    const [closedTrades, setClosedTrades] = useState<ClosedTradeRecord[]>([]);
    const [learning, setLearning] = useState<Record<string, unknown> | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const [riskMode, setRiskMode] = useState('balanced');
    const [targetDelta, setTargetDelta] = useState('0');
    const [targetVega, setTargetVega] = useState('0');
    const [maxSliceLots, setMaxSliceLots] = useState('2');
    const [allowLive, setAllowLive] = useState(false);

    const [autopilotMode, setAutopilotMode] = useState<'paper' | 'live'>('paper');
    const [autopilotInterval, setAutopilotInterval] = useState('30');
    const expiryFallback = chainData?.expiry || '';

    const normalizedCurrentLegs = useMemo(
        () => currentLegs.map((l) => ({ ...l, expiry: l.expiry || expiryFallback })),
        [currentLegs, expiryFallback],
    );

    const withBusy = useCallback(async <T,>(label: string, fn: () => Promise<T>) => {
        setBusy(label);
        setError(null);
        try {
            return await fn();
        } catch (e) {
            setError((e as Error).message || `Failed: ${label}`);
            return null;
        } finally {
            setBusy(null);
        }
    }, []);

    const loadProfile = useCallback(async () => {
        const out = await withBusy('profile', async () => {
            const res = await axios.get<QuantProfile>(`${API}/quant/profile`);
            return res.data;
        });
        if (!out) return;
        setProfile(out);
        setRiskMode(asString(out.risk_mode, 'balanced'));
        setTargetDelta(String(asNumber(out.target_delta, 0)));
        setTargetVega(String(asNumber(out.target_vega, 0)));
        setMaxSliceLots(String(Math.max(1, Math.round(asNumber(out.max_slice_lots, 2)))));
        setAllowLive(Boolean(out.allow_live_execution));
    }, [withBusy]);

    const loadAutopilot = useCallback(async () => {
        const out = await withBusy('autopilot', async () => {
            const res = await axios.get<QuantAutopilotState>(`${API}/quant/autopilot/status`);
            return res.data;
        });
        if (!out) return;
        setAutopilot(out);
        setAutopilotMode(out.mode || 'paper');
        setAutopilotInterval(String(asNumber(out.rebalance_interval_sec, 30)));
    }, [withBusy]);

    const loadRegime = useCallback(async () => {
        const out = await withBusy('regime', async () => {
            const res = await axios.get<QuantRegime>(`${API}/quant/regime?underlying=${encodeURIComponent(underlying)}`);
            return res.data;
        });
        if (out) setRegime(out);
    }, [underlying, withBusy]);

    const loadJournal = useCallback(async () => {
        const out = await withBusy('journal', async () => {
            const res = await axios.get<{ records: QuantJournalRecord[] }>(`${API}/quant/journal?limit=20`);
            return res.data;
        });
        if (out) setJournal(out.records || []);
    }, [withBusy]);

    const loadClosedTrades = useCallback(async () => {
        try {
            const res = await axios.get<{ strategies: ClosedTradeRecord[] }>(`${API}/paper/positions`);
            const rows = (res.data.strategies || [])
                .filter((s) => s.status === 'closed')
                .sort((a, b) => {
                    const ta = new Date(a.exit_time || a.entry_time || '').getTime();
                    const tb = new Date(b.exit_time || b.entry_time || '').getTime();
                    return tb - ta;
                });
            setClosedTrades(rows);
        } catch (e) {
            setError((e as Error).message || 'Failed to load closed trades');
        }
    }, []);

    const loadLearning = useCallback(async () => {
        const out = await withBusy('learning', async () => {
            const res = await axios.get<Record<string, unknown>>(`${API}/quant/learning-summary?limit=80`);
            return res.data;
        });
        if (out) setLearning(out);
    }, [withBusy]);

    useEffect(() => {
        void loadProfile();
        void loadAutopilot();
        void loadRegime();
        void loadJournal();
        void loadLearning();
        void loadClosedTrades();
    }, [loadProfile, loadAutopilot, loadRegime, loadJournal, loadLearning, loadClosedTrades, underlying]);

    const saveProfile = async () => {
        const out = await withBusy('save-profile', async () => {
            const res = await axios.post<QuantProfile>(`${API}/quant/profile`, {
                patch: {
                    risk_mode: riskMode,
                    target_delta: asNumber(targetDelta, 0),
                    target_vega: asNumber(targetVega, 0),
                    max_slice_lots: Math.max(1, Math.round(asNumber(maxSliceLots, 2))),
                    allow_live_execution: allowLive,
                },
            });
            return res.data;
        });
        if (out) {
            setProfile(out);
            void loadJournal();
        }
    };

    const fetchAdaptive = async () => {
        const out = await withBusy('adaptive', async () => {
            const res = await axios.get<Record<string, unknown>>(
                `${API}/quant/adaptive-recommendation?underlying=${encodeURIComponent(underlying)}&num_lots=1`,
            );
            return res.data;
        });
        if (!out) return;
        const rawLegs = Array.isArray(out.legs) ? out.legs : [];
        const legs = rawLegs
            .map((leg) => parseLeg(leg, expiryFallback))
            .filter((leg): leg is ConcreteLeg => leg !== null);
        setAdaptive({
            strategy: out.strategy as QuantStrategySummary | undefined,
            legs,
            decision: out.decision as QuantDecision | undefined,
            execution_plan: out.execution_plan as QuantExecutionPlan | undefined,
        });
        if (out.decision) setDecision(out.decision as QuantDecision);
        if (out.execution_plan) setExecutionPlan(out.execution_plan as QuantExecutionPlan);
        void loadJournal();
    };

    const scoreCurrent = async () => {
        if (normalizedCurrentLegs.length === 0) return;
        const out = await withBusy('score', async () => {
            const res = await axios.post<QuantDecision>(`${API}/quant/decision-score`, {
                underlying,
                spot_price: chainData?.spot || undefined,
                legs: normalizedCurrentLegs,
            });
            return res.data;
        });
        if (out) setDecision(out);
    };

    const planCurrentExecution = async () => {
        if (normalizedCurrentLegs.length === 0) return;
        const out = await withBusy('execution-plan', async () => {
            const res = await axios.post<QuantExecutionPlan>(`${API}/quant/execution-plan`, {
                underlying,
                legs: normalizedCurrentLegs,
            });
            return res.data;
        });
        if (out) setExecutionPlan(out);
    };

    const runOptimizer = async () => {
        const out = await withBusy('optimizer', async () => {
            const res = await axios.post<QuantOptimizer>(`${API}/quant/portfolio-optimize`, {
                underlying,
                target_delta: asNumber(targetDelta, 0),
                target_vega: asNumber(targetVega, 0),
            });
            return res.data;
        });
        if (out) {
            const raw = Array.isArray(out.rebalancing_legs) ? out.rebalancing_legs : [];
            const parsed = raw
                .map((leg) => parseLeg(leg, expiryFallback))
                .filter((leg): leg is ConcreteLeg => leg !== null);
            setOptimizer({ ...out, rebalancing_legs: parsed });
            if (out.execution_plan) setExecutionPlan(out.execution_plan);
            void loadJournal();
        }
    };

    const runAdjustments = async () => {
        const out = await withBusy('adjustments', async () => {
            const res = await axios.get<QuantAdjustments>(
                `${API}/quant/adjustments?underlying=${encodeURIComponent(underlying)}`,
            );
            return res.data;
        });
        if (!out) return;
        const normalizedActions = (out.actions || []).map((a) => ({
            ...a,
            legs: (a.legs || [])
                .map((leg) => parseLeg(leg, expiryFallback))
                .filter((leg): leg is ConcreteLeg => leg !== null),
        }));
        setAdjustments({ actions: normalizedActions });
        void loadJournal();
    };

    const approveAutopilot = async () => {
        const out = await withBusy('approve-autopilot', async () => {
            const res = await axios.post<QuantAutopilotState>(`${API}/quant/autopilot/approve`, {
                mode: autopilotMode,
                rebalance_interval_sec: Math.max(10, Math.round(asNumber(autopilotInterval, 30))),
                allow_strategy_switch: true,
                allow_live_execution: allowLive && autopilotMode === 'live',
                max_active_rebalance_per_symbol: 1,
                approval_note: 'approved-from-ui',
            });
            return res.data;
        });
        if (out) {
            setAutopilot(out);
            void loadJournal();
        }
    };

    const pauseAutopilot = async () => {
        const out = await withBusy('pause-autopilot', async () => {
            const res = await axios.post<QuantAutopilotState>(`${API}/quant/autopilot/pause?reason=paused-from-ui`);
            return res.data;
        });
        if (out) {
            setAutopilot(out);
            void loadJournal();
        }
    };

    const runAutopilot = async () => {
        const out = await withBusy('run-autopilot', async () => {
            const res = await axios.post<Record<string, unknown>>(`${API}/quant/autopilot/run`, {
                underlying,
                force: true,
            });
            return res.data;
        });
        if (!out) return;
        await loadAutopilot();
        await loadJournal();
        await loadClosedTrades();
        if (out.optimizer && typeof out.optimizer === 'object') {
            const opt = out.optimizer as QuantOptimizer;
            const raw = Array.isArray(opt.rebalancing_legs) ? opt.rebalancing_legs : [];
            const parsed = raw
                .map((leg) => parseLeg(leg, expiryFallback))
                .filter((leg): leg is ConcreteLeg => leg !== null);
            setOptimizer({ ...opt, rebalancing_legs: parsed });
        }
        if (out.adjustments && typeof out.adjustments === 'object') {
            const adj = out.adjustments as QuantAdjustments;
            setAdjustments(adj);
        }
    };

    const applyLegs = (legs: ConcreteLeg[]) => {
        if (legs.length === 0) return;
        onApplyLegs(legs);
    };

    const summarizeJournal = (row: QuantJournalRecord): string => {
        const payload = asObject(row.payload);
        if (!payload) return '';

        if (row.event_type === 'autopilot_action') {
            const action = asString(payload.action);
            const status = asString(payload.status, payload.result ? 'executed' : '');
            const reason = asString(payload.reason);
            return [action, status, reason].filter(Boolean).join(' · ');
        }

        if (row.event_type === 'autopilot_cycle') {
            const report = asObject(payload.execution_report);
            const executed = asNumber(report?.executed_count, 0);
            const skipped = asNumber(report?.skipped_count, 0);
            return `executed:${executed} skipped:${skipped}`;
        }

        if (row.event_type === 'portfolio_optimizer') {
            const needed = Boolean(payload.rebalancing_required);
            const legs = Array.isArray(payload.rebalancing_legs) ? payload.rebalancing_legs.length : 0;
            return needed ? `rebalancing required · legs:${legs}` : 'no rebalance required';
        }

        return '';
    };

    return (
        <div className="panel">
            <div className="panel__header">
                <span className="panel__title">▸ QUANT ENGINE v1</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {busy && <span className="btn btn--xs">{busy}</span>}
                    {autopilot?.enabled ? (
                        <span className="btn btn--xs btn--green">AUTO ON ({autopilot.mode.toUpperCase()})</span>
                    ) : (
                        <span className="btn btn--xs">AUTO OFF</span>
                    )}
                </div>
            </div>
            <div className="panel__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))', gap: 8 }}>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Regime</span>
                        <span className="metric-cell__val">{regime?.regime || '—'}</span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Regime Conf.</span>
                        <span className="metric-cell__val">{regime ? `${Math.round((regime.confidence || 0) * 100)}%` : '—'}</span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Decision Grade</span>
                        <span className={`metric-cell__val ${decision?.grade === 'A' || decision?.grade === 'B' ? 'val--pos' : ''}`}>{decision?.grade || '—'}</span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Conf. Score</span>
                        <span className="metric-cell__val">{decision ? `${Math.round(decision.confidence * 100)}%` : '—'}</span>
                    </div>
                </div>

                <div className="builder-controls" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(80px, 1fr))' }}>
                    <select className="expiry-select" value={riskMode} onChange={e => setRiskMode(e.target.value)}>
                        <option value="conservative">conservative</option>
                        <option value="balanced">balanced</option>
                        <option value="aggressive">aggressive</option>
                    </select>
                    <input className="builder-input" value={targetDelta} onChange={e => setTargetDelta(e.target.value)} placeholder="Target Δ" />
                    <input className="builder-input" value={targetVega} onChange={e => setTargetVega(e.target.value)} placeholder="Target Vega" />
                    <input className="builder-input" value={maxSliceLots} onChange={e => setMaxSliceLots(e.target.value)} placeholder="Slice Lots" />
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--text-2)' }}>
                        <input type="checkbox" checked={allowLive} onChange={e => setAllowLive(e.target.checked)} />
                        allow live
                    </label>
                    <button className="btn btn--cyan btn--xs" onClick={saveProfile}>SAVE PROFILE</button>
                </div>

                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button className="btn btn--xs btn--green" onClick={loadRegime}>REGIME</button>
                    <button className="btn btn--xs btn--green" onClick={fetchAdaptive}>ADAPTIVE PICK</button>
                    <button className="btn btn--xs" onClick={scoreCurrent} disabled={normalizedCurrentLegs.length === 0}>SCORE CURRENT</button>
                    <button className="btn btn--xs" onClick={planCurrentExecution} disabled={normalizedCurrentLegs.length === 0}>PLAN CURRENT</button>
                    <button className="btn btn--xs" onClick={runOptimizer}>OPTIMIZE</button>
                    <button className="btn btn--xs" onClick={runAdjustments}>ADJUSTMENTS</button>
                    <button className="btn btn--xs" onClick={loadJournal}>JOURNAL</button>
                    <button className="btn btn--xs" onClick={loadClosedTrades}>CLOSED TRADES</button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <select className="expiry-select" value={autopilotMode} onChange={e => setAutopilotMode(e.target.value as 'paper' | 'live')}>
                        <option value="paper">paper</option>
                        <option value="live">live</option>
                    </select>
                    <input className="builder-input" style={{ width: 90 }} value={autopilotInterval} onChange={e => setAutopilotInterval(e.target.value)} placeholder="Interval(s)" />
                    <button className="btn btn--xs btn--cyan" onClick={approveAutopilot}>APPROVE AUTO</button>
                    <button className="btn btn--xs btn--red" onClick={pauseAutopilot}>PAUSE</button>
                    <button className="btn btn--xs btn--green" onClick={runAutopilot}>RUN NOW</button>
                    {autopilot?.approval_id && <span style={{ color: 'var(--text-3)', fontSize: 10 }}>id:{autopilot.approval_id}</span>}
                </div>

                {adaptive?.strategy && (
                    <div className="monitor-card" style={{ marginBottom: 0 }}>
                        <div className="monitor-card__head">
                            <span className="monitor-card__name">
                                Adaptive: #{adaptive.strategy.id} {adaptive.strategy.name}
                            </span>
                            <button className="btn btn--xs btn--green" onClick={() => applyLegs(adaptive.legs)}>LOAD LEGS</button>
                        </div>
                        <div className="monitor-card__legs">
                            <div>{adaptive.strategy.description}</div>
                            <div>Execution: {adaptive.execution_plan?.execution_ready ? 'ready' : 'guarded'}</div>
                        </div>
                    </div>
                )}

                {optimizer?.rebalancing_required && optimizer.rebalancing_legs.length > 0 && (
                    <div className="monitor-card" style={{ marginBottom: 0 }}>
                        <div className="monitor-card__head">
                            <span className="monitor-card__name">Optimizer Hedge Legs ({optimizer.rebalancing_legs.length})</span>
                            <button className="btn btn--xs btn--cyan" onClick={() => applyLegs(optimizer.rebalancing_legs)}>
                                LOAD HEDGE
                            </button>
                        </div>
                        <div className="monitor-card__legs">
                            {(optimizer.reasons || []).map((r, i) => <div key={i}>{r}</div>)}
                        </div>
                    </div>
                )}

                {adjustments?.actions && adjustments.actions.length > 0 && (
                    <div className="monitor-card" style={{ marginBottom: 0 }}>
                        <div className="monitor-card__head">
                            <span className="monitor-card__name">Adjustment Actions ({adjustments.actions.length})</span>
                        </div>
                        <div className="monitor-card__legs">
                            {adjustments.actions.slice(0, 4).map((a, idx) => (
                                <div key={idx} style={{ marginBottom: 6 }}>
                                    <div>{a.action_type} · {a.strategy_name}</div>
                                    <div style={{ color: 'var(--text-3)' }}>{a.reason}</div>
                                    {a.legs.length > 0 && (
                                        <button
                                            className="btn btn--xs"
                                            style={{ marginTop: 4 }}
                                            onClick={() => applyLegs(a.legs)}
                                        >
                                            LOAD ACTION LEGS
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {executionPlan && (
                    <div className="metrics-strip">
                        <div className="metric-cell">
                            <span className="metric-cell__label">Execution</span>
                            <span className={`metric-cell__val ${executionPlan.execution_ready ? 'val--pos' : 'val--neg'}`}>
                                {executionPlan.execution_ready ? 'READY' : 'GUARDED'}
                            </span>
                        </div>
                        <div className="metric-cell">
                            <span className="metric-cell__label">Slices</span>
                            <span className="metric-cell__val">{executionPlan.order_slices?.length || 0}</span>
                        </div>
                        <div className="metric-cell">
                            <span className="metric-cell__label">Notional</span>
                            <span className="metric-cell__val">₹{Math.round(executionPlan.estimated_notional || 0).toLocaleString()}</span>
                        </div>
                        <div className="metric-cell">
                            <span className="metric-cell__label">Warnings</span>
                            <span className="metric-cell__val">{executionPlan.warnings?.length || 0}</span>
                        </div>
                    </div>
                )}

                {error && <div style={{ color: 'var(--red)', fontSize: 11 }}>{error}</div>}

                <div className="monitor-card" style={{ marginBottom: 0 }}>
                    <div className="monitor-card__head">
                        <span className="monitor-card__name">Trading Journal</span>
                    </div>
                    <div className="monitor-card__legs">
                        {journal.length === 0 ? (
                            <div style={{ color: 'var(--text-3)' }}>No events yet.</div>
                        ) : (
                            journal.map((row) => (
                                <div key={row.id}>
                                    <div>{new Date(row.created_at).toLocaleString('en-IN')} · {row.event_type}</div>
                                    {summarizeJournal(row) && (
                                        <div style={{ color: 'var(--text-3)' }}>{summarizeJournal(row)}</div>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </div>

                <div className="monitor-card" style={{ marginBottom: 0 }}>
                    <div className="monitor-card__head">
                        <span className="monitor-card__name">Closed Trades</span>
                    </div>
                    <div className="monitor-card__legs">
                        {closedTrades.length === 0 ? (
                            <div style={{ color: 'var(--text-3)' }}>No closed trades yet.</div>
                        ) : (
                            closedTrades.slice(0, 12).map((row) => (
                                <div key={row.id}>
                                    <div>{row.template_name} · {row.underlying}</div>
                                    <div style={{ color: 'var(--text-3)' }}>
                                        Exit: {row.exit_time ? new Date(row.exit_time).toLocaleString('en-IN') : 'n/a'} ·
                                        Realized: {(row.realized_pnl || 0) >= 0 ? '+' : ''}₹{(row.realized_pnl || 0).toLocaleString('en-IN')}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>

                {learning && (
                    <div style={{ color: 'var(--text-3)', fontSize: 10 }}>
                        Learning summary: sample {asNumber(learning.sample_size, 0)} · win-rate {asNumber(learning.win_rate_pct, 0).toFixed(1)}%
                    </div>
                )}
            </div>
        </div>
    );
};
