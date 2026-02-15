"""
Dealer Agent — Polymarket-Only Trade Executor with Active Position Management.

Responsibilities:
  - Execute trades ONLY on Polymarket (5-min BTC UP/DOWN binary markets)
  - Place limit orders on CLOB for better fills (or market orders if configured)
  - ACTIVELY MONITOR positions during the 5-minute window
  - Exit early when conditions are met (take profit, trailing stop, stop loss)
  - Run mid-window signal re-check for signal flip detection
  - NO Hyperliquid trading — HL is data source only

Position Lifecycle:
  1. ENTER  — Buy YES/NO shares based on Strategist decision
  2. MONITOR — Poll BTC price every 10s, estimate share price, check exits
  3. EXIT   — One of:
     a) TAKE PROFIT    — Share price up enough, lock in gains
     b) TRAILING STOP  — Price peaked then pulled back, protect gains
     c) STOP LOSS      — Share price dropped too far, cut losses
     d) SIGNAL FLIP    — Mid-window data says original signal reversed
     e) TIME EXIT      — Held to resolution (market settles at $0 or $1)

Bus topics consumed:
  - "prediction_decision": PredictionDecision (from Strategist)
  - "price_snapshot": PriceSnapshot (from Oracle, for entry BTC price)

Bus topics published:
  - "trade_executed": dict with trade details
  - "position_update": dict with live position state
  - "position_closed": dict with final position result
"""

import time
from datetime import datetime, timezone
from typing import Any, Optional

from agents.base import BaseAgent, AgentBus
from models.signals import PredictionDecision, Direction
from services.position_manager import PositionManager, ExitStrategy, ExitReason, PositionState
from services.hyperliquid_client import HyperliquidClient
from services.polymarket_client import PolymarketClient
from config.settings import settings


