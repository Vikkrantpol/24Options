import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from backend import db as db_module
from backend.quant_engine import QuantEngineService
from backend.models import (
    ConcreteLeg,
    StrategyInstance,
    StrategyTemplate,
    StrategyCategory,
    PayoffType,
    Side,
    OptionRight,
)


def _sample_chain(symbol: str = "NSE:NIFTY50-INDEX") -> dict:
    spot = 22500.0
    expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
    return {
        "symbol": symbol,
        "spot": spot,
        "expiry": expiry,
        "lot_size": 65 if "BANK" not in symbol else 30,
        "chain": [
            {
                "strike": 22400,
                "CE": {
                    "premium": 180.0,
                    "ltp": 180.0,
                    "iv": 15.5,
                    "delta": 0.61,
                    "gamma": 0.0011,
                    "theta": -14.2,
                    "vega": 11.2,
                    "oi": 70000,
                    "volume": 3400,
                    "bid": 179.0,
                    "ask": 181.0,
                    "symbol": f"{symbol}:22400CE",
                },
                "PE": {
                    "premium": 95.0,
                    "ltp": 95.0,
                    "iv": 17.8,
                    "delta": -0.31,
                    "gamma": 0.0010,
                    "theta": -11.2,
                    "vega": 10.8,
                    "oi": 120000,
                    "volume": 3800,
                    "bid": 94.5,
                    "ask": 95.5,
                    "symbol": f"{symbol}:22400PE",
                },
            },
            {
                "strike": 22500,
                "CE": {
                    "premium": 140.0,
                    "ltp": 140.0,
                    "iv": 15.0,
                    "delta": 0.51,
                    "gamma": 0.0013,
                    "theta": -15.0,
                    "vega": 11.6,
                    "oi": 88000,
                    "volume": 4100,
                    "bid": 139.0,
                    "ask": 141.0,
                    "symbol": f"{symbol}:22500CE",
                },
                "PE": {
                    "premium": 132.0,
                    "ltp": 132.0,
                    "iv": 16.8,
                    "delta": -0.49,
                    "gamma": 0.0013,
                    "theta": -14.8,
                    "vega": 11.5,
                    "oi": 140000,
                    "volume": 4600,
                    "bid": 131.0,
                    "ask": 133.0,
                    "symbol": f"{symbol}:22500PE",
                },
            },
            {
                "strike": 22600,
                "CE": {
                    "premium": 104.0,
                    "ltp": 104.0,
                    "iv": 14.4,
                    "delta": 0.39,
                    "gamma": 0.0010,
                    "theta": -12.5,
                    "vega": 10.3,
                    "oi": 76000,
                    "volume": 3200,
                    "bid": 103.0,
                    "ask": 105.0,
                    "symbol": f"{symbol}:22600CE",
                },
                "PE": {
                    "premium": 172.0,
                    "ltp": 172.0,
                    "iv": 18.2,
                    "delta": -0.62,
                    "gamma": 0.0011,
                    "theta": -13.1,
                    "vega": 11.0,
                    "oi": 125000,
                    "volume": 3900,
                    "bid": 171.0,
                    "ask": 173.0,
                    "symbol": f"{symbol}:22600PE",
                },
            },
        ],
    }


class FakeFyersClient:
    def __init__(self):
        self.is_authenticated = False
        self._chain = _sample_chain()

    def get_option_chain(self, symbol: str = "NSE:NIFTY50-INDEX", strike_count: int = 15, expiry: str = None):
        chain = dict(self._chain)
        chain["symbol"] = symbol
        return chain

    def deploy_strategy(self, legs, underlying):
        return {"status": "deployed", "num_legs": len(legs), "underlying": underlying}


class FakePaperEngine:
    def __init__(self):
        self.strategies = []
        self.positions = []

    def update_mtm(self, spot_price, **kwargs):
        # Keep deterministic no-op for unit tests.
        return None

    def open_strategy(self, template, legs, underlying, spot_price, tags=None):
        instance = StrategyInstance(
            template_id=template.id,
            template_name=template.name,
            underlying=underlying,
            spot_at_entry=spot_price,
            legs=legs,
            tags=tags or [],
        )
        self.strategies.append(instance)
        return instance

    def close_strategy(self, strategy_id, spot_price):
        for s in self.strategies:
            if s.id == strategy_id and s.status == "active":
                s.status = "closed"
                s.realized_pnl = 1234.56
                s.exit_time = datetime.now()
                return {"strategy_id": strategy_id, "realized_pnl": s.realized_pnl}
        return {"error": "Strategy not found or already closed"}


