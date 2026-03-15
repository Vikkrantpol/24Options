import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { StrategySelector } from './components/StrategySelector';
import { PayoffChart } from './components/PayoffChart';
import { GreeksPanel } from './components/GreeksPanel';
import { OptionChainViewer } from './components/OptionChainViewer';
import { ScenarioAnalysis } from './components/ScenarioAnalysis';
import { AICopilot } from './components/AICopilot';
import { EnhancedMetricsBar } from './components/EnhancedMetricsBar';
import { StrikeOptimizer } from './components/StrikeOptimizer';
import { QuantEnginePanel } from './components/QuantEnginePanel';
import { ActiveStrategyIntel } from './components/ActiveStrategyIntel';
import { X } from 'lucide-react';
import type {
    StrategyTemplate, ConcreteLeg, PayoffDataPoint, GreeksSummary,
    StrategyMetrics, ChainData,
} from './types';

const API = '/api';
const RISK_FREE_RATE = 0.10;

// ── Paper Strategy Record ──────────────────────────────────
interface PaperStrategy {
    id: string;
    template_name: string;
    underlying: string;
    entry_time: string;
    exit_time?: string | null;
    status: string;
    unrealized_pnl: number;
    realized_pnl: number;
    legs: ConcreteLeg[];
}

interface StreamSnapshot {
    type: 'snapshot' | 'error';
    timestamp?: string;
    broker_connected?: boolean;
    chain?: ChainData;
    paper?: {
        strategies?: PaperStrategy[];
        positions?: any[];
        portfolio?: any;
    };
    message?: string;
}

