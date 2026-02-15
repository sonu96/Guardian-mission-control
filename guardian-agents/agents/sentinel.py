"""
Sentinel Agent — Funding Rate & Open Interest Analyst.

Responsibilities:
  - Monitor Hyperliquid BTC funding rate (current + predicted)
  - Compare funding rates across venues (HL vs Binance)
  - Track open interest changes and divergences from price
  - Detect extreme funding (>2 std dev from mean)
  - Estimate liquidation clusters from OI + price data

Bus topics consumed:
  - "price_snapshot": PriceSnapshot (from Oracle)

Bus topics published:
  - "sentinel_signal": SentinelSignal
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import requests

from agents.base import BaseAgent, AgentBus
from services.hyperliquid_client import HyperliquidClient
from models.signals import (
    SentinelSignal, FundingData, OpenInterestData, Direction,
)


BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"


class SentinelAgent(BaseAgent):
    """Monitors funding rates, OI, and liquidation risk via Hyperliquid."""

    def __init__(self, bus: AgentBus, hl_client: HyperliquidClient):
        super().__init__("sentinel", bus)
        self.hl = hl_client

        # Rolling funding rate history for std dev calculation
        self._funding_history: list[float] = []
        self._oi_history: list[dict] = []  # {"timestamp", "oi_usd"}

    async def start(self):
        await super().start()
        # Pre-load some funding history
        try:
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            start = now - (7 * 24 * 3600 * 1000)  # 7 days
            history = self.hl.get_funding_history("BTC", start, now)
            self._funding_history = [
                float(h.get("fundingRate", 0)) for h in history[-168:]  # ~7 days hourly
            ]
            self.logger.info(
                f"Loaded {len(self._funding_history)} historical funding rates"
            )
        except Exception as e:
            self.logger.warning(f"Could not pre-load funding history: {e}")

        self.logger.info("Sentinel ready — funding rate & OI monitoring")

    def _get_binance_funding(self) -> Optional[float]:
        """Get latest Binance BTC/USDT perp funding rate."""
        try:
            resp = requests.get(
                BINANCE_FUNDING_URL,
                params={"symbol": "BTCUSDT", "limit": 1},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["fundingRate"])
        except Exception as e:
            self.logger.warning(f"Binance funding fetch failed: {e}")
        return None

    def _is_funding_extreme(self, rate: float) -> bool:
        """Check if funding rate is >2 std deviations from rolling mean."""
        if len(self._funding_history) < 24:
            return False

        import numpy as np
        rates = self._funding_history[-168:]  # last 7 days
        mean = float(np.mean(rates))
        std = float(np.std(rates))
        if std == 0:
            return False

        z_score = abs(rate - mean) / std
        return z_score > 2.0

    def _compute_oi_change(self, current_oi_usd: float) -> tuple[float, float]:
        """Compute OI change over 1h and 24h."""
        now = datetime.now(timezone.utc)
        self._oi_history.append({
            "timestamp": now,
            "oi_usd": current_oi_usd,
        })
        # Keep 24h of data
        cutoff = now - timedelta(hours=25)
        self._oi_history = [
            h for h in self._oi_history if h["timestamp"] > cutoff
        ]

        change_1h = 0.0
        change_24h = 0.0

        # 1h change
        target_1h = now - timedelta(hours=1)
        closest_1h = min(
            self._oi_history,
            key=lambda h: abs((h["timestamp"] - target_1h).total_seconds()),
            default=None,
        )
        if closest_1h and closest_1h["oi_usd"] > 0:
            change_1h = (current_oi_usd - closest_1h["oi_usd"]) / closest_1h["oi_usd"] * 100

        # 24h change
        target_24h = now - timedelta(hours=24)
        closest_24h = min(
            self._oi_history,
            key=lambda h: abs((h["timestamp"] - target_24h).total_seconds()),
            default=None,
        )
        if closest_24h and closest_24h["oi_usd"] > 0:
            change_24h = (current_oi_usd - closest_24h["oi_usd"]) / closest_24h["oi_usd"] * 100

        return change_1h, change_24h

    async def run_cycle(self, cycle_id: str) -> SentinelSignal:
        """
        Analyze funding rates, OI, and detect anomalies.
        """
        # 1. Hyperliquid funding data
        hl_funding = self.hl.get_current_funding("BTC")
        hl_rate = hl_funding["funding_rate"]

        # Update rolling history
        self._funding_history.append(hl_rate)

        # 2. Predicted funding (cross-venue)
        predicted = self.hl.get_predicted_fundings()
        hl_predicted = hl_rate  # fallback
        for entry in predicted:
            if isinstance(entry, list):
                for item in entry:
                    if isinstance(item, dict) and item.get("coin") == "BTC":
                        hl_predicted = float(item.get("predictedFundingRate", hl_rate))
                        break

        # 3. Binance funding for comparison
        binance_rate = self._get_binance_funding()
        hl_binance_spread = None
        if binance_rate is not None:
            hl_binance_spread = round(hl_rate - binance_rate, 8)

        funding = FundingData(
            timestamp=datetime.now(timezone.utc),
            hl_funding_rate=hl_rate,
            hl_predicted_funding=hl_predicted,
            binance_funding_rate=binance_rate,
            hl_binance_spread=hl_binance_spread,
        )

        # 4. Open interest
        oi_data = self.hl.get_open_interest("BTC")
        oi_usd = oi_data["open_interest_usd"]
        change_1h, change_24h = self._compute_oi_change(oi_usd)

        open_interest = OpenInterestData(
            timestamp=datetime.now(timezone.utc),
            hl_open_interest=oi_data["open_interest_btc"],
            hl_oi_usd=oi_usd,
            oi_change_1h_pct=round(change_1h, 2),
            oi_change_24h_pct=round(change_24h, 2),
        )

        # 5. Detect extremes and divergences
        funding_extreme = self._is_funding_extreme(hl_rate)

        # OI divergence: OI increasing while price dropping (or vice versa)
        price_snap = self.get_signal("price_snapshot")
        oi_divergence = False
        if price_snap and len(self._oi_history) > 1:
            price_change = price_snap.hl_mid_price - price_snap.hl_oracle_price
            if (change_1h > 5 and price_change < 0) or (change_1h < -5 and price_change > 0):
                oi_divergence = True

        # 6. Determine signal direction
        bullish_score = 0
        bearish_score = 0

        # Negative funding = shorts paying longs = potential short squeeze = bullish
        if hl_rate < -0.0001:
            bullish_score += 2
        elif hl_rate > 0.0001:
            bearish_score += 1  # positive funding is common, mild bearish

        # Extreme positive funding often precedes dumps
        if funding_extreme and hl_rate > 0:
            bearish_score += 2
        elif funding_extreme and hl_rate < 0:
            bullish_score += 2

        # OI spike with stable price = big move incoming (direction from funding)
        if change_1h > 3:
            if hl_rate < 0:
                bullish_score += 1
            else:
                bearish_score += 1

        # OI divergence is a reversal signal
        if oi_divergence:
            if change_1h > 0:  # OI up but price down = potential squeeze
                bullish_score += 1
            else:
                bearish_score += 1

        # Funding spread: if HL is much more negative than Binance, shorts are more
        # aggressive on HL = potential short squeeze
        if hl_binance_spread is not None:
            if hl_binance_spread < -0.0002:
                bullish_score += 1
            elif hl_binance_spread > 0.0002:
                bearish_score += 1

        net = bullish_score - bearish_score
        if net > 0:
            direction = Direction.UP
        elif net < 0:
            direction = Direction.DOWN
        else:
            direction = Direction.NEUTRAL

        max_points = max(bullish_score + bearish_score, 1)
        confidence = round(min(0.85, 0.35 + abs(net) / max_points * 0.5), 3)

        reasoning = (
            f"Funding: {hl_rate:.6f} (predicted: {hl_predicted:.6f}) | "
            f"Binance: {binance_rate or 'N/A'} | "
            f"Spread: {hl_binance_spread or 'N/A'} | "
            f"OI: ${oi_usd:,.0f} ({change_1h:+.1f}% 1h, {change_24h:+.1f}% 24h) | "
            f"Extreme: {funding_extreme} | Divergence: {oi_divergence}"
        )

        signal = SentinelSignal(
            timestamp=datetime.now(timezone.utc),
            funding=funding,
            open_interest=open_interest,
            funding_extreme=funding_extreme,
            oi_divergence=oi_divergence,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
        )

        await self.publish("sentinel_signal", signal)
        self.logger.info(
            f"Sentinel: {direction.value} ({confidence:.0%}) — "
            f"Funding {hl_rate:.6f} | OI ${oi_usd:,.0f} ({change_1h:+.1f}%)"
        )

        return signal
