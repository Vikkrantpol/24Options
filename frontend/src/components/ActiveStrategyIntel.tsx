import { useMemo, useState } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChainData, ConcreteLeg } from '../types';

const API = '/api';

interface Props {
    strategyName: string;
    underlying: string;
    legs: ConcreteLeg[];
    chainData: ChainData | null;
    currentPop?: number | null;
    onApplyLegs: (legs: ConcreteLeg[]) => void;
}

interface DecisionScore {
    confidence: number;
    grade: string;
    stress?: {
        worst_pnl: number;
        best_pnl: number;
        avg_pnl: number;
    };
}

interface ExecutionPlan {
    execution_ready: boolean;
    estimated_notional: number;
    order_slices: Array<Record<string, unknown>>;
    warnings: string[];
}

function extractDeployJson(text: string): Record<string, unknown> | null {
    const match = text.match(/```json\s*([\s\S]*?)\s*```/);
    if (!match) return null;
    try {
        const parsed = JSON.parse(match[1]);
        if (parsed && parsed.action === 'deploy_strategy' && Array.isArray(parsed.legs)) {
            return parsed as Record<string, unknown>;
        }
    } catch {
        return null;
    }
    return null;
}

function normalizeLegs(raw: unknown[], expiryFallback: string): ConcreteLeg[] {
    return raw
        .map((r) => {
            if (!r || typeof r !== 'object') return null;
            const row = r as Record<string, unknown>;
            const sideRaw = String(row.side || '').toUpperCase();
            const rightRaw = String(row.right || '').toUpperCase();
            const side: 'BUY' | 'SELL' = sideRaw === 'SELL' ? 'SELL' : sideRaw === 'BUY' ? 'BUY' : 'BUY';
            const right: 'CE' | 'PE' | 'FUT' =
                rightRaw === 'PE' ? 'PE' : rightRaw === 'FUT' ? 'FUT' : rightRaw === 'CE' ? 'CE' : 'CE';

            const strike = Number(row.strike ?? 0);
            const premium = Number(row.premium ?? 0);
            const qty = Math.max(1, Number(row.qty ?? 1));
            if (!Number.isFinite(strike) || strike <= 0 || !Number.isFinite(premium) || !Number.isFinite(qty)) {
                return null;
            }

            return {
                id: String(row.id || ''),
                side,
                right,
                strike,
                premium,
                qty,
                expiry: String(row.expiry || expiryFallback || ''),
                iv: row.iv !== undefined ? Number(row.iv) : undefined,
                delta: row.delta !== undefined ? Number(row.delta) : undefined,
                gamma: row.gamma !== undefined ? Number(row.gamma) : undefined,
                vega: row.vega !== undefined ? Number(row.vega) : undefined,
                theta: row.theta !== undefined ? Number(row.theta) : undefined,
            } as ConcreteLeg;
        })
        .filter((x): x is ConcreteLeg => Boolean(x));
}

