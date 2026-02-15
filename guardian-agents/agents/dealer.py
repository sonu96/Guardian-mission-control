"""
Dealer Agent — Polymarket-Only Trade Executor.

Responsibilities:
  - Execute trades ONLY on Polymarket (1h BTC UP/DOWN binary markets)
  - Place limit orders on CLOB for better fills
  - Track open positions and pending orders
  - Handle order fills and position management
  - NO Hyperliquid trading — HL is data source only

Bus topics consumed:
  - "prediction_decision": PredictionDecision (from Strategist)

Bus topics published:
  - "trade_executed": dict with trade details
  - "position_status": dict with current position
"""

from datetime import datetime, timezone
from typing import Any, Optional

from agents.base import BaseAgent, AgentBus
from models.signals import PredictionDecision, Direction
from config.settings import settings


class DealerAgent(BaseAgent):
    """Executes prediction trades on Polymarket only."""

    def __init__(self, bus: AgentBus):
        super().__init__("dealer", bus)

        # Position tracking
        self._current_position: Optional[dict] = None
        self._pending_orders: list[dict] = []
        self._trade_history: list[dict] = []

    async def start(self):
        await super().start()
        self.logger.info(
            f"Dealer ready — Polymarket executor | "
            f"Max position: ${settings.polymarket.max_position_usd}"
        )

    def _find_btc_market(self) -> Optional[dict]:
        """
        Find the current 1-hour BTC UP/DOWN prediction market on Polymarket.

        In production, this queries the Polymarket CLOB API for active
        BTC hourly markets. For now, returns the market structure.
        """
        # TODO: Query Polymarket API for active BTC 1h markets
        # GET https://clob.polymarket.com/markets
        # Filter for: BTC, 1-hour resolution, currently tradeable
        #
        # Market structure:
        # {
        #     "condition_id": "0x...",
        #     "question": "Will BTC go up in the next hour?",
        #     "tokens": [
        #         {"token_id": "YES_TOKEN_ID", "outcome": "Yes", "price": 0.52},
        #         {"token_id": "NO_TOKEN_ID", "outcome": "No", "price": 0.48},
        #     ],
        #     "end_date_iso": "2026-02-15T15:00:00Z",
        # }
        return None

    async def _place_order(
        self,
        token_id: str,
        side: str,  # "BUY" or "SELL"
        size: float,
        price: float,
    ) -> Optional[dict]:
        """
        Place an order on Polymarket CLOB.

        In production, uses py-clob-client:
            from py_clob_client.client import ClobClient
            client = ClobClient(host, key, chain_id, ...)
            order = client.create_and_post_order(OrderArgs(...))
        """
        # TODO: Implement actual Polymarket order execution
        # from py_clob_client.client import ClobClient
        # from py_clob_client.clob_types import OrderArgs, OrderType
        #
        # client = ClobClient(
        #     host=settings.polymarket.host,
        #     key=settings.polymarket.private_key,
        #     chain_id=settings.polymarket.chain_id,
        #     creds=ApiCreds(
        #         api_key=settings.polymarket.api_key,
        #         api_secret=settings.polymarket.api_secret,
        #         api_passphrase=settings.polymarket.api_passphrase,
        #     ),
        # )
        #
        # order = client.create_and_post_order(OrderArgs(
        #     token_id=token_id,
        #     price=price,
        #     size=size,
        #     side=side,
        #     order_type=OrderType.GTC,
        # ))

        self.logger.info(
            f"ORDER: {side} {size:.4f} shares @ ${price:.4f} (token: {token_id[:10]}...)"
        )

        return {
            "order_id": f"sim_{datetime.now(timezone.utc).timestamp()}",
            "token_id": token_id,
            "side": side,
            "size": size,
            "price": price,
            "status": "PLACED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def run_cycle(self, cycle_id: str) -> dict:
        """
        Execute trade based on Strategist's decision.
        """
        decision: Optional[PredictionDecision] = self.get_signal("prediction_decision")

        if not decision:
            self.logger.warning("No prediction decision available — skipping")
            return {"action": "skip", "reason": "no_decision"}

        if not decision.should_trade:
            self.logger.info(f"Strategist says SKIP: {decision.skip_reason}")
            await self.publish("trade_executed", {
                "cycle_id": cycle_id,
                "action": "skip",
                "reason": decision.skip_reason,
                "direction": decision.direction.value,
                "confidence": decision.confidence,
            })
            return {"action": "skip", "reason": decision.skip_reason}

        # Find the active BTC 1h market
        market = self._find_btc_market()

        if not market:
            self.logger.warning("No active BTC 1h market found on Polymarket")
            # In development mode, simulate the trade
            trade = self._simulate_trade(decision, cycle_id)
            await self.publish("trade_executed", trade)
            return trade

        # Determine which token to buy
        # If prediction is UP → buy YES token
        # If prediction is DOWN → buy NO token
        tokens = market.get("tokens", [])
        if decision.direction == Direction.UP:
            target_token = next(
                (t for t in tokens if t["outcome"].lower() == "yes"), None
            )
        else:
            target_token = next(
                (t for t in tokens if t["outcome"].lower() == "no"), None
            )

        if not target_token:
            self.logger.error("Could not find target token in market")
            return {"action": "error", "reason": "token_not_found"}

        # Calculate number of shares
        token_price = target_token["price"]
        shares = decision.position_size_usd / token_price

        # Place order
        order = await self._place_order(
            token_id=target_token["token_id"],
            side="BUY",
            size=shares,
            price=token_price,
        )

        trade = {
            "cycle_id": cycle_id,
            "action": "trade",
            "direction": decision.direction.value,
            "confidence": decision.confidence,
            "market_id": market.get("condition_id"),
            "token_id": target_token["token_id"],
            "outcome": target_token["outcome"],
            "price": token_price,
            "shares": shares,
            "cost_usd": decision.position_size_usd,
            "order": order,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._current_position = trade
        self._trade_history.append(trade)

        await self.publish("trade_executed", trade)
        self.logger.info(
            f"Dealer: {decision.direction.value} — "
            f"Bought {shares:.2f} {target_token['outcome']} shares @ ${token_price:.4f} "
            f"(${decision.position_size_usd:.2f})"
        )

        return trade

    def _simulate_trade(self, decision: PredictionDecision, cycle_id: str) -> dict:
        """Simulate a trade for development/testing."""
        # Simulated prices based on direction
        if decision.direction == Direction.UP:
            sim_price = 0.50 + (decision.confidence - 0.5) * 0.3
            outcome = "YES"
        else:
            sim_price = 0.50 + (decision.confidence - 0.5) * 0.3
            outcome = "NO"

        shares = decision.position_size_usd / sim_price

        trade = {
            "cycle_id": cycle_id,
            "action": "simulated_trade",
            "direction": decision.direction.value,
            "confidence": decision.confidence,
            "outcome": outcome,
            "price": round(sim_price, 4),
            "shares": round(shares, 2),
            "cost_usd": decision.position_size_usd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._current_position = trade
        self._trade_history.append(trade)

        self.logger.info(
            f"Dealer (SIM): {decision.direction.value} — "
            f"{shares:.2f} {outcome} shares @ ${sim_price:.4f}"
        )

        return trade

    @property
    def trade_history(self) -> list[dict]:
        return self._trade_history
