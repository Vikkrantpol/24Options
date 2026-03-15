import React, { useState, useRef, useEffect, useCallback } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AIMessage, ConcreteLeg, ChainData, GreeksSummary } from '../types';

interface Props {
    legs: ConcreteLeg[];
    strategyName: string;
    chainData?: ChainData | null;
    greeks?: GreeksSummary | null;
    marketStatus?: any;
    underlying?: string;
    onDeployLegs?: (legs: any[]) => void;
}

// ── Preset queries (no emojis, engineer tone) ─────────────────────────────────
const PRESET_QUERIES = [
    { label: 'Best strategy for today', text: 'Analyse the live chain Greeks, IV skew, and DTE. Select the single highest-probability strategy with exact strikes, PoP, Theta/day, capital required, and entry/exit rules.' },
    { label: 'Signal strategy', text: 'Scan the live chain for Greek mismatches against BSM fair value and combine that with OI positioning. Recommend the single best canonical strategy with exact legs.' },
    { label: 'Bullish OI setup', text: 'Read the live OI structure around ATM and build the best bullish strategy if put-side support is dominant. Use exact strikes and risk metrics.' },
    { label: 'Bearish OI setup', text: 'Read the live OI structure around ATM and build the best bearish strategy if call-side resistance is dominant. Use exact strikes and risk metrics.' },
    { label: 'Theta-optimal setup', text: 'Which strike combination generates maximum theta per rupee of capital deployed, while keeping delta near zero and PoP above 60%? Build the legs.' },
    { label: 'IV skew analysis', text: 'Analyse the current IV skew — CE vs PE across strikes. Is skew steep, flat, inverted? What does it imply about market positioning and what strategy fits?' },
    { label: 'Risk / max pain report', text: 'Calculate max pain level from open interest. Where is my portfolio most exposed? At which spot levels do I face maximum drawdown? Recommend a hedge.' },
    { label: 'Analyse my current position', text: 'Review my current legs and Greeks. Are these strikes optimal? What is the probability of max profit at expiry? Should I adjust or hold?' },
    { label: 'DTE decay curve', text: 'Model my position\'s theta decay over the remaining DTE. At what point does time value erosion peak? When should I close or roll?' },
    { label: 'Volatility crush trade', text: 'Is IV elevated vs historical norms? If yes, build a vega-negative strategy to profit from IV crush. Include exact strikes from the live chain.' },
];

const FOLLOWUP_POOL = [
    'What strike adjustments improve PoP above 65%?',
    'Model what happens if spot moves ±2% from here.',
    'Should I roll to next expiry or hold till expiry?',
    'Add the cheapest possible hedge to this position.',
    'At what spot price should I book 50% of max profit?',
    'What does OI buildup at ATM tell us about direction?',
    'Run a worst-case scenario — IV spikes +5 points.',
    'If I am right directionally, what is the optimal leverage structure?',
    'Calculate exact breakeven prices as % from current spot.',
    'Compare Iron Condor vs Iron Butterfly for this DTE and IV.',
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function daysToExpiry(expiry: string): number {
    if (!expiry) return 0;
    const parts = expiry.split('-');
    if (parts.length !== 3) return 0;

    let y = 0;
    let m = 0;
    let d = 0;
    // Handle both YYYY-MM-DD and DD-MM-YYYY formats safely
    if (parts[0].length === 4) {
        y = Number(parts[0]);
        m = Number(parts[1]) - 1;
        d = Number(parts[2]);
    } else {
        y = Number(parts[2]);
        m = Number(parts[1]) - 1;
        d = Number(parts[0]);
    }
    if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return 0;
    const expDay = new Date(y, m, d, 0, 0, 0, 0);
    if (Number.isNaN(expDay.getTime())) return 0;
    const today = new Date();
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0, 0);
    return Math.max(Math.ceil((expDay.getTime() - todayStart.getTime()) / 86400000), 0);
}

function extractDeployJson(text: string): any | null {
    const match = text.match(/```json\s*([\s\S]*?)\s*```/);
    if (!match) return null;
    try {
        const obj = JSON.parse(match[1]);
        if (obj.action === 'deploy_strategy' && Array.isArray(obj.legs)) return obj;
    } catch { /* ignore */ }
    return null;
}

function fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve((r.result as string).split(',')[1]);
        r.onerror = reject;
        r.readAsDataURL(file);
    });
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
const mdComponents: any = {
    h1: ({ children }: any) => (
        <h1 style={{ color: 'var(--green)', fontSize: '13px', fontWeight: 700, margin: '12px 0 5px', borderBottom: '1px solid rgba(0,230,118,0.18)', paddingBottom: '4px' }}>{children}</h1>
    ),
    h2: ({ children }: any) => (
        <h2 style={{ color: 'var(--green)', fontSize: '12px', fontWeight: 700, margin: '10px 0 4px' }}>{children}</h2>
    ),
    h3: ({ children }: any) => (
        <h3 style={{ color: 'var(--cyan)', fontSize: '11px', fontWeight: 700, margin: '8px 0 3px' }}>{children}</h3>
    ),
    p: ({ children }: any) => (
        <p style={{ margin: '3px 0', lineHeight: 1.65, fontSize: '11.5px', color: '#c8d8e0' }}>{children}</p>
    ),
    strong: ({ children }: any) => <strong style={{ color: '#ffffff', fontWeight: 700 }}>{children}</strong>,
    em: ({ children }: any) => <em style={{ color: 'var(--amber)', fontStyle: 'italic' }}>{children}</em>,
    code: ({ inline, children }: any) =>
        inline ? (
            <code style={{ background: 'rgba(0,230,118,0.1)', color: 'var(--green)', padding: '1px 5px', borderRadius: '3px', fontSize: '10.5px', fontFamily: "'JetBrains Mono', monospace" }}>{children}</code>
        ) : (
            <pre style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(0,230,118,0.15)', borderRadius: '4px', padding: '8px 10px', margin: '6px 0', overflowX: 'auto', fontSize: '10.5px', fontFamily: "'JetBrains Mono', monospace", color: '#a8d8b0', lineHeight: 1.5 }}>
                <code>{children}</code>
            </pre>
        ),
    table: ({ children }: any) => (
        <div style={{ overflowX: 'auto', margin: '7px 0', borderRadius: '4px', border: '1px solid rgba(0,230,118,0.2)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10.5px', fontFamily: "'JetBrains Mono', monospace" }}>{children}</table>
        </div>
    ),
    thead: ({ children }: any) => <thead style={{ background: 'rgba(0,230,118,0.07)' }}>{children}</thead>,
    th: ({ children }: any) => (
        <th style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--green)', fontWeight: 700, borderBottom: '1px solid rgba(0,230,118,0.22)', whiteSpace: 'nowrap' }}>{children}</th>
    ),
    td: ({ children }: any) => (
        <td style={{ padding: '4px 8px', color: '#c0d0da', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>{children}</td>
    ),
    tr: ({ children }: any) => (
        <tr onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,230,118,0.04)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>{children}</tr>
    ),
    ul: ({ children }: any) => <ul style={{ margin: '3px 0 3px 14px', padding: 0, listStyleType: 'none' }}>{children}</ul>,
    ol: ({ children }: any) => <ol style={{ margin: '3px 0 3px 14px', padding: 0, listStyleType: 'decimal', paddingLeft: '14px' }}>{children}</ol>,
    li: ({ children }: any) => (
        <li style={{ margin: '2px 0', fontSize: '11.5px', color: '#c8d8e0', lineHeight: 1.55, display: 'flex', gap: '5px' }}>
            <span style={{ color: 'var(--green)', minWidth: '9px', flexShrink: 0 }}>▸</span><span>{children}</span>
        </li>
    ),
    hr: () => <hr style={{ border: 'none', borderTop: '1px solid rgba(0,230,118,0.1)', margin: '7px 0' }} />,
    blockquote: ({ children }: any) => (
        <blockquote style={{ borderLeft: '3px solid var(--cyan)', paddingLeft: '8px', margin: '5px 0', color: '#8090a0', fontStyle: 'italic', fontSize: '10.5px' }}>{children}</blockquote>
    ),
};