export const ActiveStrategyIntel = ({
    strategyName,
    underlying,
    legs,
    chainData,
    currentPop,
    onApplyLegs,
}: Props) => {
    const [loading, setLoading] = useState<'score' | 'execution' | 'ai' | null>(null);
    const [decision, setDecision] = useState<DecisionScore | null>(null);
    const [executionPlan, setExecutionPlan] = useState<ExecutionPlan | null>(null);
    const [aiReply, setAiReply] = useState<string>('');
    const [error, setError] = useState<string>('');

    const normalizedLegs = useMemo(
        () => legs.map((l) => ({ ...l, expiry: l.expiry || chainData?.expiry || '' })),
        [legs, chainData?.expiry],
    );

    const runDecisionScore = async () => {
        setLoading('score');
        setError('');
        try {
            const res = await axios.post<DecisionScore>(`${API}/quant/decision-score`, {
                underlying,
                spot_price: chainData?.spot || undefined,
                legs: normalizedLegs,
            });
            setDecision(res.data);
        } catch (e) {
            setError((e as Error).message || 'Decision score failed');
        } finally {
            setLoading(null);
        }
    };

    const runExecutionPlan = async () => {
        setLoading('execution');
        setError('');
        try {
            const res = await axios.post<ExecutionPlan>(`${API}/quant/execution-plan`, {
                underlying,
                legs: normalizedLegs,
            });
            setExecutionPlan(res.data);
        } catch (e) {
            setError((e as Error).message || 'Execution plan failed');
        } finally {
            setLoading(null);
        }
    };

    const runAiOddsBoost = async () => {
        setLoading('ai');
        setError('');
        try {
            const popHint = Number.isFinite(Number(currentPop)) ? `Current PoP is ${Number(currentPop).toFixed(1)}%.` : '';
            const query = [
                `I am monitoring active strategy: ${strategyName}.`,
                popHint,
                'Give highest-probability adjustment plan to maximize winning odds while controlling risk.',
                'Use exact strikes from live chain, include adjustment legs and strict exit rules.',
                'Return deployable JSON.',
            ].join(' ');

            const res = await axios.post<{ reply: string }>(`${API}/ai/chat`, {
                query,
                history: [],
                current_legs: normalizedLegs,
                context: `Monitor mode. Focus on improving PoP and reducing tail risk for ${strategyName}.`,
                thinking_enabled: true,
                underlying,
            });
            setAiReply(res.data.reply || '');
        } catch (e) {
            setError((e as Error).message || 'AI odds boost failed');
        } finally {
            setLoading(null);
        }
    };

    const deployJson = extractDeployJson(aiReply);
    const suggestedLegs = deployJson
        ? normalizeLegs((deployJson.legs as unknown[]) || [], chainData?.expiry || '')
        : [];
    const renderReply = deployJson ? aiReply.replace(/```json\s*[\s\S]*?\s*```/g, '').trim() : aiReply;

    return (
        <div className="panel" style={{ marginTop: 12 }}>
            <div className="panel__header">
                <span className="panel__title">▸ ACTIVE STRATEGY INTEL</span>
                <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn--xs" onClick={runDecisionScore} disabled={loading !== null}>
                        SCORE
                    </button>
                    <button className="btn btn--xs" onClick={runExecutionPlan} disabled={loading !== null}>
                        EXEC PLAN
                    </button>
                    <button className="btn btn--xs btn--green" onClick={runAiOddsBoost} disabled={loading !== null}>
                        AI ODDS BOOST
                    </button>
                </div>
            </div>
            <div className="panel__body">
                {loading && (
                    <div style={{ color: 'var(--text-3)', fontSize: 11, marginBottom: 8 }}>
                        Running {loading}...
                    </div>
                )}
                {error && (
                    <div style={{ color: 'var(--red)', fontSize: 11, marginBottom: 8 }}>
                        {error}
                    </div>
                )}

                <div className="metrics-strip">
                    <div className="metric-cell">
                        <span className="metric-cell__label">Current PoP</span>
                        <span className="metric-cell__val">
                            {currentPop !== undefined && currentPop !== null ? `${Number(currentPop).toFixed(1)}%` : '—'}
                        </span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Decision Grade</span>
                        <span className={`metric-cell__val ${decision?.grade === 'A' || decision?.grade === 'B' ? 'val--pos' : ''}`}>
                            {decision?.grade || '—'}
                        </span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Confidence</span>
                        <span className="metric-cell__val">
                            {decision ? `${Math.round(decision.confidence * 100)}%` : '—'}
                        </span>
                    </div>
                    <div className="metric-cell">
                        <span className="metric-cell__label">Execution</span>
                        <span className={`metric-cell__val ${executionPlan?.execution_ready ? 'val--pos' : 'val--neg'}`}>
                            {executionPlan ? (executionPlan.execution_ready ? 'READY' : 'GUARDED') : '—'}
                        </span>
                    </div>
                </div>

                {executionPlan && (
                    <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-2)' }}>
                        Slices: {executionPlan.order_slices?.length || 0} · Notional: ₹{Math.round(executionPlan.estimated_notional || 0).toLocaleString()} · Warnings: {executionPlan.warnings?.length || 0}
                    </div>
                )}

                {aiReply && (
                    <div style={{ marginTop: 10, borderTop: '1px solid var(--border-0)', paddingTop: 8 }}>
                        <div style={{ color: 'var(--green)', fontSize: 10, marginBottom: 6, letterSpacing: '0.08em' }}>
                            AI MONITOR OUTPUT
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-1)', lineHeight: 1.6 }}>
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{renderReply || 'Suggested deploy payload available.'}</ReactMarkdown>
                        </div>
                        {suggestedLegs.length > 0 && (
                            <button
                                className="btn btn--cyan btn--xs"
                                style={{ marginTop: 8 }}
                                onClick={() => onApplyLegs(suggestedLegs)}
                            >
                                LOAD AI ADJUSTMENT LEGS
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