class DealerAgent(BaseAgent):
    """Executes and actively manages prediction trades on Polymarket."""

    def __init__(self, bus: AgentBus, hl_client: HyperliquidClient, poly_client: PolymarketClient):
        super().__init__("dealer", bus)
        self.hl = hl_client
        self.poly = poly_client

        # Position management
        self.position_manager = PositionManager(
            hl_client=hl_client,
            strategy=ExitStrategy(
                take_profit_pct=settings.agent.exit_take_profit_pct,
                trailing_stop_pct=settings.agent.exit_trailing_stop_pct,
                stop_loss_pct=settings.agent.exit_stop_loss_pct,
                mid_window_check_minute=settings.agent.exit_mid_check_minute,
                min_hold_seconds=settings.agent.exit_min_hold_seconds,
                poll_interval=settings.agent.exit_poll_interval,
            ),
            on_exit=self._on_position_exit,
            on_tick=self._on_price_tick,
        )

        # History
        self._trade_history: list[dict] = []
        self._early_exits = 0
        self._time_exits = 0

    async def start(self):
        await super().start()
        strategy = self.position_manager.strategy
        mode = "LIVE" if self.poly.is_ready else "SIMULATION"
        self.logger.info(
            f"Dealer ready — {mode} mode | "
            f"Max: ${settings.polymarket.max_position_usd} | "
            f"TP: {strategy.take_profit_pct}% | "
            f"Trail: {strategy.trailing_stop_pct}% | "
            f"SL: {strategy.stop_loss_pct}% | "
            f"Poll: {strategy.poll_interval}s"
        )
        if self.poly.is_ready:
            balance = self.poly.get_usdc_balance()
            self.logger.info(f"Wallet USDC balance: ${balance:.2f}")

    def _on_position_exit(self, position: PositionState, reason: ExitReason):
        """Callback when PositionManager exits a position."""
        if reason == ExitReason.TIME_EXIT:
            self._time_exits += 1
        else:
            self._early_exits += 1

        self.logger.info(
            f"Position closed: {reason.value} | "
            f"PnL: ${position.realized_pnl:+.2f} | "
            f"Held: {position.hold_duration_seconds/60:.1f}min | "
            f"BTC: {position.btc_change_pct:+.2f}%"
        )

    def _on_price_tick(self, position: PositionState, tick_count: int):
        """Callback on each price tick — publishes live position to bus."""
        pass  # Position logging happens in PositionManager

    def _find_btc_market(self) -> Optional[dict]:
        """
        Find the current 5-minute BTC UP/DOWN prediction market on Polymarket.
        Uses Gamma API via PolymarketClient.
        """
        return self.poly.find_btc_5min_market()

    async def _place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        cost_usd: float,
    ) -> Optional[dict]:
        """
        Place an order on Polymarket CLOB.
        Uses limit orders by default, market orders if configured.
        """
        if not self.poly.is_ready:
            # Simulation mode — return mock order
            self.logger.info(
                f"SIM ORDER: {side} {size:.4f} shares @ ${price:.4f} (token: {token_id[:10]}...)"
            )
            return {
                "order_id": f"sim_{datetime.now(timezone.utc).timestamp()}",
                "token_id": token_id,
                "side": side,
                "size": size,
                "price": price,
                "status": "SIMULATED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if settings.polymarket.use_market_orders:
            resp = self.poly.place_market_order(token_id=token_id, amount=cost_usd)
        else:
            resp = self.poly.place_limit_order(
                token_id=token_id,
                side=side,
                size=size,
                price=price,
            )

        if resp:
            self.logger.info(
                f"ORDER PLACED: {side} {size:.4f} shares @ ${price:.4f} "
                f"(token: {token_id[:10]}...)"
            )
            return {
                "order_id": resp.get("orderID") or resp.get("id", "unknown"),
                "token_id": token_id,
                "side": side,
                "size": size,
                "price": price,
                "status": "PLACED",
                "response": resp,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        self.logger.error(f"Order placement failed for {side} {size:.4f} @ ${price:.4f}")
        return None

    async def _sell_position(self, position: PositionState) -> Optional[dict]:
        """
        Sell current Polymarket position for early exit.
        Places a SELL limit order slightly below estimated price for faster fill.
        """
        if not self.poly.is_ready:
            self.logger.info(
                f"SIM SELL: {position.shares:.4f} shares @ "
                f"~${position.estimated_share_price:.4f}"
            )
            return {
                "order_id": f"sim_sell_{datetime.now(timezone.utc).timestamp()}",
                "side": "SELL",
                "size": position.shares,
                "price": position.estimated_share_price,
                "status": "SIMULATED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Sell slightly below estimated price for faster fill
        slippage = settings.polymarket.limit_order_slippage
        sell_price = max(0.01, position.estimated_share_price - slippage)

        # Get the token_id from the trade that opened this position
        token_id = self._get_position_token_id(position.cycle_id)
        if not token_id:
            self.logger.error("Cannot sell — no token_id found for position")
            return None

        resp = self.poly.place_limit_order(
            token_id=token_id,
            side="SELL",
            size=position.shares,
            price=round(sell_price, 2),
        )

        if resp:
            self.logger.info(
                f"SELL ORDER: {position.shares:.4f} shares @ ${sell_price:.4f} "
                f"(est: ${position.estimated_share_price:.4f})"
            )
            return {
                "order_id": resp.get("orderID") or resp.get("id", "unknown"),
                "side": "SELL",
                "size": position.shares,
                "price": sell_price,
                "status": "PLACED",
                "response": resp,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        self.logger.error("Sell order failed")
        return None

    def _get_position_token_id(self, cycle_id: str) -> Optional[str]:
        """Look up the token_id from trade history for a given cycle."""
        for trade in reversed(self._trade_history):
            if trade.get("cycle_id") == cycle_id and trade.get("token_id"):
                return trade["token_id"]
        return None

    async def run_cycle(self, cycle_id: str) -> dict:
        """
        Execute trade based on Strategist's decision.
        This only handles ENTRY. Monitoring is done separately via monitor_position().
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

        # Get current BTC price for position tracking
        try:
            entry_btc_price = self.hl.get_btc_price()
        except Exception:
            entry_btc_price = 0.0

        # Find the active BTC 5-min market
        market = self._find_btc_market()

        if not market:
            if self.poly.is_ready:
                self.logger.warning("No BTC market found — cannot trade")
                return {"action": "skip", "reason": "no_market_found"}
            # Simulation mode: simulate the trade
            trade = self._simulate_trade(decision, cycle_id, entry_btc_price)
            await self.publish("trade_executed", trade)
            return trade

        # Determine which token to buy
        tokens = market.get("tokens", [])
        if decision.direction == Direction.UP:
            target_token = next(
                (t for t in tokens if t["outcome"].upper() in ("YES", "UP")), None
            )
        else:
            target_token = next(
                (t for t in tokens if t["outcome"].upper() in ("NO", "DOWN")), None
            )

        if not target_token:
            self.logger.error("Could not find target token in market")
            return {"action": "error", "reason": "token_not_found"}

        # Get live CLOB price if available, else use Gamma price
        token_id = target_token["token_id"]
        live_price = self.poly.get_price(token_id) if self.poly.is_ready else None
        token_price = live_price or target_token["price"]

        # Calculate shares and place order
        shares = decision.position_size_usd / token_price

        order = await self._place_order(
            token_id=token_id,
            side="BUY",
            size=round(shares, 2),
            price=round(token_price, 2),
            cost_usd=decision.position_size_usd,
        )

        if not order:
            self.logger.error("Order placement failed")
            return {"action": "error", "reason": "order_failed"}

        # Register with PositionManager for active monitoring
        self.position_manager.open_position(
            cycle_id=cycle_id,
            direction=decision.direction.value,
            entry_price=token_price,
            shares=shares,
            cost_usd=decision.position_size_usd,
            entry_btc_price=entry_btc_price,
        )

        trade = {
            "cycle_id": cycle_id,
            "action": "trade",
            "direction": decision.direction.value,
            "confidence": decision.confidence,
            "market_id": market.get("condition_id"),
            "token_id": token_id,
            "outcome": target_token["outcome"],
            "entry_price": token_price,
            "shares": shares,
            "cost_usd": decision.position_size_usd,
            "entry_btc_price": entry_btc_price,
            "order": order,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._trade_history.append(trade)
        await self.publish("trade_executed", trade)

        self.logger.info(
            f"Dealer: ENTERED {decision.direction.value} — "
            f"{shares:.2f} shares @ ${token_price:.4f} "
            f"(${decision.position_size_usd:.2f}) | "
            f"BTC @ ${entry_btc_price:,.2f} | "
            f"Now monitoring for {settings.agent.cycle_minutes}min..."
        )

        return trade

    async def monitor_position(self, signal_check_fn=None) -> Optional[dict]:
        """
        Run active position monitoring for the duration of the window.
        Called by Orchestrator AFTER run_cycle().

        Args:
            signal_check_fn: Optional async callable(position) -> bool.
                           Returns True if signal has flipped and we should exit.
                           Called once at the mid-window mark.

        Returns:
            Position summary dict, or None if no position.
        """
        if not self.position_manager.has_position:
            return None

        window_seconds = settings.agent.cycle_minutes * 60

        # Run the monitoring loop (blocks for up to window_seconds)
        final_state = await self.position_manager.monitor_position(
            window_seconds=window_seconds,
            signal_check_fn=signal_check_fn,
        )

        # If early exit, sell the position
        if final_state.exit_reason and final_state.exit_reason != ExitReason.TIME_EXIT:
            sell_order = await self._sell_position(final_state)
            self.logger.info(
                f"Early exit executed: {final_state.exit_reason.value} | "
                f"Sell @ ~${final_state.exit_share_price:.4f}"
            )

        # Publish final position state
        summary = self.position_manager.get_position_summary()
        await self.publish("position_closed", summary)

        return summary

    def _simulate_trade(
        self, decision: PredictionDecision, cycle_id: str, entry_btc_price: float
    ) -> dict:
        """Simulate a trade for development/testing."""
        if decision.direction == Direction.UP:
            sim_price = 0.50 + (decision.confidence - 0.5) * 0.3
            outcome = "YES"
        else:
            sim_price = 0.50 + (decision.confidence - 0.5) * 0.3
            outcome = "NO"

        shares = decision.position_size_usd / sim_price

        # Register with PositionManager even in simulation
        self.position_manager.open_position(
            cycle_id=cycle_id,
            direction=decision.direction.value,
            entry_price=round(sim_price, 4),
            shares=round(shares, 2),
            cost_usd=decision.position_size_usd,
            entry_btc_price=entry_btc_price,
        )

        trade = {
            "cycle_id": cycle_id,
            "action": "simulated_trade",
            "direction": decision.direction.value,
            "confidence": decision.confidence,
            "outcome": outcome,
            "entry_price": round(sim_price, 4),
            "shares": round(shares, 2),
            "cost_usd": decision.position_size_usd,
            "entry_btc_price": entry_btc_price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._trade_history.append(trade)
        self.logger.info(
            f"Dealer (SIM): ENTERED {decision.direction.value} — "
            f"{shares:.2f} {outcome} shares @ ${sim_price:.4f} | "
            f"BTC @ ${entry_btc_price:,.2f}"
        )

        return trade

    @property
    def trade_history(self) -> list[dict]:
        return self._trade_history

    @property
    def stats(self) -> dict:
        return {
            "total_trades": len(self._trade_history),
            "early_exits": self._early_exits,
            "time_exits": self._time_exits,
            "early_exit_rate": (
                self._early_exits / max(self._early_exits + self._time_exits, 1)
            ),
        }