// ── Bubbles ───────────────────────────────────────────────────────────────────
const UserBubble: React.FC<{ text: string; image?: string }> = ({ text, image }) => (
    <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '5px 0' }}>
        <div style={{ background: 'rgba(96,112,128,0.18)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '4px 4px 0 4px', padding: '6px 10px', maxWidth: '88%', fontSize: '11.5px', color: '#d0e0ea', lineHeight: 1.5, fontFamily: "'JetBrains Mono', monospace" }}>
            {image && <img src={`data:image/jpeg;base64,${image}`} alt="attached" style={{ maxWidth: '100%', borderRadius: '3px', marginBottom: '5px', display: 'block' }} />}
            <span style={{ color: 'var(--muted)', marginRight: '4px' }}>&gt;</span>{text}
        </div>
    </div>
);

const AssistantBubble: React.FC<{ text: string; onDeploy?: (legs: any[]) => void }> = ({ text, onDeploy }) => {
    const deployJson = extractDeployJson(text);
    const renderText = deployJson
        ? text.replace(/```json\s*[\s\S]*?\s*```/g, '').trim()
        : text;
    const isInit = text.startsWith('> MINIMAX');

    if (isInit) {
        return (
            <div style={{ margin: '4px 0 10px' }}>
                {text.split('\n').map((line, i) => (
                    <div key={i} style={{ color: 'var(--green)', fontSize: '10.5px', opacity: 0.7, fontFamily: "'JetBrains Mono', monospace" }}>{line}</div>
                ))}
            </div>
        );
    }

    return (
        <div style={{ background: 'rgba(0,15,10,0.55)', border: '1px solid rgba(0,230,118,0.1)', borderRadius: '0 4px 4px 4px', padding: '9px 11px', margin: '5px 0 8px', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '7px', paddingBottom: '5px', borderBottom: '1px solid rgba(0,230,118,0.08)', fontSize: '8.5px', color: 'var(--green)', opacity: 0.55, letterSpacing: '0.12em' }}>
                <span>●</span><span>QUANT ENGINE OUTPUT</span>
            </div>
            {renderText ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{renderText}</ReactMarkdown>
            ) : (
                <p style={{ margin: 0, lineHeight: 1.65, fontSize: '11.5px', color: '#c8d8e0' }}>
                    Deploy payload prepared.
                </p>
            )}
            {deployJson && onDeploy && (
                <button
                    onClick={() => onDeploy(deployJson.legs)}
                    style={{
                        marginTop: '10px', width: '100%', padding: '7px',
                        background: 'rgba(0,230,118,0.1)', border: '1px solid rgba(0,230,118,0.5)',
                        color: 'var(--green)', borderRadius: '3px', cursor: 'pointer',
                        fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', fontWeight: 700,
                        letterSpacing: '0.06em', transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,230,118,0.2)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'rgba(0,230,118,0.1)')}
                >
                    INJECT STRATEGY — {deployJson.strategy_name}
                </button>
            )}
        </div>
    );
};

const Chip: React.FC<{ text: string; onClick: () => void; variant?: 'preset' | 'followup' }> = ({ text, onClick, variant = 'followup' }) => (
    <button
        onClick={onClick}
        style={{
            border: variant === 'preset' ? '1px solid rgba(0,188,212,0.3)' : '1px solid rgba(0,230,118,0.22)',
            background: variant === 'preset' ? 'rgba(0,188,212,0.05)' : 'rgba(0,230,118,0.04)',
            color: variant === 'preset' ? 'var(--cyan)' : 'var(--green)',
            borderRadius: '3px', padding: '3px 9px', fontSize: '10px', cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace", whiteSpace: 'nowrap',
            transition: 'opacity 0.12s', letterSpacing: '0.01em',
        }}
        onMouseEnter={e => (e.currentTarget.style.opacity = '0.65')}
        onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
    >{text}</button>
);

