"""
Oracle Agent — Market Data Collector.

Responsibilities:
  - Stream real-time BTC price from Hyperliquid WebSocket
  - Collect BTC candles (1m, 5m, 1h) from Hyperliquid
  - Fetch Binance BTC/USDT price for cross-reference
  - Compute HL-Binance spread (basis)
  - Publish price snapshots and candle data to bus

Bus topics published:
  - "price_snapshot": PriceSnapshot
  - "candles_1h": list of CandleData
  - "orderbook_snapshot": OrderBookSnapshot
"""

from datetime import datetime, timezone
from typing import Any, Optional
import requests

from agents.base import BaseAgent, AgentBus
from services.hyperliquid_client import HyperliquidClient
from models.signals import PriceSnapshot, OrderBookSnapshot, CandleData, TimeFrame


BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


class OracleAgent(BaseAgent):
    """Collects and normalizes market data from Hyperliquid + Binance."""

    def __init__(self, bus: AgentBus, hl_client: HyperliquidClient):
        super().__init__("oracle", bus)
        self.hl = hl_client

    async def start(self):
        await super().start()
        self.logger.info("Oracle ready — Hyperliquid + Binance data feeds")

    def _get_binance_btc_price(self) -> Optional[float]:
        """Fetch BTC/USDT spot price from Binance."""
        try:
            resp = requests.get(
                BINANCE_PRICE_URL,
                params={"symbol": "BTCUSDT"},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as e:
            self.logger.warning(f"Binance price fetch failed: {e}")
            return None

    async def run_cycle(self, cycle_id: str) -> dict:
        """
        Collect full market data snapshot for the prediction cycle.
        """
        # 1. Hyperliquid BTC snapshot (price + funding + OI)
        hl_snapshot = self.hl.get_btc_full_snapshot()

        # 2. Binance cross-reference
        binance_price = self._get_binance_btc_price()

        # 3. Build price snapshot
        hl_mid = hl_snapshot["price"]["mid"]
        spread = None
        if binance_price and hl_mid:
            spread = round((hl_mid - binance_price) / binance_price * 10000, 2)

        price_snap = PriceSnapshot(
            timestamp=datetime.now(timezone.utc),
            hl_mark_price=hl_snapshot["price"]["mark"],
            hl_oracle_price=hl_snapshot["price"]["oracle"],
            hl_mid_price=hl_mid,
            binance_price=binance_price,
            spread_hl_binance=spread,
        )
        await self.publish("price_snapshot", price_snap)

        # 4. Order book snapshot
        ob = hl_snapshot["order_book"]
        ob_snap = OrderBookSnapshot(
            timestamp=datetime.now(timezone.utc),
            best_bid=ob["best_bid"],
            best_ask=ob["best_ask"],
            spread_bps=ob["spread_bps"],
            bid_depth_1pct=ob["bid_depth_1pct"],
            ask_depth_1pct=ob["ask_depth_1pct"],
            bid_ask_imbalance=ob["bid_ask_imbalance"],
        )
        await self.publish("orderbook_snapshot", ob_snap)

        # 5. Candles (1h for Quant TA)
        raw_candles = self.hl.get_candles("BTC", "1h")
        candles = [
            CandleData(
                timestamp=datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc),
                open=float(c["o"]),
                high=float(c["h"]),
                low=float(c["l"]),
                close=float(c["c"]),
                volume=float(c["v"]),
                timeframe=TimeFrame.H1,
            )
            for c in raw_candles[-100:]  # last 100 candles
        ]
        await self.publish("candles_1h", candles)

        # 6. Also grab 5m candles for finer-grained TA
        raw_5m = self.hl.get_candles("BTC", "5m")
        candles_5m = [
            CandleData(
                timestamp=datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc),
                open=float(c["o"]),
                high=float(c["h"]),
                low=float(c["l"]),
                close=float(c["c"]),
                volume=float(c["v"]),
                timeframe=TimeFrame.M5,
            )
            for c in raw_5m[-100:]
        ]
        await self.publish("candles_5m", candles_5m)

        self.logger.info(
            f"Oracle snapshot: BTC ${hl_mid:,.0f} | "
            f"Funding {hl_snapshot['funding']['current_rate']:.6f} | "
            f"OI ${hl_snapshot['open_interest']['usd']:,.0f} | "
            f"HL-Binance spread {spread}bps"
        )

        return {
            "price": price_snap,
            "orderbook": ob_snap,
            "candles_1h": candles,
            "candles_5m": candles_5m,
            "raw_snapshot": hl_snapshot,
        }