class QuantEngineV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db_module.DB_PATH = Path(cls.tmp.name) / "quant_engine_test.db"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.fyers = FakeFyersClient()
        self.paper = FakePaperEngine()
        self.engine = QuantEngineService(self.fyers, self.paper)

    def _option_legs(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        return [
            ConcreteLeg(
                side=Side.SELL,
                right=OptionRight.CE,
                strike=22600,
                premium=104.0,
                qty=65,
                expiry=expiry,
                iv=0.144,
            ),
            ConcreteLeg(
                side=Side.SELL,
                right=OptionRight.PE,
                strike=22400,
                premium=95.0,
                qty=65,
                expiry=expiry,
                iv=0.178,
            ),
        ]

    def test_profile_update_and_clamps(self):
        out = self.engine.update_profile(
            {
                "preferred_underlyings": ["NSE:NIFTY50-INDEX", "banknifty"],
                "max_margin_utilization_pct": 200,
                "repair_loss_trigger_pct": 0.0001,
                "max_slice_lots": 0,
            }
        )
        self.assertIn("preferred_underlyings", out)
        self.assertLessEqual(out["max_margin_utilization_pct"], 100.0)
        self.assertGreaterEqual(out["repair_loss_trigger_pct"], 0.001)
        self.assertGreaterEqual(out["max_slice_lots"], 1)

    def test_regime_and_adaptive_recommendation(self):
        regime = self.engine.analyze_regime("NSE:NIFTY50-INDEX")
        self.assertIn("regime", regime)
        self.assertTrue(regime["recommended_strategy_ids"])

        rec = self.engine.build_adaptive_recommendation("NSE:NIFTY50-INDEX", num_lots=1)
        self.assertIn("strategy", rec)
        self.assertIn("legs", rec)
        self.assertIn("decision", rec)
        self.assertGreater(len(rec["legs"]), 0)

    def test_execution_plan_slicing(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        legs = [
            ConcreteLeg(
                side=Side.BUY,
                right=OptionRight.CE,
                strike=22500,
                premium=140.0,
                qty=260,  # split across multiple slices
                expiry=expiry,
                iv=0.15,
            )
        ]
        plan = self.engine.build_execution_plan("NSE:NIFTY50-INDEX", legs)
        self.assertTrue(plan["execution_ready"])
        self.assertGreaterEqual(len(plan["order_slices"]), 2)

    def test_decision_score_output(self):
        result = self.engine.score_decision("NSE:NIFTY50-INDEX", self._option_legs())
        self.assertIn("confidence", result)
        self.assertIn("stress", result)
        self.assertIn(result["grade"], ("A", "B", "C", "D"))
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

    def test_optimizer_and_adjustment_actions(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        # High positive delta + large unrealized loss to trigger both optimizer and adjustment logic.
        fut_leg = ConcreteLeg(
            side=Side.BUY,
            right=OptionRight.FUT,
            strike=22500.0,
            premium=22500.0,
            qty=130,
            expiry=expiry,
            iv=0.0,
        )
        strat = StrategyInstance(
            template_id=900,
            template_name="Test Delta Heavy",
            underlying="NSE:NIFTY50-INDEX",
            spot_at_entry=22500.0,
            legs=[fut_leg],
            unrealized_pnl=-50000.0,
            status="active",
        )
        self.paper.strategies.append(strat)

        opt = self.engine.optimize_portfolio("NSE:NIFTY50-INDEX", target_delta=0, target_vega=0)
        self.assertIn("rebalancing_required", opt)
        self.assertTrue(opt["rebalancing_required"])
        self.assertGreater(len(opt["rebalancing_legs"]), 0)

        adj = self.engine.generate_adjustments("NSE:NIFTY50-INDEX")
        self.assertIn("actions", adj)
        self.assertGreater(len(adj["actions"]), 0)

    def test_autopilot_cycle_and_learning_summary(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        fut_leg = ConcreteLeg(
            side=Side.BUY,
            right=OptionRight.FUT,
            strike=22500.0,
            premium=22500.0,
            qty=130,
            expiry=expiry,
            iv=0.0,
        )
        strat = StrategyInstance(
            template_id=901,
            template_name="Test Auto",
            underlying="NSE:NIFTY50-INDEX",
            spot_at_entry=22500.0,
            legs=[fut_leg],
            unrealized_pnl=-60000.0,
            status="active",
        )
        self.paper.strategies.append(strat)

        state = self.engine.approve_autopilot({"mode": "paper", "rebalance_interval_sec": 10})
        self.assertTrue(state["enabled"])

        run = self.engine.run_autopilot_cycle("NSE:NIFTY50-INDEX", force=True)
        self.assertEqual(run["status"], "ran")
        self.assertIn("execution_report", run)

        journal = self.engine.get_journal(limit=20)
        self.assertGreater(len(journal), 0)

        summary = self.engine.learning_summary(limit=50)
        self.assertIn("event_counts", summary)
        self.assertIn("sample_size", summary)

    def test_market_closed_blocks_autopilot_execution(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        fut_leg = ConcreteLeg(
            side=Side.BUY,
            right=OptionRight.FUT,
            strike=22500.0,
            premium=22500.0,
            qty=130,
            expiry=expiry,
            iv=0.0,
        )
        strat = StrategyInstance(
            template_id=902,
            template_name="Test Market Closed Block",
            underlying="NSE:NIFTY50-INDEX",
            spot_at_entry=22500.0,
            legs=[fut_leg],
            unrealized_pnl=-60000.0,
            status="active",
        )
        self.paper.strategies.append(strat)

        self.engine.approve_autopilot({"mode": "paper", "rebalance_interval_sec": 10})

        with patch("backend.quant_engine.market_status", return_value={
            "status": "CLOSED",
            "is_open": False,
            "message": "Test closed market gate",
        }):
            out = self.engine.run_autopilot_cycle("NSE:NIFTY50-INDEX", force=True)

        self.assertEqual(out["status"], "ran")
        self.assertEqual(out["execution_report"]["executed_count"], 0)
        self.assertGreaterEqual(out["execution_report"]["skipped_count"], 1)
        self.assertIn("market", out)
        self.assertEqual(out["market"]["status"], "CLOSED")

    def test_rebalance_dedup_blocks_duplicate_active_autopilot_hedges(self):
        expiry = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        rebalance_legs = [
            ConcreteLeg(
                side=Side.SELL,
                right=OptionRight.CE,
                strike=22500.0,
                premium=140.0,
                qty=65,
                expiry=expiry,
                iv=0.15,
            ),
            ConcreteLeg(
                side=Side.SELL,
                right=OptionRight.PE,
                strike=22500.0,
                premium=132.0,
                qty=65,
                expiry=expiry,
                iv=0.16,
            ),
        ]

        self.engine.approve_autopilot({
            "mode": "paper",
            "rebalance_interval_sec": 10,
            "max_active_rebalance_per_symbol": 1,
        })

        # Force a deterministic optimizer output so this test only exercises dedupe logic.
        self.engine.optimize_portfolio = lambda *args, **kwargs: {
            "symbol": "NSE:NIFTY50-INDEX",
            "rebalancing_required": True,
            "rebalancing_legs": [leg.model_dump() for leg in rebalance_legs],
        }
        self.engine.generate_adjustments = lambda *args, **kwargs: {"actions": []}

        open_market = {
            "status": "OPEN",
            "is_open": True,
            "message": "Test open market",
        }
        with patch("backend.quant_engine.market_status", return_value=open_market):
            first = self.engine.run_autopilot_cycle("NSE:NIFTY50-INDEX", force=True)
            second = self.engine.run_autopilot_cycle("NSE:NIFTY50-INDEX", force=True)

        active_rebalances = [
            s for s in self.paper.strategies
            if s.status == "active" and s.template_name == "AUTOPILOT-rebalance_portfolio"
        ]
        self.assertEqual(first["execution_report"]["executed_count"], 1)
        self.assertEqual(second["execution_report"]["executed_count"], 0)
        self.assertEqual(len(active_rebalances), 1)
        self.assertGreaterEqual(second["execution_report"]["skipped_count"], 1)
        self.assertIn("already open", second["execution_report"]["skipped"][0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