function App() {
    // ── Core state ───────────────────────────────────────────
    const [strategies, setStrategies] = useState<StrategyTemplate[]>([]);
    const [selectedStrategy, setSelectedStrategy] = useState<StrategyTemplate | null>(null);
    const [legs, setLegs] = useState<ConcreteLeg[]>([]);
    const [payoffData, setPayoffData] = useState<PayoffDataPoint[]>([]);
    const [greeks, setGreeks] = useState<GreeksSummary | null>(null);
    const [metrics, setMetrics] = useState<StrategyMetrics | null>(null);
    const [chainData, setChainData] = useState<ChainData | null>(null);
    const [loading, setLoading] = useState(true);
    const [enhanced, setEnhanced] = useState<any>(null);
    const [marketStatus, setMarketStatus] = useState<any>(null);

    // ── Panel toggles ───────────────────────────────────────
    const [sidebarOpen, setSidebarOpen] = useState(() => {
        if (typeof window === 'undefined') return true;
        return window.innerWidth > 1180;
    });
    const [aiPanelOpen, setAiPanelOpen] = useState(false);
    const [rightWidth, setRightWidth] = useState(300);
    const [isDraggingRight, setIsDraggingRight] = useState(false);
    const [builderDeskMode, setBuilderDeskMode] = useState<'trade' | 'analysis'>('trade');

    const startResizingRight = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        const startX = e.clientX;
        const startWidth = rightWidth;
        setIsDraggingRight(true);

        const onMouseMove = (moveEvent: MouseEvent) => {
            const delta = startX - moveEvent.clientX;
            setRightWidth(Math.max(250, Math.min(800, startWidth + delta)));
        };

        const onMouseUp = () => {
            setIsDraggingRight(false);
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.body.style.cursor = 'default';
        };

        document.body.style.cursor = 'ew-resize';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    }, [rightWidth]);

    // ── Mode & monitoring ───────────────────────────────────
    const [brokerConnected, setBrokerConnected] = useState(false);
    const [streamConnected, setStreamConnected] = useState(false);
    const [activeTab, setActiveTab] = useState<'builder' | 'monitor' | 'quant'>('builder');
    const [paperStrategies, setPaperStrategies] = useState<PaperStrategy[]>([]);
    const [portfolio, setPortfolio] = useState<any>(null);
    const [underlying, setUnderlying] = useState('NSE:NIFTY50-INDEX');
    const [monitorSelectedStrategyId, setMonitorSelectedStrategyId] = useState<string | null>(null);
    const [monitorPayoffData, setMonitorPayoffData] = useState<PayoffDataPoint[]>([]);
    const [monitorGreeks, setMonitorGreeks] = useState<GreeksSummary | null>(null);
    const [monitorMetrics, setMonitorMetrics] = useState<StrategyMetrics | null>(null);
    const [monitorEnhanced, setMonitorEnhanced] = useState<any>(null);
    const monitorLastCalcAtRef = useRef(0);

    // ── Expiry selection ────────────────────────────────────
    const [expiries, setExpiries] = useState<string[]>([]);
    const [selectedExpiry, setSelectedExpiry] = useState('');
    const [positionMultiplier, setPositionMultiplier] = useState(1);

    // ── Custom builder ──────────────────────────────────────
    const [customStrike, setCustomStrike] = useState('');
    const [customRight, setCustomRight] = useState<'CE' | 'PE' | 'FUT'>('CE');
    const [customSide, setCustomSide] = useState<'BUY' | 'SELL'>('BUY');
    const [customQty, setCustomQty] = useState('');
    const [customPremium, setCustomPremium] = useState('');
    const effectiveLotSize = chainData?.lot_size || (underlying.includes('BANK') ? 30 : 65);

    const toExchangeSymbol = useCallback((symbolLike?: string) => {
        const value = String(symbolLike || '').toUpperCase();
        if (value.includes('BANK')) return 'NSE:NIFTYBANK-INDEX';
        if (value.includes('NIFTY')) return 'NSE:NIFTY50-INDEX';
        return underlying;
    }, [underlying]);

    const deriveDte = useCallback((expiry?: string) => {
        if (!expiry) return 7;
        const exp = new Date(`${expiry}T00:00:00`);
        if (Number.isNaN(exp.getTime())) return 7;
        const now = new Date();
        now.setHours(0, 0, 0, 0);
        const diffMs = exp.getTime() - now.getTime();
        return Math.max(Math.ceil(diffMs / 86_400_000), 0);
    }, []);

    const refreshMonitor = useCallback(async () => {
        try {
            const [posRes, portRes] = await Promise.all([
                axios.get(`${API}/paper/positions`),
                axios.get(`${API}/paper/portfolio`),
            ]);
            setPaperStrategies(posRes.data.strategies || []);
            setPortfolio(portRes.data);
        } catch (e) {
            console.error('Monitor error:', e);
        }
    }, []);

    // ── Load data on mount ──────────────────────────────────
    useEffect(() => {
        const load = async () => {
            try {
                const [stratRes, chainRes, healthRes] = await Promise.all([
                    axios.get(`${API}/strategies`),
                    axios.get(`${API}/chain`),
                    axios.get(`${API}/health`),
                ]);
                setStrategies(stratRes.data.strategies);
                setChainData(chainRes.data);
                setBrokerConnected(Boolean(healthRes.data.broker_connected && chainRes.data?.source === 'live'));

                const expList = chainRes.data.expiries || [];
                setExpiries(expList);
                if (expList.length > 0) {
                    const chainExpiry = chainRes.data.expiry;
                    const initialExpiry = chainExpiry && expList.includes(chainExpiry) ? chainExpiry : expList[0];
                    setSelectedExpiry(initialExpiry);
                }
            } catch (e) {
                console.error('Load error:', e);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    // ── Recalculate on leg changes ──────────────────────────
    const recalculate = useCallback(async (curLegs: ConcreteLeg[]) => {
        if (curLegs.length === 0) {
            setPayoffData([]); setGreeks(null); setMetrics(null);
            return;
        }
        const spot = chainData?.spot || 22500;
        try {
            const [pRes, gRes] = await Promise.all([
                axios.post(`${API}/pricing/payoff`, { spot_price: spot, legs: curLegs }),
                axios.post(`${API}/pricing/greeks`, {
                    spot_price: spot,
                    risk_free_rate: RISK_FREE_RATE,
                    legs: curLegs,
                    underlying,
                }),
            ]);
            setPayoffData(pRes.data.payoff);
            setMetrics(pRes.data.metrics);
            setGreeks(gRes.data);
        } catch (e) {
            console.error('Calc error:', e);
        }
    }, [chainData, underlying]);

    // ── Enhanced metrics polling ────────────────────────────
    useEffect(() => {
        const fetchEnhanced = async () => {
            if (legs.length === 0) { setEnhanced(null); return; }
            const spot = chainData?.spot || 22500;
            const dte = deriveDte(selectedExpiry || chainData?.expiry);
            try {
                const res = await axios.post(`${API}/pricing/enhanced-metrics`, {
                    spot_price: spot, legs, dte, risk_free_rate: RISK_FREE_RATE, underlying,
                });
                setEnhanced(res.data);
            } catch { /* silent */ }
        };
        fetchEnhanced();
    }, [legs, chainData, selectedExpiry, deriveDte, underlying]);

    // ── Market status polling (every 30s) ──────────────────
    useEffect(() => {
        const fetchMarket = async () => {
            try {
                const res = await axios.get(`${API}/market/status`);
                setMarketStatus(res.data);
            } catch { /* silent */ }
        };
        fetchMarket();
        const interval = setInterval(fetchMarket, 30_000);
        return () => clearInterval(interval);
    }, []);

    // ── Market stream via backend websocket (chain + paper MTM) ──────────
    useEffect(() => {
        let socket: WebSocket | null = null;
        let reconnectTimer: number | null = null;
        let intentionallyClosed = false;

        const connect = () => {
            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const params = new URLSearchParams({ symbol: underlying, strike_count: '15' });
            if (selectedExpiry) params.set('expiry', selectedExpiry);
            socket = new WebSocket(`${protocol}://${window.location.host}/ws/market-stream?${params.toString()}`);

            socket.onopen = () => setStreamConnected(true);
            socket.onmessage = (event) => {
                let payload: StreamSnapshot;
                try {
                    payload = JSON.parse(event.data);
                } catch {
                    return;
                }
                if (payload.type !== 'snapshot') return;

                if (typeof payload.broker_connected === 'boolean') {
                    setBrokerConnected(payload.broker_connected);
                }
                if (payload.chain) {
                    setChainData(payload.chain);
                    const expList = payload.chain.expiries || [];
                    setExpiries(expList);
                    if (expList.length > 0 && (!selectedExpiry || !expList.includes(selectedExpiry))) {
                        const chainExpiry = payload.chain.expiry;
                        const nextExpiry = chainExpiry && expList.includes(chainExpiry) ? chainExpiry : expList[0];
                        setSelectedExpiry(nextExpiry);
                    }
                }
                if (payload.paper) {
                    setPaperStrategies(payload.paper.strategies || []);
                    setPortfolio(payload.paper.portfolio || null);
                }
            };
            socket.onclose = () => {
                setStreamConnected(false);
                if (!intentionallyClosed) {
                    reconnectTimer = window.setTimeout(connect, 1500);
                }
            };
            socket.onerror = () => {
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.close();
                }
            };
        };

        connect();
        return () => {
            intentionallyClosed = true;
            setStreamConnected(false);
            if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
            if (socket) socket.close();
        };
    }, [underlying, selectedExpiry]);

    useEffect(() => { recalculate(legs); }, [legs, recalculate]);

    const selectedMonitorStrategy = paperStrategies.find(
        s => s.status === 'active' && s.id === monitorSelectedStrategyId,
    ) || null;

    const recalculateMonitor = useCallback(async (strategy: PaperStrategy | null) => {
        if (!strategy || !strategy.legs || strategy.legs.length === 0) {
            setMonitorPayoffData([]);
            setMonitorGreeks(null);
            setMonitorMetrics(null);
            setMonitorEnhanced(null);
            return;
        }

        const monitorLegs = strategy.legs.map(l => ({
            ...l,
            side: l.side as 'BUY' | 'SELL',
            right: l.right as 'CE' | 'PE' | 'FUT',
            strike: Number(l.strike),
            premium: Number(l.premium),
            qty: Number(l.qty),
            expiry: l.expiry || selectedExpiry || chainData?.expiry || '',
        }));
        const liveSpot = chainData?.spot || 22500;
        const monitorExpiry = monitorLegs[0]?.expiry || selectedExpiry || chainData?.expiry || '';
        const monitorDte = deriveDte(monitorExpiry);
        const monitorUnderlying = strategy.underlying || underlying;

        try {
            const [payoffRes, greeksRes, enhancedRes] = await Promise.all([
                axios.post(`${API}/pricing/payoff`, { spot_price: liveSpot, legs: monitorLegs }),
                axios.post(`${API}/pricing/greeks`, {
                    spot_price: liveSpot,
                    risk_free_rate: RISK_FREE_RATE,
                    legs: monitorLegs,
                    underlying: monitorUnderlying,
                }),
                axios.post(`${API}/pricing/enhanced-metrics`, {
                    spot_price: liveSpot,
                    legs: monitorLegs,
                    dte: monitorDte,
                    risk_free_rate: RISK_FREE_RATE,
                    underlying: monitorUnderlying,
                }),
            ]);
            setMonitorPayoffData(payoffRes.data.payoff || []);
            setMonitorMetrics(payoffRes.data.metrics || null);
            setMonitorGreeks(greeksRes.data || null);
            setMonitorEnhanced(enhancedRes.data || null);
        } catch (e) {
            console.error('Monitor analytics error:', e);
        }
    }, [chainData, selectedExpiry, deriveDte, underlying]);

    const handleMonitorScenario = async (ds: number, di: number, dd: number) => {
        if (!selectedMonitorStrategy || !selectedMonitorStrategy.legs || selectedMonitorStrategy.legs.length === 0) return;
        const monitorLegs = selectedMonitorStrategy.legs.map(l => ({
            ...l,
            side: l.side as 'BUY' | 'SELL',
            right: l.right as 'CE' | 'PE' | 'FUT',
            strike: Number(l.strike),
            premium: Number(l.premium),
            qty: Number(l.qty),
            expiry: l.expiry || selectedExpiry || chainData?.expiry || '',
        }));
        const liveSpot = chainData?.spot || 22500;
        if (ds === 0 && di === 0 && dd === 0) {
            void recalculateMonitor(selectedMonitorStrategy);
            return;
        }
        try {
            const res = await axios.post(`${API}/pricing/scenario`, {
                spot_price: liveSpot,
                legs: monitorLegs,
                delta_spot_pct: ds,
                delta_iv_points: di,
                delta_days: dd,
                risk_free_rate: RISK_FREE_RATE,
                underlying: selectedMonitorStrategy.underlying || underlying,
            });
            setMonitorPayoffData(res.data.payoff_curve || []);
            setMonitorGreeks(res.data.greeks || null);
        } catch (e) {
            console.error('Monitor scenario error:', e);
        }
    };

    const openSelectedInBuilder = () => {
        if (!selectedMonitorStrategy || !selectedMonitorStrategy.legs || selectedMonitorStrategy.legs.length === 0) return;

        const targetUnderlying = toExchangeSymbol(selectedMonitorStrategy.underlying);

        const copiedLegs: ConcreteLeg[] = selectedMonitorStrategy.legs.map(l => ({
            ...l,
            side: l.side as 'BUY' | 'SELL',
            right: l.right as 'CE' | 'PE' | 'FUT',
            strike: Number(l.strike),
            premium: Number(l.premium),
            qty: Number(l.qty),
            expiry: l.expiry || selectedExpiry || chainData?.expiry || '',
        }));

        setSelectedStrategy(null);
        if (targetUnderlying !== underlying) {
            setUnderlying(targetUnderlying);
        }
        setLegs(copiedLegs);
        setActiveTab('builder');
    };

    useEffect(() => {
        const active = paperStrategies.filter(s => s.status === 'active');
        if (active.length === 0) {
            setMonitorSelectedStrategyId(null);
            setMonitorPayoffData([]);
            setMonitorGreeks(null);
            setMonitorMetrics(null);
            setMonitorEnhanced(null);
            return;
        }
        if (!monitorSelectedStrategyId || !active.some(s => s.id === monitorSelectedStrategyId)) {
            setMonitorSelectedStrategyId(active[0].id);
        }
    }, [paperStrategies, monitorSelectedStrategyId]);

    useEffect(() => {
        if (!selectedMonitorStrategy) return;
        void recalculateMonitor(selectedMonitorStrategy);
    }, [monitorSelectedStrategyId, recalculateMonitor]);

    useEffect(() => {
        if (activeTab !== 'monitor' || !selectedMonitorStrategy) return;
        const now = Date.now();
        if (now - monitorLastCalcAtRef.current < 1200) return;
        monitorLastCalcAtRef.current = now;
        void recalculateMonitor(selectedMonitorStrategy);
    }, [chainData?.spot, activeTab, selectedMonitorStrategy, recalculateMonitor]);

    const handleSelectStrategy = async (s: StrategyTemplate) => {
        setSelectedStrategy(s);
        try {
            const res = await axios.post(`${API}/strategies/resolve`, {
                template_id: s.id,
                underlying: underlying,
                spot_price: chainData?.spot || 22500,
                strike_step: chainData?.strike_step || 100,
                lot_size: effectiveLotSize,
                num_lots: Math.max(positionMultiplier, 1),
                expiry: selectedExpiry || chainData?.expiry || '',
            });
            setLegs(res.data.legs);
            setMetrics(res.data.metrics);
            setGreeks(res.data.greeks);
        } catch (e) {
            console.error('Resolve error:', e);
        }
    };

    useEffect(() => {
        if (!selectedStrategy) return;
        void handleSelectStrategy(selectedStrategy);
    }, [positionMultiplier]);

    // ── Leg management ──────────────────────────────────────
    const addLeg = (leg: ConcreteLeg) => {
        setSelectedStrategy(null);
        setLegs(prev => [...prev, leg]);
    };

    const applyExternalLegs = useCallback((incoming: any[]) => {
        if (!Array.isArray(incoming) || incoming.length === 0) return;
        const normalized: ConcreteLeg[] = incoming
            .map((raw) => {
                const sideRaw = String(raw?.side || 'BUY').toUpperCase();
                const rightRaw = String(raw?.right || 'CE').toUpperCase();
                const side: 'BUY' | 'SELL' = sideRaw === 'SELL' ? 'SELL' : 'BUY';
                const right: 'CE' | 'PE' | 'FUT' = rightRaw === 'PE' || rightRaw === 'FUT' ? rightRaw : 'CE';

                const strike = Number(raw?.strike ?? (chainData?.spot || 0));
                const premium = Number(raw?.premium ?? 0);
                const qty = Math.max(Number(raw?.qty ?? effectiveLotSize), 1);
                const expiry = String(raw?.expiry || selectedExpiry || chainData?.expiry || '');

                if (!Number.isFinite(strike) || strike <= 0 || !Number.isFinite(premium)) {
                    return null;
                }

                return {
                    side,
                    right,
                    strike,
                    premium,
                    qty,
                    expiry,
                } as ConcreteLeg;
            })
            .filter((x): x is ConcreteLeg => Boolean(x));

        if (normalized.length === 0) return;
        setSelectedStrategy(null);
        setLegs(normalized);
        setActiveTab('builder');
    }, [chainData?.spot, chainData?.expiry, effectiveLotSize, selectedExpiry]);

    const removeLeg = (idx: number) => setLegs(prev => prev.filter((_, i) => i !== idx));
    const clearLegs = () => { setLegs([]); setSelectedStrategy(null); };

    // ── Custom leg builder ──────────────────────────────────
    const addCustomLeg = () => {
        const strike = customRight === 'FUT' ? (chainData?.spot || 22500) : parseFloat(customStrike);
        const prem = parseFloat(customPremium);
        const typedQty = parseInt(customQty, 10);
        const baseQty = Number.isFinite(typedQty) && typedQty > 0 ? typedQty : effectiveLotSize;
        const qty = baseQty * Math.max(positionMultiplier, 1);
        if (customRight !== 'FUT' && isNaN(strike)) return;
        if (isNaN(prem)) return;
        addLeg({
            side: customSide,
            right: customRight,
            strike,
            premium: prem,
            qty,
            expiry: selectedExpiry || chainData?.expiry || '',
        });
        setCustomStrike('');
        setCustomPremium('');
    };

    // ── Scenario analysis ──────────────────────────────────
    const handleScenario = async (ds: number, di: number, dd: number) => {
        if (legs.length === 0) return;
        const spot = chainData?.spot || 22500;
        if (ds === 0 && di === 0 && dd === 0) { recalculate(legs); return; }
        try {
            const res = await axios.post(`${API}/pricing/scenario`, {
                spot_price: spot, legs, delta_spot_pct: ds, delta_iv_points: di,
                delta_days: dd, risk_free_rate: RISK_FREE_RATE, underlying,
            });
            setPayoffData(res.data.payoff_curve);
            setGreeks(res.data.greeks);
        } catch (e) {
            console.error('Scenario error:', e);
        }
    };

    // ── Paper trading ───────────────────────────────────────
    const deployPaper = async () => {
        if (legs.length === 0) return;
        try {
            const sym = underlying.includes('BANK') ? 'BANKNIFTY' : 'NIFTY';
            const res = await axios.post(`${API}/paper/open-custom`, {
                legs,
                underlying: sym,
                spot_price: chainData?.spot || 22500,
                strategy_name: selectedStrategy?.name || 'Custom Strategy',
            });
            if (res.data.status === 'opened') {
                refreshMonitor();
                setActiveTab('monitor');
            }
        } catch (e) {
            console.error('Paper deploy error:', e);
        }
    };

    const deployBroker = async () => {
        if (legs.length === 0 || !brokerConnected) return;
        try {
            const sym = underlying.includes('BANK') ? 'BANKNIFTY' : 'NIFTY';
            await axios.post(`${API}/broker/deploy`, {
                legs: legs.map(l => ({
                    side: l.side, right: l.right, strike: l.strike,
                    qty: l.qty, premium: l.premium,
                })),
                underlying: sym,
                strategy_name: selectedStrategy?.name || 'Custom',
            });
            alert('Strategy deployed to broker!');
        } catch (e) {
            console.error('Broker deploy error:', e);
        }
    };

    const closePaperStrategy = async (strategy: PaperStrategy) => {
        try {
            const strategySymbol = toExchangeSymbol(strategy.underlying);
            const strategyExpiry = strategy.legs?.[0]?.expiry || '';
            let closeSpot = chainData?.spot || 22500;

            if ((chainData?.symbol || underlying) !== strategySymbol) {
                const params = new URLSearchParams({ symbol: strategySymbol, strike_count: '15' });
                if (strategyExpiry) params.set('expiry', strategyExpiry);
                const chainRes = await axios.get(`${API}/chain?${params.toString()}`);
                const fetchedSpot = Number(chainRes.data?.spot || 0);
                if (fetchedSpot > 0) {
                    closeSpot = fetchedSpot;
                }
            }

            await axios.post(`${API}/paper/close/${strategy.id}?spot_price=${closeSpot}`);
            if (monitorSelectedStrategyId === strategy.id) {
                setMonitorSelectedStrategyId(null);
            }
            refreshMonitor();
        } catch (e) {
            console.error('Close error:', e);
        }
    };

    const handleUnderlyingChange = (newSymbol: string) => {
        setUnderlying(newSymbol);
        setLegs([]);
        setSelectedStrategy(null);
        setSelectedExpiry('');
        setCustomQty('');
    };

    // ── Expiry change ───────────────────────────────────────
    const handleExpiryChange = (exp: string) => {
        setSelectedExpiry(exp);
    };

    // ── Loading screen ──────────────────────────────────────
    if (loading) {
        return (
            <div className="loading-screen">
                <div className="loading-text">{'> INITIALIZING 24 OPTIONS ENGINE...'}</div>
            </div>
        );
    }

    const spot = chainData?.spot || 22500;
    const quoteFeed = chainData?.quote_feed || 'mock';
    const quoteFeedLabel = quoteFeed === 'live-stream'
        ? 'LIVE STREAM'
        : quoteFeed === 'live-poll'
            ? 'LIVE POLL'
            : 'MOCK FEED';
    const lastTickAgeMs = chainData?.last_tick_age_ms ?? chainData?.tick_age_ms;
    const tickAgeLabel = typeof lastTickAgeMs === 'number' ? `${lastTickAgeMs}ms` : '--';
    const modeLabel = quoteFeed === 'mock' ? '● PAPER DATA' : '● LIVE DATA (PAPER)';
    const monitorLegsForAi: ConcreteLeg[] = selectedMonitorStrategy?.legs?.map(l => ({
        ...l,
        side: l.side as 'BUY' | 'SELL',
        right: l.right as 'CE' | 'PE' | 'FUT',
        strike: Number(l.strike),
        premium: Number(l.premium),
        qty: Number(l.qty),
        expiry: l.expiry || selectedExpiry || chainData?.expiry || '',
    })) || [];
    const aiLegs = activeTab === 'monitor' ? monitorLegsForAi : legs;
    const aiGreeks = activeTab === 'monitor' ? monitorGreeks : greeks;
    const aiUnderlying = activeTab === 'monitor' && selectedMonitorStrategy
        ? toExchangeSymbol(selectedMonitorStrategy.underlying)
        : underlying;
    const aiStrategyName = activeTab === 'monitor' && selectedMonitorStrategy
        ? `${selectedMonitorStrategy.template_name} (MONITOR)`
        : (selectedStrategy?.name || 'Custom');
    const builderExpiry = selectedExpiry || chainData?.expiry || '';
    const builderDte = deriveDte(builderExpiry);

    return (
        <div className="app-shell">
            {/* LEFT SIDEBAR — Strategy Selector (collapsible) */}
            <div className={`sidebar ${sidebarOpen ? '' : 'sidebar--collapsed'}`}>
                <StrategySelector
                    strategies={strategies}
                    selectedId={selectedStrategy?.id || null}
                    underlying={underlying}
                    onSelect={handleSelectStrategy}
                />
            </div>

            {/* MAIN CONTENT */}
            <div className="main-area">
                {/* TOP BAR */}
                <div className="topbar">
                    <div className="topbar__left">
                        <button className="toggle-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
                            {sidebarOpen ? '◂' : '▸'} STR
                        </button>
                        <div className="topbar__brand">
                            <div className="topbar__brand-dot" />
                            24OPTS
                        </div>
                    </div>

                    <div className="topbar__center">
                        <select
                            className="bg-transparent text-green border-none outline-none mr-2"
                            style={{ background: 'transparent', color: 'var(--green)', border: 'none', appearance: 'none', outline: 'none', marginRight: '16px', fontWeight: 'bold' }}
                            value={underlying}
                            onChange={e => handleUnderlyingChange(e.target.value)}
                        >
                            <option value="NSE:NIFTY50-INDEX">NIFTY</option>
                            <option value="NSE:NIFTYBANK-INDEX">BANKNIFTY</option>
                        </select>
                        <div className="topbar__stat">
                            SPOT <strong>₹{spot.toLocaleString()}</strong>
                        </div>
                        <div className="topbar__stat">
                            EXP
                            <select
                                className="expiry-select"
                                value={selectedExpiry}
                                onChange={e => handleExpiryChange(e.target.value)}
                            >
                                {expiries.map(exp => (
                                    <option key={exp} value={exp}>{exp}</option>
                                ))}
                            </select>
                        </div>
                        <div className="topbar__stat">
                            LOT <strong>{effectiveLotSize}</strong>
                        </div>
                    </div>

                    <div className="topbar__right">
                        <span className={`mode-badge ${brokerConnected ? 'mode-badge--live' : 'mode-badge--paper'}`}>
                            {modeLabel}
                            {streamConnected ? ' · WS ON' : ' · WS OFF'}
                            {` · ${quoteFeedLabel}`}
                            {` · AGE ${tickAgeLabel}`}
                        </span>
                        <button className="toggle-btn" onClick={() => setAiPanelOpen(!aiPanelOpen)}>
                            AI {aiPanelOpen ? '▸' : '◂'}
                        </button>
                    </div>
                </div>

                {/* TAB BAR */}
                <div className="tab-bar">
                    <button className={`tab-btn ${activeTab === 'builder' ? 'tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('builder')}>
                        ▸ Builder
                    </button>
                    <button className={`tab-btn ${activeTab === 'monitor' ? 'tab-btn--active' : ''}`}
                        onClick={() => { setActiveTab('monitor'); refreshMonitor(); }}>
                        ▸ Monitor
                    </button>
                    <button className={`tab-btn ${activeTab === 'quant' ? 'tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('quant')}>
                        ▸ Quant
                    </button>
                </div>

                {/* CONTENT */}
                <div className="content-scroll">
                    {activeTab === 'builder' ? (
                        <div className="builder-layout">
                            <div className="builder-market-pane">
                                {chainData && (
                                    <OptionChainViewer
                                        chain={chainData.chain}
                                        spot={chainData.spot}
                                        expiry={builderExpiry || chainData.expiry}
                                        lotSize={effectiveLotSize}
                                        lotMultiplier={Math.max(positionMultiplier, 1)}
                                        onAddLeg={addLeg}
                                    />
                                )}
                            </div>

                            <div className="builder-workbench">
                                <div className="builder-stage-tabs">
                                    <button
                                        className={`builder-stage-tab ${builderDeskMode === 'trade' ? 'builder-stage-tab--active' : ''}`}
                                        onClick={() => setBuilderDeskMode('trade')}
                                    >
                                        Trade Desk
                                    </button>
                                    <button
                                        className={`builder-stage-tab ${builderDeskMode === 'analysis' ? 'builder-stage-tab--active' : ''}`}
                                        onClick={() => setBuilderDeskMode('analysis')}
                                    >
                                        Risk Lab
                                    </button>
                                    <button
                                        className="builder-stage-link"
                                        onClick={() => setActiveTab('quant')}
                                    >
                                        Quant Workflow
                                    </button>
                                </div>

                                {builderDeskMode === 'trade' ? (
                                    <>
                                        <div className="panel builder-brief">
                                            <div className="panel__header">
                                                <span className="panel__title">▸ DESK SUMMARY</span>
                                                <span className="btn btn--xs">
                                                    {selectedStrategy ? `#${selectedStrategy.id} ${selectedStrategy.category}` : 'CUSTOM BOOK'}
                                                </span>
                                            </div>
                                            <div className="panel__body">
                                                <div className="builder-brief-grid">
                                                    <div className="builder-brief-card">
                                                        <span className="builder-brief-card__label">Strategy</span>
                                                        <strong>{selectedStrategy?.name || 'Custom Structure'}</strong>
                                                    </div>
                                                    <div className="builder-brief-card">
                                                        <span className="builder-brief-card__label">Underlying</span>
                                                        <strong>{underlying.includes('BANK') ? 'BANKNIFTY' : 'NIFTY'}</strong>
                                                    </div>
                                                    <div className="builder-brief-card">
                                                        <span className="builder-brief-card__label">Spot / DTE</span>
                                                        <strong>₹{spot.toLocaleString()} · {builderDte}d</strong>
                                                    </div>
                                                    <div className="builder-brief-card">
                                                        <span className="builder-brief-card__label">Working Legs</span>
                                                        <strong>{legs.length}</strong>
                                                    </div>
                                                </div>
                                                {selectedStrategy && (
                                                    <div className="builder-brief-notes">
                                                        <p>{selectedStrategy.description}</p>
                                                        <div className="builder-brief-tags">
                                                            <span>View: {selectedStrategy.primary_view}</span>
                                                            <span>Risk: {selectedStrategy.max_risk}</span>
                                                            <span>Reward: {selectedStrategy.max_reward}</span>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>

                                        <div className="panel">
                                            <div className="panel__header">
                                                <span className="panel__title">
                                                    ▸ ORDER TICKET
                                                    {selectedStrategy && (
                                                        <span style={{ color: 'var(--cyan)', fontWeight: 400, marginLeft: 6 }}>
                                                            — {selectedStrategy.name}
                                                        </span>
                                                    )}
                                                </span>
                                                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                                    {selectedStrategy && (
                                                        <StrikeOptimizer
                                                            templateId={selectedStrategy?.id ?? null}
                                                            underlying={underlying}
                                                            spotPrice={spot}
                                                            expiry={builderExpiry}
                                                            lotSize={effectiveLotSize * Math.max(positionMultiplier, 1)}
                                                            dte={builderDte}
                                                            onApply={(newLegs) => setLegs(newLegs)}
                                                        />
                                                    )}
                                                    {legs.length > 0 && (
                                                        <>
                                                            <button className="btn btn--green btn--sm" onClick={deployPaper}>
                                                                DEPLOY PAPER
                                                            </button>
                                                            <button className="btn btn--xs" onClick={clearLegs}>CLEAR</button>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="panel__body">
                                                <div className="builder-controls builder-controls--ticket">
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Lots Mult</span>
                                                        <input
                                                            type="number"
                                                            min={1}
                                                            step={1}
                                                            className="builder-input"
                                                            value={positionMultiplier}
                                                            onChange={e => setPositionMultiplier(Math.max(parseInt(e.target.value || '1', 10) || 1, 1))}
                                                        />
                                                    </label>
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Side</span>
                                                        <select
                                                            className="builder-input builder-input--select"
                                                            value={customSide}
                                                            onChange={e => setCustomSide(e.target.value as any)}
                                                        >
                                                            <option value="BUY">BUY</option>
                                                            <option value="SELL">SELL</option>
                                                        </select>
                                                    </label>
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Strike</span>
                                                        <input
                                                            className="builder-input"
                                                            placeholder="Strike"
                                                            disabled={customRight === 'FUT'}
                                                            value={customStrike}
                                                            onChange={e => setCustomStrike(e.target.value)}
                                                        />
                                                    </label>
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Instrument</span>
                                                        <select
                                                            className="builder-input builder-input--select"
                                                            value={customRight}
                                                            onChange={e => {
                                                                const val = e.target.value as any;
                                                                setCustomRight(val);
                                                                if (val === 'FUT') {
                                                                    const p = chainData?.spot || 22500;
                                                                    setCustomPremium(p.toString());
                                                                    setCustomStrike(p.toString());
                                                                }
                                                            }}
                                                        >
                                                            <option value="CE">CE</option>
                                                            <option value="PE">PE</option>
                                                            <option value="FUT">FUT</option>
                                                        </select>
                                                    </label>
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Quantity</span>
                                                        <input
                                                            className="builder-input"
                                                            placeholder={`Qty (${effectiveLotSize})`}
                                                            value={customQty}
                                                            onChange={e => setCustomQty(e.target.value)}
                                                        />
                                                    </label>
                                                    <label className="desk-field">
                                                        <span className="desk-field__label">Premium</span>
                                                        <input
                                                            className="builder-input"
                                                            placeholder="Premium"
                                                            value={customPremium}
                                                            onChange={e => setCustomPremium(e.target.value)}
                                                        />
                                                    </label>
                                                    <div className="desk-field desk-field--action">
                                                        <span className="desk-field__label">Route</span>
                                                        <button className="btn btn--cyan btn--sm" onClick={addCustomLeg}>+ ADD LEG</button>
                                                    </div>
                                                </div>

                                                {legs.length === 0 ? (
                                                    <div className="empty builder-empty-state">
                                                        <p>Click directly in the chain to stage legs, or key in a manual ticket.</p>
                                                    </div>
                                                ) : (
                                                    <div>
                                                        {legs.map((leg, idx) => (
                                                            <div key={idx} className="leg-row">
                                                                <span className={`leg-badge leg-badge--${leg.side.toLowerCase()}`}>
                                                                    {leg.side}
                                                                </span>
                                                                <div className="leg-info">
                                                                    <span className="leg-info__qty">{leg.qty}</span>
                                                                    <span className="leg-info__strike">{leg.strike}</span>
                                                                    <span className="leg-info__right">{leg.right}</span>
                                                                    <span className="leg-info__prem">₹{leg.premium.toFixed(1)}</span>
                                                                    {leg.iv && (
                                                                        <span style={{ color: 'var(--text-3)', fontSize: 10 }}>
                                                                            IV:{(leg.iv * 100).toFixed(1)}%
                                                                        </span>
                                                                    )}
                                                                </div>
                                                                <button className="leg-remove" onClick={() => removeLeg(idx)}>
                                                                    <X size={12} />
                                                                </button>
                                                            </div>
                                                        ))}

                                                        {metrics && (
                                                            <div className="metrics-strip" style={{ marginTop: 8 }}>
                                                                <div className="metric-cell">
                                                                    <span className="metric-cell__label">Max Profit</span>
                                                                    <span className="metric-cell__val val--pos">
                                                                        +₹{metrics.max_profit.toLocaleString()}
                                                                    </span>
                                                                </div>
                                                                <div className="metric-cell">
                                                                    <span className="metric-cell__label">Max Loss</span>
                                                                    <span className="metric-cell__val val--neg">
                                                                        ₹{metrics.max_loss.toLocaleString()}
                                                                    </span>
                                                                </div>
                                                                <div className="metric-cell">
                                                                    <span className="metric-cell__label">Net Prem</span>
                                                                    <span className={`metric-cell__val ${metrics.net_premium >= 0 ? 'val--pos' : 'val--neg'}`}>
                                                                        {metrics.net_premium >= 0 ? '+' : ''}₹{metrics.net_premium.toLocaleString()}
                                                                    </span>
                                                                </div>
                                                                <div className="metric-cell">
                                                                    <span className="metric-cell__label">Breakeven</span>
                                                                    <span className="metric-cell__val" style={{ color: 'var(--amber)', fontSize: 11 }}>
                                                                        {metrics.breakevens.map(b => b.toLocaleString()).join(' | ') || '—'}
                                                                    </span>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="panel">
                                            <div className="panel__header">
                                                <span className="panel__title">▸ LIVE METRICS</span>
                                                <span className="btn btn--xs">{builderExpiry || 'NO EXPIRY'}</span>
                                            </div>
                                            <EnhancedMetricsBar
                                                enhanced={enhanced}
                                                market={marketStatus}
                                                spot={spot}
                                            />
                                        </div>
                                        <GreeksPanel greeks={greeks} />
                                        <PayoffChart
                                            data={payoffData}
                                            spotPrice={spot}
                                            metrics={metrics}
                                            strategyName={selectedStrategy?.name || ''}
                                        />
                                        <ScenarioAnalysis onScenarioChange={handleScenario} />
                                    </>
                                )}
                            </div>
                        </div>
                    ) : activeTab === 'monitor' ? (
                        /* MONITOR TAB */
                        <div style={{ maxWidth: 900, margin: '0 auto' }}>
                            {/* Portfolio Summary */}
                            {portfolio && (
                                <div className="panel" style={{ marginBottom: 12 }}>
                                    <div className="panel__header">
                                        <span className="panel__title">▸ PORTFOLIO</span>
                                        <button className="btn btn--xs btn--cyan" onClick={refreshMonitor}>REFRESH</button>
                                    </div>
                                    <div className="panel__body">
                                        <div className="metrics-strip">
                                            <div className="metric-cell">
                                                <span className="metric-cell__label">Capital</span>
                                                <span className="metric-cell__val">₹{(portfolio.capital || 0).toLocaleString()}</span>
                                            </div>
                                            <div className="metric-cell">
                                                <span className="metric-cell__label">Total P&L</span>
                                                <span className={`metric-cell__val ${(portfolio.total_pnl || 0) >= 0 ? 'val--pos' : 'val--neg'}`}>
                                                    {(portfolio.total_pnl || 0) >= 0 ? '+' : ''}₹{(portfolio.total_pnl || 0).toLocaleString()}
                                                </span>
                                            </div>
                                            <div className="metric-cell">
                                                <span className="metric-cell__label">Active</span>
                                                <span className="metric-cell__val">{portfolio.active_strategies || 0}</span>
                                            </div>
                                            <div className="metric-cell">
                                                <span className="metric-cell__label">Closed</span>
                                                <span className="metric-cell__val">{portfolio.closed_strategies || 0}</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Active Strategies */}
                            <div className="panel">
                                <div className="panel__header">
                                    <span className="panel__title">▸ ACTIVE STRATEGIES</span>
                                </div>
                                <div className="monitor-list">
                                    {paperStrategies.filter(s => s.status === 'active').length === 0 ? (
                                        <div className="empty">
                                            <p>No active strategies. Deploy from the Builder tab.</p>
                                        </div>
                                    ) : (
                                        paperStrategies.filter(s => s.status === 'active').map(s => {
                                            const isSelected = monitorSelectedStrategyId === s.id;
                                            return (
                                            <div
                                                key={s.id}
                                                className="monitor-card"
                                                onClick={() => {
                                                    const strategySymbol = toExchangeSymbol(s.underlying);
                                                    if (strategySymbol !== underlying) {
                                                        setUnderlying(strategySymbol);
                                                    }
                                                    setMonitorSelectedStrategyId(s.id);
                                                }}
                                                style={{
                                                    cursor: 'pointer',
                                                    borderColor: isSelected ? 'rgba(0,230,118,0.45)' : undefined,
                                                    boxShadow: isSelected ? '0 0 0 1px rgba(0,230,118,0.15) inset' : undefined,
                                                }}
                                            >
                                                <div className="monitor-card__head">
                                                    <span className="monitor-card__name">{s.template_name}</span>
                                                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                                        <span className={`monitor-card__pnl ${s.unrealized_pnl >= 0 ? 'val--pos' : 'val--neg'}`}>
                                                            {s.unrealized_pnl >= 0 ? '+' : ''}₹{s.unrealized_pnl.toLocaleString()}
                                                        </span>
                                                        <button
                                                            className="btn btn--red btn--xs"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                closePaperStrategy(s);
                                                            }}
                                                        >
                                                            EXIT
                                                        </button>
                                                    </div>
                                                </div>
                                                <div className="monitor-card__legs">
                                                    {s.legs.map((l: any, i: number) => (
                                                        <div key={i}>
                                                            {l.side} {l.qty}x {l.strike} {l.right} @ ₹{l.premium}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )})
                                    )}
                                </div>
                            </div>

                            {/* Selected Strategy Live Analytics */}
                            {selectedMonitorStrategy && (
                                <div style={{ marginTop: 12 }}>
                                    <PayoffChart
                                        data={monitorPayoffData}
                                        spotPrice={spot}
                                        metrics={monitorMetrics}
                                        strategyName={`${selectedMonitorStrategy.template_name} (LIVE)`}
                                    />
                                    <EnhancedMetricsBar
                                        enhanced={monitorEnhanced}
                                        market={marketStatus}
                                        spot={spot}
                                    />
                                    <GreeksPanel greeks={monitorGreeks} />
                                    <ScenarioAnalysis
                                        key={`monitor-scenario-${selectedMonitorStrategy.id}`}
                                        onScenarioChange={handleMonitorScenario}
                                    />
                                    <ActiveStrategyIntel
                                        strategyName={selectedMonitorStrategy.template_name}
                                        underlying={toExchangeSymbol(selectedMonitorStrategy.underlying)}
                                        legs={monitorLegsForAi}
                                        chainData={chainData}
                                        currentPop={typeof monitorEnhanced?.pop === 'number' ? monitorEnhanced.pop : null}
                                        onApplyLegs={applyExternalLegs}
                                    />
                                    <div className="panel" style={{ marginTop: 12 }}>
                                        <div className="panel__header">
                                            <span className="panel__title">▸ POSITION DETAILS</span>
                                            <button
                                                className="btn btn--xs btn--cyan"
                                                onClick={openSelectedInBuilder}
                                            >
                                                OPEN SELECTED IN BUILDER
                                            </button>
                                        </div>
                                        <div className="monitor-list">
                                            <div className="monitor-card" style={{ marginBottom: 0 }}>
                                                <div className="monitor-card__head">
                                                    <span className="monitor-card__name">{selectedMonitorStrategy.template_name}</span>
                                                    <span className={`monitor-card__pnl ${selectedMonitorStrategy.unrealized_pnl >= 0 ? 'val--pos' : 'val--neg'}`}>
                                                        {selectedMonitorStrategy.unrealized_pnl >= 0 ? '+' : ''}₹{selectedMonitorStrategy.unrealized_pnl.toLocaleString()}
                                                    </span>
                                                </div>
                                                <div className="monitor-card__legs">
                                                    <div>Underlying: {selectedMonitorStrategy.underlying}</div>
                                                    <div>Entry: {new Date(selectedMonitorStrategy.entry_time).toLocaleString('en-IN')}</div>
                                                    {selectedMonitorStrategy.legs.map((l: any, i: number) => (
                                                        <div key={i}>
                                                            {l.side} {l.qty}x {l.strike} {l.right} @ ₹{l.premium}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Closed Strategies */}
                            <div className="panel" style={{ marginTop: 12 }}>
                                <div className="panel__header">
                                    <span className="panel__title">▸ CLOSED TRADES</span>
                                </div>
                                <div className="monitor-list">
                                    {paperStrategies.filter(s => s.status === 'closed').length === 0 ? (
                                        <div className="empty">
                                            <p>No closed trades yet.</p>
                                        </div>
                                    ) : (
                                        paperStrategies
                                            .filter(s => s.status === 'closed')
                                            .map(s => (
                                                <div key={s.id} className="monitor-card" style={{ opacity: 0.7 }}>
                                                    <div className="monitor-card__head">
                                                        <span className="monitor-card__name">{s.template_name}</span>
                                                        <span className={`monitor-card__pnl ${s.realized_pnl >= 0 ? 'val--pos' : 'val--neg'}`}>
                                                            {s.realized_pnl >= 0 ? '+' : ''}₹{s.realized_pnl.toLocaleString()}
                                                        </span>
                                                    </div>
                                                    <div className="monitor-card__legs">
                                                        <div>Underlying: {s.underlying}</div>
                                                        <div>Closed: {s.exit_time ? new Date(s.exit_time).toLocaleString('en-IN') : 'n/a'}</div>
                                                    </div>
                                                </div>
                                            ))
                                    )}
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* QUANT TAB */
                        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
                            <QuantEnginePanel
                                underlying={underlying}
                                chainData={chainData}
                                currentLegs={legs}
                                onApplyLegs={applyExternalLegs}
                            />
                            <div className="panel" style={{ marginTop: 12 }}>
                                <div className="panel__header">
                                    <span className="panel__title">▸ QUANT WORKFLOW</span>
                                </div>
                                <div className="panel__body" style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.8 }}>
                                    <p><span style={{ color: 'var(--text-3)' }}>1.</span> Set profile (risk mode, target delta/vega, slice size).</p>
                                    <p><span style={{ color: 'var(--text-3)' }}>2.</span> Run <span style={{ color: 'var(--green)' }}>REGIME</span> and <span style={{ color: 'var(--green)' }}>ADAPTIVE PICK</span>, then load legs.</p>
                                    <p><span style={{ color: 'var(--text-3)' }}>3.</span> Validate with <span style={{ color: 'var(--green)' }}>SCORE CURRENT</span> and <span style={{ color: 'var(--green)' }}>PLAN CURRENT</span>.</p>
                                    <p><span style={{ color: 'var(--text-3)' }}>4.</span> Use <span style={{ color: 'var(--green)' }}>OPTIMIZE</span> / <span style={{ color: 'var(--green)' }}>ADJUSTMENTS</span> for live portfolio management.</p>
                                    <p><span style={{ color: 'var(--text-3)' }}>5.</span> Start autopilot in <span style={{ color: 'var(--amber)' }}>paper mode</span>, monitor journal, then scale carefully.</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* RIGHT PANEL — AI Copilot (collapsible) */}
            <div
                className={`right-panel ${aiPanelOpen ? '' : 'right-panel--collapsed'}`}
                style={aiPanelOpen ? {
                    width: rightWidth,
                    minWidth: rightWidth,
                    transition: isDraggingRight ? 'none' : 'width 0.3s ease, min-width 0.3s ease, opacity 0.3s ease'
                } : {}}
            >
                <div className="resizer-left" onMouseDown={startResizingRight} />
                <AICopilot
                    legs={aiLegs}
                    strategyName={aiStrategyName}
                    chainData={chainData}
                    greeks={aiGreeks}
                    marketStatus={marketStatus}
                    underlying={aiUnderlying}
                    onDeployLegs={applyExternalLegs}
                />
            </div>
        </div>
    );
}

export default App;
