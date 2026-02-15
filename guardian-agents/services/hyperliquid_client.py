"""
Hyperliquid data client - SIGNAL SOURCE ONLY, no trading.

Provides:
  - Real-time BTC price, order book, candles via WebSocket
  - Whale position tracking via clearinghouseState
  - Funding rates (current, predicted, historical)
  - Open interest snapshots
  - Liquidation level estimation
"""

import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Callable

import requests
import websockets

from config.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.hyperliquid.base_url
WS_URL = settings.hyperliquid.ws_url


class HyperliquidClient:
    """Read-only Hyperliquid data client for BTC signal extraction."""

    def __init__(self):
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_callbacks: dict[str, list[Callable]] = {}
        self._running = False

    # ----------------------------------------------------------------
    # REST Info API (POST /info) — no auth required
    # ----------------------------------------------------------------

    def _post_info(self, payload: dict) -> dict:
        """Send a POST request to Hyperliquid Info API."""
        resp = requests.post(f"{BASE_URL}/info", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---- Prices ----

    def get_all_mids(self) -> dict[str, str]:
        """Get mid-market prices for all assets. Returns {coin: price}."""
        return self._post_info({"type": "allMids"})

    def get_btc_price(self) -> float:
        """Get current BTC mid price."""
        mids = self.get_all_mids()
        return float(mids.get("BTC", 0))

    # ---- Order Book ----

    def get_order_book(self, coin: str = "BTC", n_levels: int = 20) -> dict:
        """
        Get L2 order book snapshot.
        Returns: {"coin": "BTC", "levels": [[bids], [asks]], "time": ...}
        Each level: [{"px": price, "sz": size, "n": order_count}]
        """
        return self._post_info({"type": "l2Book", "coin": coin, "nSigFigs": 5})

    def get_orderbook_summary(self, coin: str = "BTC") -> dict:
        """Compute order book imbalance and depth within 1% of mid."""
        book = self.get_order_book(coin)
        mid = self.get_btc_price()

        levels = book.get("levels", [[], []])
        bids = levels[0] if len(levels) > 0 else []
        asks = levels[1] if len(levels) > 1 else []

        # Depth within 1% of mid
        bid_threshold = mid * 0.99
        ask_threshold = mid * 1.01

        bid_depth = sum(
            float(b["sz"]) for b in bids if float(b["px"]) >= bid_threshold
        )
        ask_depth = sum(
            float(a["sz"]) for a in asks if float(a["px"]) <= ask_threshold
        )

        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0

        return {
            "mid": mid,
            "best_bid": float(bids[0]["px"]) if bids else 0,
            "best_ask": float(asks[0]["px"]) if asks else 0,
            "spread_bps": ((float(asks[0]["px"]) - float(bids[0]["px"])) / mid * 10000)
            if bids and asks else 0,
            "bid_depth_1pct": bid_depth,
            "ask_depth_1pct": ask_depth,
            "bid_ask_imbalance": imbalance,
        }

    # ---- Meta & Asset Contexts (funding, OI, volume) ----

    def get_meta_and_contexts(self) -> tuple[dict, list[dict]]:
        """
        Get metadata + per-asset contexts (funding, OI, prices, volume).
        Returns (meta, asset_contexts).
        meta["universe"] lists all perps with their index.
        """
        result = self._post_info({"type": "metaAndAssetCtxs"})
        return result[0], result[1]

    def get_btc_context(self) -> dict:
        """Get BTC-specific asset context (funding, OI, prices)."""
        meta, ctxs = self.get_meta_and_contexts()
        universe = meta.get("universe", [])
        for i, asset in enumerate(universe):
            if asset.get("name") == "BTC":
                return ctxs[i]
        return {}

    # ---- Funding Rates ----

    def get_current_funding(self, coin: str = "BTC") -> dict:
        """Get current funding rate for a coin."""
        ctx = self.get_btc_context() if coin == "BTC" else {}
        return {
            "coin": coin,
            "funding_rate": float(ctx.get("funding", 0)),
            "premium": float(ctx.get("premium", 0)),
            "oracle_price": float(ctx.get("oraclePx", 0)),
            "mark_price": float(ctx.get("markPx", 0)),
        }

    def get_predicted_fundings(self) -> list:
        """Get predicted funding rates across venues."""
        return self._post_info({"type": "predictedFundings"})

    def get_funding_history(
        self, coin: str = "BTC", start_time: int = 0, end_time: Optional[int] = None
    ) -> list:
        """Get historical funding rates."""
        payload = {"type": "fundingHistory", "coin": coin, "startTime": start_time}
        if end_time:
            payload["endTime"] = end_time
        return self._post_info(payload)

    # ---- Open Interest ----

    def get_open_interest(self, coin: str = "BTC") -> dict:
        """Get current open interest for a coin."""
        ctx = self.get_btc_context() if coin == "BTC" else {}
        oi = float(ctx.get("openInterest", 0))
        mark = float(ctx.get("markPx", 0))
        return {
            "coin": coin,
            "open_interest_btc": oi,
            "open_interest_usd": oi * mark,
            "day_volume_usd": float(ctx.get("dayNtlVlm", 0)),
        }

    # ---- Whale Position Tracking ----

    def get_user_positions(self, address: str) -> dict:
        """
        Query any wallet's full clearinghouse state.
        Returns positions, margin, leverage — fully transparent on-chain data.
        """
        return self._post_info({"type": "clearinghouseState", "user": address})

    def get_whale_btc_position(self, address: str) -> Optional[dict]:
        """
        Get a specific wallet's BTC position.
        Returns None if no BTC position open.
        """
        state = self.get_user_positions(address)
        positions = state.get("assetPositions", [])
        for pos_wrapper in positions:
            pos = pos_wrapper.get("position", {})
            if pos.get("coin") == "BTC":
                szi = float(pos.get("szi", 0))
                return {
                    "address": address,
                    "coin": "BTC",
                    "size": szi,  # positive=long, negative=short
                    "entry_price": float(pos.get("entryPx", 0)),
                    "liquidation_price": float(pos.get("liquidationPx", 0))
                    if pos.get("liquidationPx")
                    else None,
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                    "position_value_usd": abs(szi) * float(pos.get("entryPx", 0)),
                    "margin_used": float(pos.get("marginUsed", 0)),
                    "leverage": float(
                        pos.get("leverage", {}).get("value", 1)
                    ),
                    "leverage_type": pos.get("leverage", {}).get("type", "cross"),
                    "return_on_equity": float(pos.get("returnOnEquity", 0)),
                }
        return None

    def get_whale_all_positions(self, address: str) -> list[dict]:
        """Get all open positions for a wallet."""
        state = self.get_user_positions(address)
        positions = []
        for pos_wrapper in state.get("assetPositions", []):
            pos = pos_wrapper.get("position", {})
            szi = float(pos.get("szi", 0))
            if szi == 0:
                continue
            positions.append({
                "coin": pos.get("coin"),
                "size": szi,
                "entry_price": float(pos.get("entryPx", 0)),
                "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                "position_value_usd": abs(szi) * float(pos.get("entryPx", 0)),
            })
        return positions

    # ---- Recent Trades ----

    def get_recent_trades(self, coin: str = "BTC") -> list:
        """Get recent trades for a coin."""
        return self._post_info({"type": "recentTrades", "coin": coin})

    # ---- Candles (OHLCV) ----

    def get_candles(
        self,
        coin: str = "BTC",
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        """
        Get candle data. Interval: 1m, 5m, 15m, 1h, 4h, 1d, etc.
        Returns list of {"t": timestamp, "T": close_time, "s": coin,
                         "i": interval, "o": open, "c": close, "h": high,
                         "l": low, "v": volume, "n": num_trades}
        """
        now_ms = int(time.time() * 1000)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time or (now_ms - 86400 * 1000),  # last 24h
                "endTime": end_time or now_ms,
            },
        }
        return self._post_info(payload)

    # ----------------------------------------------------------------
    # WebSocket — real-time streaming
    # ----------------------------------------------------------------

    async def connect_ws(self):
        """Establish WebSocket connection."""
        self._ws = await websockets.connect(WS_URL)
        self._running = True
        logger.info("Hyperliquid WebSocket connected")

    async def subscribe(self, subscription: dict, callback: Callable):
        """
        Subscribe to a WebSocket channel.
        subscription examples:
          {"type": "trades", "coin": "BTC"}
          {"type": "l2Book", "coin": "BTC"}
          {"type": "candle", "coin": "BTC", "interval": "1m"}
          {"type": "allMids"}
        """
        if not self._ws:
            await self.connect_ws()

        key = json.dumps(subscription, sort_keys=True)
        if key not in self._ws_callbacks:
            self._ws_callbacks[key] = []
        self._ws_callbacks[key].append(callback)

        await self._ws.send(json.dumps({
            "method": "subscribe",
            "subscription": subscription,
        }))
        logger.info(f"Subscribed to {subscription}")

    async def _listen(self):
        """Listen for WebSocket messages and dispatch to callbacks."""
        while self._running and self._ws:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(msg)

                # Match message to subscription callbacks
                channel = data.get("channel")
                sub_data = data.get("data")

                if channel and sub_data:
                    for key, callbacks in self._ws_callbacks.items():
                        sub = json.loads(key)
                        if sub.get("type") == channel:
                            for cb in callbacks:
                                try:
                                    if asyncio.iscoroutinefunction(cb):
                                        await cb(sub_data)
                                    else:
                                        cb(sub_data)
                                except Exception as e:
                                    logger.error(f"Callback error: {e}")

            except asyncio.TimeoutError:
                # Send ping to keep alive
                if self._ws:
                    await self._ws.send(json.dumps({"method": "ping"}))
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket disconnected, reconnecting...")
                await self._reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(1)

    async def _reconnect(self):
        """Reconnect with exponential backoff."""
        for attempt in range(4):
            delay = 2 ** (attempt + 1)
            logger.info(f"Reconnecting in {delay}s (attempt {attempt + 1}/4)")
            await asyncio.sleep(delay)
            try:
                await self.connect_ws()
                # Re-subscribe to all channels
                for key in self._ws_callbacks:
                    sub = json.loads(key)
                    await self._ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": sub,
                    }))
                logger.info("Reconnected and re-subscribed")
                return
            except Exception as e:
                logger.error(f"Reconnect attempt {attempt + 1} failed: {e}")

    async def start_streaming(self):
        """Start the WebSocket listener loop."""
        if not self._ws:
            await self.connect_ws()
        await self._listen()

    async def close(self):
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    # ----------------------------------------------------------------
    # Compound data methods for agents
    # ----------------------------------------------------------------

    def get_btc_full_snapshot(self) -> dict:
        """
        Get a comprehensive BTC data snapshot for the prediction cycle.
        Combines price, order book, funding, OI, and recent trades.
        """
        ctx = self.get_btc_context()
        book_summary = self.get_orderbook_summary("BTC")
        predicted = self.get_predicted_fundings()

        # Find BTC predicted funding
        btc_predicted = None
        for entry in predicted:
            if isinstance(entry, list):
                for item in entry:
                    if isinstance(item, dict) and item.get("coin") == "BTC":
                        btc_predicted = item
                        break

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": {
                "mark": float(ctx.get("markPx", 0)),
                "oracle": float(ctx.get("oraclePx", 0)),
                "mid": float(ctx.get("midPx", 0)) if ctx.get("midPx") else book_summary["mid"],
            },
            "order_book": book_summary,
            "funding": {
                "current_rate": float(ctx.get("funding", 0)),
                "premium": float(ctx.get("premium", 0)),
                "predicted": btc_predicted,
            },
            "open_interest": {
                "btc": float(ctx.get("openInterest", 0)),
                "usd": float(ctx.get("openInterest", 0)) * float(ctx.get("markPx", 0)),
            },
            "volume_24h_usd": float(ctx.get("dayNtlVlm", 0)),
            "prev_day_price": float(ctx.get("prevDayPx", 0)),
        }
