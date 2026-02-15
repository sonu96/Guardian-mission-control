"""
Strategist Agent — Decision Engine (Lead Agent).

Responsibilities:
  - Aggregate signals from Quant, Hawk, Sentinel, Sage
  - Apply weighted ensemble scoring
  - Compute position size via Kelly criterion
  - Apply risk management rules (daily loss limit, streak limits)
  - Decide: trade or skip

Bus topics consumed:
  - "technical_signal": TechnicalSignal (from Quant)
  - "whale_signal": WhaleSignal (from Hawk)
  - "sentinel_signal": SentinelSignal (from Sentinel)
  - "sage_signal": SageSignal (from Sage)
  - "price_snapshot": PriceSnapshot (from Oracle)

Bus topics published:
  - "prediction_decision": PredictionDecision
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from agents.base import BaseAgent, AgentBus
from models.signals import (
    PredictionDecision, Direction,
    TechnicalSignal, WhaleSignal, SentinelSignal, SageSignal,
)
from config.settings import settings


class StrategistAgent(BaseAgent):
    """Weighted ensemble decision engine with risk management."""

    def __init__(self, bus: AgentBus):
        super().__init__("strategist", bus)

        # Running stats for risk management
        self._daily_pnl: float = 0.0
        self._daily_reset_date: Optional[str] = None
        self._consecutive_losses: int = 0
        self._total_trades: int = 0

    async def start(self):
        await super().start()
        self.logger.info(
            f"Strategist ready — weights: Quant={settings.agent.weight_quant}, "
            f"Hawk={settings.agent.weight_hawk}, Sentinel={settings.agent.weight_sentinel}, "
            f"Sage={settings.agent.weight_sage}"
        )

    def _reset_daily_if_needed(self):
        """Reset daily PnL counter at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today

    def _kelly_position_size(
        self, win_prob: float, win_payout: float = 0.92, loss_payout: float = 1.0
    ) -> float:
        """
        Quarter-Kelly position sizing.

        For Polymarket: if you buy at $0.52, win pays $1.00 (92% gain),
        loss pays $0 (100% loss of stake).

        win_payout = (1.0 - buy_price) / buy_price  (e.g., 0.48/0.52 = 0.92)
        loss_payout = 1.0  (you lose your full stake)
        """
        if win_prob <= 0 or win_payout <= 0:
            return 0.0

        # Kelly formula: f* = (bp - q) / b
        # b = win_payout ratio, p = win probability, q = 1-p
        b = win_payout
        p = win_prob
        q = 1 - p

        kelly = (b * p - q) / b
        kelly = max(0, kelly)

        # Use quarter-Kelly for conservative sizing
        fractional_kelly = kelly * settings.agent.kelly_fraction

        # Convert to USD
        position = fractional_kelly * settings.polymarket.max_position_usd

        return round(min(position, settings.polymarket.max_position_usd), 2)

    def _check_risk_limits(self) -> Optional[str]:
        """Check if risk management rules prevent trading."""
        self._reset_daily_if_needed()

        if self._daily_pnl <= -settings.agent.max_daily_loss_usd:
            return f"Daily loss limit reached (${self._daily_pnl:.2f})"

        if self._consecutive_losses >= settings.agent.max_consecutive_losses:
            return f"Max consecutive losses reached ({self._consecutive_losses})"

        return None

    async def run_cycle(self, cycle_id: str) -> PredictionDecision:
        """
        Aggregate all agent signals and produce a final prediction decision.
        """
        now = datetime.now(timezone.utc)

        # Collect signals from bus
        quant: Optional[TechnicalSignal] = self.get_signal("technical_signal")
        whale: Optional[WhaleSignal] = self.get_signal("whale_signal")
        sentinel: Optional[SentinelSignal] = self.get_signal("sentinel_signal")
        sage: Optional[SageSignal] = self.get_signal("sage_signal")

        # ---- Weighted ensemble ----
        weights = {
            "quant": settings.agent.weight_quant,
            "hawk": settings.agent.weight_hawk,
            "sentinel": settings.agent.weight_sentinel,
            "sage": settings.agent.weight_sage,
        }

        # Score: +1 for UP, -1 for DOWN, 0 for NEUTRAL, weighted by confidence
        weighted_score = 0.0
        total_weight = 0.0
        active_signals = []

        if quant and quant.direction != Direction.NEUTRAL:
            sign = 1 if quant.direction == Direction.UP else -1
            weighted_score += sign * quant.confidence * weights["quant"]
            total_weight += weights["quant"]
            active_signals.append(f"Quant:{quant.direction.value}@{quant.confidence:.0%}")

        if whale and whale.direction != Direction.NEUTRAL:
            sign = 1 if whale.direction == Direction.UP else -1
            weighted_score += sign * whale.confidence * weights["hawk"]
            total_weight += weights["hawk"]
            active_signals.append(f"Hawk:{whale.direction.value}@{whale.confidence:.0%}")

        if sentinel and sentinel.direction != Direction.NEUTRAL:
            sign = 1 if sentinel.direction == Direction.UP else -1
            weighted_score += sign * sentinel.confidence * weights["sentinel"]
            total_weight += weights["sentinel"]
            active_signals.append(f"Sentinel:{sentinel.direction.value}@{sentinel.confidence:.0%}")

        if sage and sage.direction != Direction.NEUTRAL:
            sign = 1 if sage.direction == Direction.UP else -1
            weighted_score += sign * sage.confidence * weights["sage"]
            total_weight += weights["sage"]
            active_signals.append(f"Sage:{sage.direction.value}@{sage.confidence:.0%}")

        # Normalize score to [-1, 1]
        if total_weight > 0:
            normalized_score = weighted_score / total_weight
        else:
            normalized_score = 0

        # Direction from sign, confidence from magnitude
        if normalized_score > 0.05:
            direction = Direction.UP
        elif normalized_score < -0.05:
            direction = Direction.DOWN
        else:
            direction = Direction.NEUTRAL

        # Confidence: the magnitude of the normalized score
        # Scale it to be more intuitive (0.5 = minimum actionable)
        raw_confidence = abs(normalized_score)
        confidence = round(min(0.95, 0.5 + raw_confidence * 0.45), 3)

        # ---- Signal agreement bonus ----
        # If all active signals agree on direction, boost confidence
        if active_signals:
            up_count = sum(1 for s in [quant, whale, sentinel, sage]
                         if s and s.direction == Direction.UP)
            down_count = sum(1 for s in [quant, whale, sentinel, sage]
                           if s and s.direction == Direction.DOWN)
            total_directional = up_count + down_count
            if total_directional >= 3:
                agreement = max(up_count, down_count) / total_directional
                if agreement >= 0.75:
                    confidence = min(0.95, confidence + 0.05)

        # ---- Risk management ----
        skip_reason = self._check_risk_limits()

        if not skip_reason and direction == Direction.NEUTRAL:
            skip_reason = "No directional consensus"

        if not skip_reason and confidence < settings.agent.min_confidence_trade:
            skip_reason = f"Confidence {confidence:.0%} below threshold {settings.agent.min_confidence_trade:.0%}"

        # ---- Position sizing (Kelly) ----
        position_size = 0.0
        if not skip_reason:
            position_size = self._kelly_position_size(confidence)
            if position_size < 1.0:
                skip_reason = "Kelly sizing too small (<$1)"
                position_size = 0.0

        should_trade = skip_reason is None

        # Build reasoning
        signals_str = ", ".join(active_signals) if active_signals else "No signals"
        reasoning = (
            f"Ensemble score: {normalized_score:+.3f} → {direction.value} @ {confidence:.0%}\n"
            f"Signals: {signals_str}\n"
            f"Position: ${position_size:.2f} (Kelly {settings.agent.kelly_fraction}x)\n"
            f"Risk: daily PnL ${self._daily_pnl:+.2f}, streak {self._consecutive_losses} losses\n"
            f"{'TRADE' if should_trade else f'SKIP: {skip_reason}'}"
        )

        decision = PredictionDecision(
            timestamp=now,
            cycle_id=cycle_id,
            prediction_window_start=now,
            prediction_window_end=now + timedelta(minutes=settings.agent.cycle_minutes),
            direction=direction,
            confidence=confidence,
            position_size_usd=position_size,
            quant_signal=quant,
            whale_signal=whale,
            sentinel_signal=sentinel,
            sage_signal=sage,
            weights_used=weights,
            should_trade=should_trade,
            skip_reason=skip_reason,
            reasoning=reasoning,
        )

        await self.publish("prediction_decision", decision)
        self.logger.info(
            f"Strategist: {direction.value} @ {confidence:.0%} — "
            f"{'TRADE $' + f'{position_size:.0f}' if should_trade else 'SKIP: ' + (skip_reason or '')}"
        )

        return decision

    def update_pnl(self, pnl: float, won: bool):
        """Called by Auditor after cycle resolves to update risk state."""
        self._daily_pnl += pnl
        if won:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
        self._total_trades += 1