// ── Main Component ────────────────────────────────────────────────────────────
export const AICopilot: React.FC<Props> = ({
    legs, strategyName, chainData, greeks, marketStatus, underlying = 'NSE:NIFTY50-INDEX', onDeployLegs,
}) => {
    const today = new Date();
    const expiry = chainData?.expiry || '';
    const dte = daysToExpiry(expiry);

    const initMessage = [
        '> MINIMAX M2.5 — QUANT ENGINE INITIALIZED',
        `> Date: ${today.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })} IST`,
        `> Expiry: ${expiry || 'Not loaded'} | DTE: ${dte} days`,
        `> Market: ${marketStatus?.status || 'Unknown'} ${marketStatus?.message ? '— ' + marketStatus.message : ''}`,
        '> Chain data feeds into every query automatically.',
        '> Paste a screenshot or ask a question to begin.',
    ].join('\n');

    const [messages, setMessages] = useState<(AIMessage & { image?: string })[]>([
        { role: 'assistant', content: initMessage },
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [thinking, setThinking] = useState(true);
    const [followups, setFollowups] = useState<string[]>([]);
    const [pendingImage, setPendingImage] = useState<{ b64: string; preview: string } | null>(null);
    const [isDragOver, setIsDragOver] = useState(false);
    const bottomRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        return () => {
            if (pendingImage?.preview) {
                URL.revokeObjectURL(pendingImage.preview);
            }
        };
    }, [pendingImage]);

    // Reinit header message when context changes
    useEffect(() => {
        const upd = [
            '> MINIMAX M2.5 — QUANT ENGINE INITIALIZED',
            `> Date: ${today.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })} IST`,
            `> Expiry: ${expiry || 'Not loaded'} | DTE: ${dte} days`,
            `> Market: ${marketStatus?.status || 'Unknown'} ${marketStatus?.message ? '— ' + marketStatus.message : ''}`,
            '> Chain data feeds into every query automatically.',
            '> Paste a screenshot or ask a question to begin.',
        ].join('\n');
        setMessages(prev =>
            prev.length === 1 && prev[0].content.startsWith('> MINIMAX')
                ? [{ role: 'assistant', content: upd }]
                : prev
        );
    }, [expiry, marketStatus?.status]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, followups, loading]);

    // Build rich text context
    const buildCtx = useCallback(() => {
        const parts: string[] = [];
        const now = new Date();
        parts.push('=== MARKET CONTEXT ===');
        parts.push(`Today: ${now.toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}`);
        parts.push(`IST Time: ${now.toLocaleTimeString('en-IN')}`);
        parts.push(`Market: ${marketStatus?.status || 'Unknown'} — ${marketStatus?.message || ''}`);
        if (expiry) { parts.push(`Expiry: ${expiry} | DTE: ${dte} calendar days`); }
        if (chainData) {
            parts.push(`Spot: ₹${chainData.spot} | Lot: ${chainData.lot_size} | Step: ${chainData.strike_step}`);
        }
        if (legs.length > 0) {
            parts.push('\n=== ACTIVE LEGS ===');
            parts.push(`Strategy: ${strategyName || 'Custom'}`);
            legs.forEach((l, i) => parts.push(
                `Leg ${i + 1}: ${l.side} ${l.qty}x ${l.strike} ${l.right} @ ₹${l.premium}` +
                (l.iv !== undefined && l.iv !== null ? ` IV:${(l.iv * 100).toFixed(1)}%` : '') +
                (l.delta !== undefined && l.delta !== null ? ` Δ:${l.delta}` : '')
            ));
        }
        if (greeks) {
            parts.push('\n=== PORTFOLIO GREEKS ===');
            parts.push(`Δ: ${greeks.delta} ${Math.abs(greeks.delta) < 0.1 ? '(near-neutral)' : '(directional)'}`);
            parts.push(`Γ: ${greeks.gamma} | Θ: ${greeks.theta}/day ${greeks.theta > 0 ? '(positive carry)' : '(negative carry)'}`);
            parts.push(`Vega: ${greeks.vega} ${greeks.vega < 0 ? '(short vol)' : '(long vol)'} | IV avg: ${(greeks.iv_avg * 100).toFixed(1)}%`);
        }
        return parts.join('\n');
    }, [legs, greeks, chainData, marketStatus, expiry, dte, strategyName]);

    // Image attachment handler
    const handleImageFile = useCallback(async (file: File) => {
        if (!file.type.startsWith('image/')) return;
        const b64 = await fileToBase64(file);
        const preview = URL.createObjectURL(file);
        setPendingImage({ b64, preview });
        inputRef.current?.focus();
    }, []);

    // Paste handler on input
    const handlePaste = useCallback((e: React.ClipboardEvent) => {
        const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/'));
        if (item) {
            e.preventDefault();
            const file = item.getAsFile();
            if (file) handleImageFile(file);
        }
    }, [handleImageFile]);

    // Drag handlers on panel
    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault(); setIsDragOver(false);
        const file = e.dataTransfer.files[0];
        if (file) handleImageFile(file);
    }, [handleImageFile]);

    const sendMessage = async (query: string) => {
        if (!query.trim() && !pendingImage) return;
        setFollowups([]);
        const imgB64 = pendingImage?.b64 || null;
        const imgPreview = pendingImage?.b64 || undefined;
        setPendingImage(null);

        const userMsg: AIMessage & { image?: string } = {
            role: 'user', content: query || '[Image attached — analyse it.]', image: imgPreview,
        };
        const chatHistory = [...messages, userMsg];
        setMessages(chatHistory);
        setInput('');
        setLoading(true);

        try {
            const ctx = buildCtx();
            const cleanHistory = chatHistory
                .filter(m => !m.content.startsWith('> MINIMAX'))
                .map(m => ({ role: m.role, content: m.content }));

            const res = await axios.post('/api/ai/chat', {
                query: query || 'Analyse the attached screenshot and act on what you see.',
                history: cleanHistory,
                context: ctx || null,
                current_legs: legs,
                thinking_enabled: thinking,
                ...(imgB64 ? { image_b64: imgB64 } : {}),
                underlying,
            });
            const reply = res.data.reply;
            setMessages(p => [...p, { role: 'assistant', content: reply }]);

            // Auto-deploy if AI recommends and handler exists
            const deployJson = extractDeployJson(reply);
            if (deployJson && onDeployLegs) {
                // Don't auto-inject — let user confirm via the button in AssistantBubble
            }

            setFollowups([...FOLLOWUP_POOL].sort(() => Math.random() - 0.5).slice(0, 3));
        } catch {
            setMessages(p => [...p, { role: 'assistant', content: '> ERROR: Backend connection failed.' }]);
        } finally {
            setLoading(false);
        }
    };

    const showPresets = messages.length <= 1;

    return (
        <div
            className="ai-panel"
            onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            style={isDragOver ? { outline: '2px dashed var(--green)', outlineOffset: '-2px' } : {}}
        >
            {/* Header */}
            <div className="ai-panel__head">
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                    <h3>▸ QUANT ENGINE</h3>
                    {expiry && (
                        <span style={{ fontSize: '9px', color: 'var(--muted)', fontFamily: "'JetBrains Mono', monospace" }}>
                            EXP: {expiry} · DTE: <span style={{ color: dte <= 3 ? '#ff1744' : dte <= 7 ? 'var(--amber)' : 'var(--green)' }}>{dte}d</span>
                        </span>
                    )}
                </div>
                <label className="thinking-toggle">
                    <input type="checkbox" checked={thinking} onChange={e => setThinking(e.target.checked)} />
                    thinking
                </label>
            </div>

            {/* Live context strip */}
            <div style={{ padding: '4px 10px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: '10px', flexWrap: 'wrap', fontSize: '9px', fontFamily: "'JetBrains Mono', monospace", color: 'var(--muted)' }}>
                <span>{today.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</span>
                {marketStatus && (
                    <span style={{ color: marketStatus.status === 'OPEN' ? 'var(--green)' : 'var(--amber)' }}>
                        ● {marketStatus.status}
                        {marketStatus.seconds_to_close ? ` · closes ${Math.floor(marketStatus.seconds_to_close / 60)}m` : marketStatus.seconds_to_open ? ` · opens ~${Math.floor(marketStatus.seconds_to_open / 60)}m` : ''}
                    </span>
                )}
                {chainData && <span>SPOT ₹{chainData.spot}</span>}
                {greeks && <span>Δ {greeks.delta} Θ {greeks.theta}/d V {greeks.vega}</span>}
                <span style={{ color: 'rgba(0,230,118,0.4)' }}>CHAIN LIVE</span>
            </div>

            {/* Messages */}
            <div className="ai-messages">
                {showPresets && (
                    <div style={{ padding: '8px 0 6px' }}>
                        <div style={{ fontSize: '8.5px', color: 'var(--muted)', letterSpacing: '0.1em', marginBottom: '6px', fontFamily: "'JetBrains Mono', monospace" }}>QUICK ANALYSIS</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                            {PRESET_QUERIES.map((q, i) => (
                                <Chip key={i} text={q.label} variant="preset" onClick={() => sendMessage(q.text)} />
                            ))}
                        </div>
                    </div>
                )}

                {messages.map((m, i) =>
                    m.role === 'user'
                        ? <UserBubble key={i} text={m.content} image={m.image} />
                        : <AssistantBubble key={i} text={m.content} onDeploy={onDeployLegs} />
                )}

                {loading && (
                    <div className="ai-thinking-glass">
                        <div className="ai-thinking-glass__shimmer" />
                        <div className="ai-thinking-glass__inner">
                            <span className="ai-thinking-glass__dots"><span /><span /><span /></span>
                            <span className="ai-thinking-glass__text">Thinking deeply...</span>
                        </div>
                    </div>
                )}

                {!loading && followups.length > 0 && (
                    <div style={{ padding: '3px 0 5px' }}>
                        <div style={{ fontSize: '8.5px', color: 'var(--muted)', letterSpacing: '0.1em', marginBottom: '5px', fontFamily: "'JetBrains Mono', monospace" }}>FOLLOW UP</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                            {followups.map((q, i) => <Chip key={i} text={q} variant="followup" onClick={() => sendMessage(q)} />)}
                        </div>
                    </div>
                )}
                <div ref={bottomRef} />
            </div>

            {/* Image preview */}
            {
                pendingImage && (
                    <div style={{ padding: '6px 10px', borderTop: '1px solid rgba(0,230,118,0.1)', display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(0,230,118,0.03)' }}>
                        <img src={pendingImage.preview} alt="pending" style={{ height: '40px', borderRadius: '3px', border: '1px solid rgba(0,230,118,0.3)' }} />
                        <span style={{ fontSize: '10px', color: 'var(--green)', fontFamily: "'JetBrains Mono', monospace" }}>Screenshot attached — add query or send directly</span>
                        <button onClick={() => setPendingImage(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: '14px' }}>✕</button>
                    </div>
                )
            }

            {/* Drop zone hint */}
            {
                isDragOver && (
                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,230,118,0.07)', display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', zIndex: 10, borderRadius: '4px' }}>
                        <span style={{ color: 'var(--green)', fontFamily: "'JetBrains Mono', monospace", fontSize: '13px' }}>Drop screenshot to analyse</span>
                    </div>
                )
            }

            {/* Input */}
            <div className="ai-input" style={{ flexDirection: 'column', gap: '5px' }}>
                <input
                    ref={inputRef}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
                    onPaste={handlePaste}
                    placeholder={pendingImage ? '> Add context for the screenshot...' : '> query / paste screenshot (Ctrl+V)...'}
                    disabled={loading}
                    style={{ flex: 1 }}
                />
                <div style={{ display: 'flex', gap: '5px' }}>
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: 'var(--muted)', padding: '3px 8px', borderRadius: '3px', cursor: 'pointer', fontSize: '10px', fontFamily: "'JetBrains Mono', monospace" }}
                        title="Attach screenshot"
                    >ATTACH</button>
                    <button className="btn btn--green btn--sm" onClick={() => sendMessage(input)} disabled={loading} style={{ flex: 1 }}>SEND</button>
                </div>
                <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={e => { const f = e.target.files?.[0]; if (f) handleImageFile(f); }} />
            </div>
        </div >
    );
};
