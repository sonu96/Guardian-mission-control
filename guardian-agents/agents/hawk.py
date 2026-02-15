"""
Hawk Agent — Whale Position Tracker.

Responsibilities:
  - Monitor tracked whale wallets on Hyperliquid
  - Detect position opens, closes, size changes, leverage changes
  - Compute aggregate whale sentiment (net long/short)
  - Identify liquidation proximity for large positions
  - Flag unusual whale activity

Bus topics published:
  - "whale_signal": WhaleSignal

Uses Hyperliquid's clearinghouseState — unique alpha source.
Every wallet's positions, leverage, and margin are fully on-chain and public.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from agents.base import BaseAgent, AgentBus
from services.hyperliquid_client import HyperliquidClient
from models.signals import WhaleSignal, WhalePosition, Direction
from config.whales import TRACKED_WHALES, WHALE_POSITION_THRESHOLD_USD, POSITION_CHANGE_ALERT_PCT


class HawkAgent(BaseAgent):
    """Tracks whale BTC positions on Hyperliquid for directional signals."""

    def __init__(self, bus: AgentBus, hl_client: HyperliquidClient):
        super().__init__("hawk", bus)
        self.hl = hl_client

        # Cache previous positions to detect changes
        self._prev_positions: dict[str, Optional[dict]] = {}
        self._discovered_whales: list[dict] = []

    async def start(self):
        await super().start()
        whale_count = len(TRACKED_WHALES) + len(self._discovered_whales)
        self.logger.info(f"Hawk ready — tracking {whale_count} whale wallets")

    def _detect_changes(
        self, address: str, current: Optional[dict], previous: Optional[dict]
    ) -> Optional[dict]:
        """Detect meaningful position changes for a whale."""
        if previous is None and current is None:
            return None

        if previous is None and current is not None:
            return {
                "type": "opened",
                "address": address,
                "side": "LONG" if current["size"] > 0 else "SHORT",
                "size": current["size"],
                "value_usd": current["position_value_usd"],
                "leverage": current["leverage"],
            }

        if previous is not None and current is None:
            return {
                "type": "closed",
                "address": address,
                "prev_side": "LONG" if previous["size"] > 0 else "SHORT",
                "prev_size": previous["size"],
            }

        if previous is not None and current is not None:
            prev_size = previous["size"]
            curr_size = current["size"]

            if prev_size == 0 and curr_size == 0:
                return None

            # Check for side flip
            if (prev_size > 0 and curr_size < 0) or (prev_size < 0 and curr_size > 0):
                return {
                    "type": "flipped",
                    "address": address,
                    "from_side": "LONG" if prev_size > 0 else "SHORT",
                    "to_side": "LONG" if curr_size > 0 else "SHORT",
                    "new_size": curr_size,
                    "value_usd": current["position_value_usd"],
                }

            # Check for significant size change
            if prev_size != 0:
                change_pct = abs((curr_size - prev_size) / prev_size) * 100
                if change_pct >= POSITION_CHANGE_ALERT_PCT:
                    return {
                        "type": "increased" if abs(curr_size) > abs(prev_size) else "decreased",
                        "address": address,
                        "change_pct": round(change_pct, 1),
                        "prev_size": prev_size,
                        "new_size": curr_size,
                        "value_usd": current["position_value_usd"],
                    }

        return None

    async def run_cycle(self, cycle_id: str) -> WhaleSignal:
        """
        Poll all tracked whales and compute aggregate sentiment.
        """
        all_whales = TRACKED_WHALES + self._discovered_whales
        positions: list[WhalePosition] = []
        changes: list[dict] = []

        for whale in all_whales:
            address = whale["address"]
            label = whale.get("label", address[:10])

            try:
                pos_data = self.hl.get_whale_btc_position(address)

                # Detect changes from previous cycle
                prev = self._prev_positions.get(address)
                change = self._detect_changes(address, pos_data, prev)
                if change:
                    change["label"] = label
                    changes.append(change)
                    self.logger.info(f"Whale {label}: {change['type']} — {change}")

                # Cache for next cycle
                self._prev_positions[address] = pos_data

                if pos_data and abs(pos_data["position_value_usd"]) >= whale.get(
                    "min_position_usd", WHALE_POSITION_THRESHOLD_USD
                ):
                    positions.append(WhalePosition(
                        address=address,
                        label=label,
                        size=pos_data["size"],
                        entry_price=pos_data["entry_price"],
                        liquidation_price=pos_data.get("liquidation_price"),
                        leverage=pos_data["leverage"],
                        leverage_type=pos_data["leverage_type"],
                        unrealized_pnl=pos_data["unrealized_pnl"],
                        margin_used=pos_data["margin_used"],
                        position_value_usd=pos_data["position_value_usd"],
                    ))

            except Exception as e:
                self.logger.warning(f"Failed to query whale {label}: {e}")

        # Aggregate sentiment
        longs = [p for p in positions if p.size > 0]
        shorts = [p for p in positions if p.size < 0]
        neutral_count = len(all_whales) - len(positions)

        net_exposure = sum(p.size for p in positions)

        # Find largest positions
        largest_long = max(longs, key=lambda p: p.position_value_usd, default=None)
        largest_short = max(shorts, key=lambda p: p.position_value_usd, default=None)

        # Determine direction signal
        if len(longs) > len(shorts) * 1.5 and net_exposure > 0:
            direction = Direction.UP
            confidence = min(0.9, 0.5 + (len(longs) - len(shorts)) / max(len(all_whales), 1))
        elif len(shorts) > len(longs) * 1.5 and net_exposure < 0:
            direction = Direction.DOWN
            confidence = min(0.9, 0.5 + (len(shorts) - len(longs)) / max(len(all_whales), 1))
        else:
            direction = Direction.NEUTRAL
            confidence = 0.3

        # Boost confidence if recent changes are directional
        if changes:
            open_longs = sum(1 for c in changes if c["type"] in ("opened", "increased", "flipped") and "LONG" in str(c.get("to_side", c.get("side", ""))))
            open_shorts = sum(1 for c in changes if c["type"] in ("opened", "increased", "flipped") and "SHORT" in str(c.get("to_side", c.get("side", ""))))
            if open_longs > open_shorts and direction == Direction.UP:
                confidence = min(0.95, confidence + 0.1)
            elif open_shorts > open_longs and direction == Direction.DOWN:
                confidence = min(0.95, confidence + 0.1)

        reasoning = (
            f"{len(longs)} whales long, {len(shorts)} short, {neutral_count} flat. "
            f"Net exposure: {net_exposure:.4f} BTC. "
            f"{len(changes)} position changes this cycle."
        )

        signal = WhaleSignal(
            timestamp=datetime.now(timezone.utc),
            total_whales_tracked=len(all_whales),
            whales_long=len(longs),
            whales_short=len(shorts),
            whales_neutral=neutral_count,
            net_whale_exposure=net_exposure,
            largest_long=largest_long,
            largest_short=largest_short,
            position_changes=changes,
            direction=direction,
            confidence=round(confidence, 3),
            reasoning=reasoning,
        )

        await self.publish("whale_signal", signal)
        self.logger.info(
            f"Hawk: {direction.value} ({confidence:.0%}) — "
            f"{len(longs)}L/{len(shorts)}S, net {net_exposure:.4f} BTC"
        )

        return signal
