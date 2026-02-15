"""
Auditor Agent — Performance Tracker.

Responsibilities:
  - Wait for prediction window to close (1h BTC candle resolves)
  - Compare predicted direction vs actual BTC movement
  - Calculate PnL from Polymarket position
  - Update running statistics (win rate, Sharpe, drawdown)
  - Report results back to Strategist for risk management
  - Store outcomes in memory (Mem0) for Sage's pattern learning

Bus topics consumed:
  - "prediction_decision": PredictionDecision (from Strategist)
  - "trade_executed": dict (from Dealer)
  - "price_snapshot": PriceSnapshot (from Oracle)

Bus topics published:
  - "cycle_result": CycleResult
"""

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from agents.base import BaseAgent, AgentBus
from models.signals import CycleResult, PredictionDecision, Direction
from services.hyperliquid_client import HyperliquidClient


class AuditorAgent(BaseAgent):
    """Tracks prediction accuracy and PnL across all cycles."""

    def __init__(self, bus: AgentBus, hl_client: HyperliquidClient):
        super().__init__("auditor", bus)
        self.hl = hl_client

        # Running statistics
        self._results: list[CycleResult] = []
        self._total_predictions = 0
        self._correct_predictions = 0
        self._cumulative_pnl = 0.0
        self._current_streak = 0  # positive = wins, negative = losses
        self._max_win_streak = 0
        self._max_loss_streak = 0
        self._peak_pnl = 0.0
        self._max_drawdown = 0.0

        # Reference to strategist for risk updates
        self._strategist_ref = None

    def set_strategist(self, strategist):
        """Set reference to Strategist for PnL updates."""
        self._strategist_ref = strategist

    async def start(self):
        await super().start()
        self.logger.info("Auditor ready — performance tracking & PnL")

    async def run_cycle(self, cycle_id: str) -> Optional[CycleResult]:
        """
        Evaluate the PREVIOUS cycle's outcome.
        Called at the start of a new cycle to check how the last one did.
        """
        # Get the most recent decision and trade that has completed
        decision: Optional[PredictionDecision] = self.get_signal("prediction_decision")
        trade = self.get_signal("trade_executed")

        if not decision:
            self.logger.info("No previous decision to audit")
            return None

        # Get BTC price at the time of prediction and now
        # The "close" price is the current price (end of prediction window)
        btc_close = self.hl.get_btc_price()

        # We need the opening price from the decision
        price_snap = self.get_signal("price_snapshot")
        btc_open = price_snap.hl_mid_price if price_snap else btc_close

        if btc_open == 0:
            self.logger.warning("Cannot determine opening price — skipping audit")
            return None

        # Determine actual direction
        btc_change_pct = ((btc_close - btc_open) / btc_open) * 100

        if btc_change_pct > 0:
            actual_direction = Direction.UP
        elif btc_change_pct < 0:
            actual_direction = Direction.DOWN
        else:
            actual_direction = Direction.NEUTRAL

        # Was the prediction correct?
        prediction_correct = (
            decision.direction == actual_direction
            or actual_direction == Direction.NEUTRAL
        )

        # Calculate Polymarket PnL
        poly_pnl = 0.0
        if trade and trade.get("action") in ("trade", "simulated_trade"):
            cost = trade.get("cost_usd", 0)
            if prediction_correct:
                # Win: shares * $1.00 - cost
                shares = trade.get("shares", 0)
                poly_pnl = shares * 1.0 - cost
            else:
                # Loss: lose the cost
                poly_pnl = -cost

        # Update running stats
        self._total_predictions += 1
        if prediction_correct:
            self._correct_predictions += 1

        self._cumulative_pnl += poly_pnl

        if prediction_correct:
            self._current_streak = max(0, self._current_streak) + 1
            self._max_win_streak = max(self._max_win_streak, self._current_streak)
        else:
            self._current_streak = min(0, self._current_streak) - 1
            self._max_loss_streak = max(
                self._max_loss_streak, abs(self._current_streak)
            )

        # Drawdown
        self._peak_pnl = max(self._peak_pnl, self._cumulative_pnl)
        current_drawdown = self._peak_pnl - self._cumulative_pnl
        self._max_drawdown = max(self._max_drawdown, current_drawdown)

        win_rate = (
            self._correct_predictions / self._total_predictions
            if self._total_predictions > 0
            else 0
        )

        result = CycleResult(
            cycle_id=decision.cycle_id,
            prediction=decision,
            btc_open_price=btc_open,
            btc_close_price=btc_close,
            btc_change_pct=round(btc_change_pct, 4),
            actual_direction=actual_direction,
            prediction_correct=prediction_correct,
            polymarket_pnl_usd=round(poly_pnl, 2),
            total_pnl_usd=round(poly_pnl, 2),
            cumulative_pnl=round(self._cumulative_pnl, 2),
            win_rate=round(win_rate, 4),
            total_predictions=self._total_predictions,
            correct_predictions=self._correct_predictions,
            current_streak=self._current_streak,
        )

        # Update Strategist's risk state
        if self._strategist_ref:
            self._strategist_ref.update_pnl(poly_pnl, prediction_correct)

        await self.publish("cycle_result", result)

        emoji_result = "CORRECT" if prediction_correct else "WRONG"
        self.logger.info(
            f"Auditor: {emoji_result} — "
            f"Predicted {decision.direction.value}, Actual {actual_direction.value} | "
            f"BTC {btc_change_pct:+.2f}% (${btc_open:,.0f} → ${btc_close:,.0f}) | "
            f"PnL: ${poly_pnl:+.2f} | Cumulative: ${self._cumulative_pnl:+.2f} | "
            f"Win rate: {win_rate:.0%} ({self._correct_predictions}/{self._total_predictions})"
        )

        self._results.append(result)
        return result

    def get_stats(self) -> dict:
        """Get comprehensive performance statistics."""
        pnl_series = [r.polymarket_pnl_usd for r in self._results if r.polymarket_pnl_usd != 0]

        sharpe = None
        if len(pnl_series) > 1:
            mean = float(np.mean(pnl_series))
            std = float(np.std(pnl_series))
            if std > 0:
                sharpe = round(mean / std * np.sqrt(24), 3)  # annualized (24 trades/day)

        return {
            "total_predictions": self._total_predictions,
            "correct_predictions": self._correct_predictions,
            "win_rate": round(
                self._correct_predictions / max(self._total_predictions, 1), 4
            ),
            "cumulative_pnl": round(self._cumulative_pnl, 2),
            "max_drawdown": round(self._max_drawdown, 2),
            "sharpe_ratio": sharpe,
            "current_streak": self._current_streak,
            "max_win_streak": self._max_win_streak,
            "max_loss_streak": self._max_loss_streak,
            "avg_pnl_per_trade": round(
                self._cumulative_pnl / max(self._total_predictions, 1), 2
            ),
        }
