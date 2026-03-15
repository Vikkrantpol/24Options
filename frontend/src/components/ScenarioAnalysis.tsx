import React, { useState } from 'react';

interface Props {
    onScenarioChange: (deltaSpot: number, deltaIV: number, deltaDays: number) => void;
}

export const ScenarioAnalysis: React.FC<Props> = ({ onScenarioChange }) => {
    const [ds, setDs] = useState(0);
    const [di, setDi] = useState(0);
    const [dd, setDd] = useState(0);

    const fire = (field: 'spot' | 'iv' | 'days', val: number) => {
        const s = field === 'spot' ? val : ds;
        const i = field === 'iv' ? val : di;
        const d = field === 'days' ? val : dd;
        onScenarioChange(s, i, d);
    };

    const reset = () => { setDs(0); setDi(0); setDd(0); onScenarioChange(0, 0, 0); };

    return (
        <div className="panel">
            <div className="panel__header">
                <span className="panel__title">▸ SCENARIO</span>
                <button className="btn btn--xs" onClick={reset}>RESET</button>
            </div>
            <div className="panel__body">
                <div className="slider-row">
                    <span className="slider-row__label">Spot %</span>
                    <input type="range" className="slider-row__input" min="-10" max="10" step="0.5" value={ds}
                        onChange={e => { const v = +e.target.value; setDs(v); fire('spot', v); }} />
                    <span className="slider-row__val" style={{ color: ds > 0 ? 'var(--green)' : ds < 0 ? 'var(--red)' : 'var(--text-2)' }}>
                        {ds > 0 ? '+' : ''}{ds.toFixed(1)}%
                    </span>
                </div>
                <div className="slider-row">
                    <span className="slider-row__label">IV pts</span>
                    <input type="range" className="slider-row__input" min="-10" max="10" step="0.5" value={di}
                        onChange={e => { const v = +e.target.value; setDi(v); fire('iv', v); }} />
                    <span className="slider-row__val">{di > 0 ? '+' : ''}{di.toFixed(1)}</span>
                </div>
                <div className="slider-row">
                    <span className="slider-row__label">Days</span>
                    <input type="range" className="slider-row__input" min="0" max="30" step="1" value={dd}
                        onChange={e => { const v = +e.target.value; setDd(v); fire('days', v); }} />
                    <span className="slider-row__val">+{dd}d</span>
                </div>
            </div>
        </div>
    );
};
