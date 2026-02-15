"""
Position Manager — Active trade monitoring during the 5-minute window.

The core problem: Polymarket 5-min BTC markets resolve at the candle close.
But the share PRICE on the CLOB moves in real-time as BTC moves during
the window. This means:

  - If we buy YES @ $0.55 and BTC pumps early, YES shares might trade
    at $0.80 mid-window. We can SELL early and lock in profit without
    waiting for resolution.

  - If BTC dumps against us, YES shares drop to $0.30. We can cut losses
    early instead of riding to zero.

  - If BTC is flat, share prices stay near entry. We hold to resolution.

This is the key insight: Polymarket shares are TRADEABLE DURING the window.
We don't have to hold to expiry like a binary option. We can actively
manage the position.

Exit Strategy Hierarchy:
  1. TAKE PROFIT    — Share price hits target (e.g., bought @ 0.55, sell @ 0.80)
  2. TRAILING STOP  — Price pulled back X% from peak during this window
  3. STOP LOSS      — Share price drops below hard floor (cut losses)
  4. SIGNAL FLIP    — Mid-window data check shows signal reversed
  5. TIME EXIT      — Hold to resolution if none of the above trigger

The PositionManager polls Hyperliquid BTC price every 10s during the window.
It estimates what the Polymarket share price SHOULD be based on BTC movement,
and triggers exits accordingly.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass, field

from services.hyperliquid_client import HyperliquidClient
from config.settings import settings

logger = logging.getLogger(__name__)


class ExitReason(str, Enum):
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    STOP_LOSS = "stop_loss"
    SIGNAL_FLIP = "signal_flip"
    TIME_EXIT = "time_exit"         # Held to resolution
    MANUAL = "manual"


@dataclass
class ExitStrategy:
    """Configurable exit parameters."""

    # Take profit: sell when share price appreciation reaches this %
    take_profit_pct: float = 40.0  # e.g., bought @ 0.55, sell @ 0.77

    # Trailing stop: after share price peaks, exit if it drops by this %
    trailing_stop_pct: float = 15.0

    # Hard stop loss: exit if share price drops below this % of entry
    stop_loss_pct: float = 30.0  # e.g., bought @ 0.55, cut at 0.385

    # Signal flip: run a mid-window data check at this minute mark
    mid_window_check_minute: int = 2

    # Minimum hold time before any exit (avoid whipsaws), in seconds
    min_hold_seconds: int = 30  # 30 seconds

    # How often to check BTC price (seconds)
    poll_interval: int = 10


@dataclass
class PositionState:
    """Tracks the live state of an open position."""

    # Entry
    cycle_id: str
    direction: str  # "UP" or "DOWN"
    entry_price: float  # Polymarket share price at entry
    shares: float
    cost_usd: float
    entry_btc_price: float  # BTC price when we entered
    entered_at: float  # timestamp

    # Live tracking
    current_btc_price: float = 0.0
    estimated_share_price: float = 0.0
    peak_share_price: float = 0.0  # highest estimated share price since entry
    trough_share_price: float = 999999.0  # lowest
    btc_change_pct: float = 0.0

    # Price history during window (for analysis)
    btc_price_ticks: list = field(default_factory=list)
    share_price_ticks: list = field(default_factory=list)

    # Exit
    exited: bool = False
    exit_reason: Optional[ExitReason] = None
    exit_share_price: float = 0.0
    exit_btc_price: float = 0.0
    exited_at: Optional[float] = None
    realized_pnl: float = 0.0

    def update_btc_price(self, btc_price: float):
        """
        Update position state with new BTC price.

        Estimates what the Polymarket share price should be based on
        how BTC has moved since entry. This is an approximation —
        actual CLOB price may differ due to market dynamics.

        Pricing model:
          - BTC moves in our predicted direction → share price increases
          - BTC moves against us → share price decreases
          - Relationship is roughly: share_price ~ entry_price + delta * sensitivity

        For a 5-min BTC market, the share price sensitivity to BTC movement
        is higher than hourly markets since smaller moves matter more:
          - ~0.20 share price move per 0.1% BTC move (near 50/50 pricing)
          - Less sensitive near extremes (0.90+ or 0.10- share price)
        """
        self.current_btc_price = btc_price
        self.btc_change_pct = ((btc_price - self.entry_btc_price) / self.entry_btc_price) * 100

        # Estimate share price based on BTC movement relative to our direction
        if self.direction == "UP":
            # We hold YES shares: BTC up = good, BTC down = bad
            btc_signal = self.btc_change_pct
        else:
            # We hold NO shares: BTC down = good, BTC up = bad
            btc_signal = -self.btc_change_pct

        # Sensitivity: how much share price moves per 1% BTC move
        # Higher for 5-min markets since smaller BTC moves are more decisive
        base_sensitivity = 0.30  # ~30 cents per 1% BTC move (5-min markets are more sensitive)
        # Dampen near extremes using logistic-like curve
        dist_from_center = abs(self.entry_price - 0.50)
        sensitivity = base_sensitivity * (1.0 - dist_from_center * 1.5)
        sensitivity = max(0.05, sensitivity)  # floor

        raw_estimate = self.entry_price + (btc_signal * sensitivity)
        # Clamp to valid share price range [0.01, 0.99]
        self.estimated_share_price = max(0.01, min(0.99, raw_estimate))

        # Track peaks and troughs
        self.peak_share_price = max(self.peak_share_price, self.estimated_share_price)
        self.trough_share_price = min(self.trough_share_price, self.estimated_share_price)

        # Record tick
        now = time.time()
        self.btc_price_ticks.append({"time": now, "price": btc_price})
        self.share_price_ticks.append({"time": now, "price": self.estimated_share_price})

    @property
    def unrealized_pnl(self) -> float:
        """Current unrealized PnL in USD."""
        if self.estimated_share_price <= 0:
            return -self.cost_usd
        return (self.estimated_share_price - self.entry_price) * self.shares

    @property
    def unrealized_pnl_pct(self) -> float:
        """Current unrealized PnL as percentage of cost."""
        if self.cost_usd <= 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_usd) * 100

    @property
    def peak_pnl_pct(self) -> float:
        """Peak unrealized PnL percentage since entry."""
        if self.cost_usd <= 0:
            return 0.0
        peak_pnl = (self.peak_share_price - self.entry_price) * self.shares
        return (peak_pnl / self.cost_usd) * 100

    @property
    def drawdown_from_peak_pct(self) -> float:
        """How far share price has dropped from its peak (percentage)."""
        if self.peak_share_price <= 0:
            return 0.0
        return ((self.peak_share_price - self.estimated_share_price) / self.peak_share_price) * 100

    @property
    def hold_duration_seconds(self) -> float:
        """How long we've held this position."""
        return time.time() - self.entered_at


class PositionManager:
    """
    Actively monitors and manages an open Polymarket position.

    Runs a polling loop during the 5-minute window that:
      1. Fetches BTC price from Hyperliquid every 10s
      2. Estimates current Polymarket share price
      3. Checks exit conditions (take profit, trailing stop, stop loss)
      4. Optionally runs a mid-window signal re-check
      5. Executes exit if triggered, or holds to resolution
    """

    def __init__(
        self,
        hl_client: HyperliquidClient,
        strategy: Optional[ExitStrategy] = None,
        on_exit: Optional[Callable] = None,
        on_tick: Optional[Callable] = None,
    ):
        self.hl = hl_client
        self.strategy = strategy or ExitStrategy()
        self.on_exit = on_exit  # Called when position is exited
        self.on_tick = on_tick  # Called every price tick
        self._position: Optional[PositionState] = None
        self._monitoring = False

    @property
    def position(self) -> Optional[PositionState]:
        return self._position

    @property
    def has_position(self) -> bool:
        return self._position is not None and not self._position.exited

    def open_position(
        self,
        cycle_id: str,
        direction: str,
        entry_price: float,
        shares: float,
        cost_usd: float,
        entry_btc_price: float,
    ) -> PositionState:
        """Register a new position to monitor."""
        self._position = PositionState(
            cycle_id=cycle_id,
            direction=direction,
            entry_price=entry_price,
            shares=shares,
            cost_usd=cost_usd,
            entry_btc_price=entry_btc_price,
            entered_at=time.time(),
            current_btc_price=entry_btc_price,
            estimated_share_price=entry_price,
            peak_share_price=entry_price,
            trough_share_price=entry_price,
        )
        logger.info(
            f"Position opened: {direction} | {shares:.2f} shares @ ${entry_price:.4f} | "
            f"BTC entry: ${entry_btc_price:,.2f} | Cost: ${cost_usd:.2f}"
        )
        return self._position

    def _check_exit_conditions(self) -> Optional[ExitReason]:
        """
        Evaluate all exit conditions against current position state.
        Returns the exit reason if triggered, None otherwise.
        """
        pos = self._position
        if not pos or pos.exited:
            return None

        # Respect minimum hold time
        if pos.hold_duration_seconds < self.strategy.min_hold_seconds:
            return None

        # 1. TAKE PROFIT
        if pos.unrealized_pnl_pct >= self.strategy.take_profit_pct:
            logger.info(
                f"TAKE PROFIT triggered: +{pos.unrealized_pnl_pct:.1f}% "
                f"(target: {self.strategy.take_profit_pct}%)"
            )
            return ExitReason.TAKE_PROFIT

        # 2. TRAILING STOP — only after we've been in profit
        if pos.peak_pnl_pct > 5.0:  # Only activate after 5% peak profit
            if pos.drawdown_from_peak_pct >= self.strategy.trailing_stop_pct:
                logger.info(
                    f"TRAILING STOP triggered: -{pos.drawdown_from_peak_pct:.1f}% from peak "
                    f"(peak was +{pos.peak_pnl_pct:.1f}%, trail: {self.strategy.trailing_stop_pct}%)"
                )
                return ExitReason.TRAILING_STOP

        # 3. STOP LOSS
        if pos.unrealized_pnl_pct <= -self.strategy.stop_loss_pct:
            logger.info(
                f"STOP LOSS triggered: {pos.unrealized_pnl_pct:.1f}% "
                f"(limit: -{self.strategy.stop_loss_pct}%)"
            )
            return ExitReason.STOP_LOSS

        return None

    def _execute_exit(self, reason: ExitReason):
        """Mark the position as exited."""
        pos = self._position
        if not pos or pos.exited:
            return

        pos.exited = True
        pos.exit_reason = reason
        pos.exit_share_price = pos.estimated_share_price
        pos.exit_btc_price = pos.current_btc_price
        pos.exited_at = time.time()

        # Calculate realized PnL
        if reason == ExitReason.TIME_EXIT:
            # Held to resolution: PnL depends on actual BTC close vs open
            # If we predicted correctly: shares * $1.00 - cost
            # If wrong: -cost
            # We won't know until resolution, so estimate from current price
            pos.realized_pnl = pos.unrealized_pnl
        else:
            # Early exit: PnL = (exit_price - entry_price) * shares
            pos.realized_pnl = (pos.exit_share_price - pos.entry_price) * pos.shares

        hold_mins = pos.hold_duration_seconds / 60
        logger.info(
            f"Position EXITED: {reason.value} | "
            f"PnL: ${pos.realized_pnl:+.2f} ({pos.unrealized_pnl_pct:+.1f}%) | "
            f"BTC: ${pos.entry_btc_price:,.0f} -> ${pos.exit_btc_price:,.0f} "
            f"({pos.btc_change_pct:+.2f}%) | "
            f"Held: {hold_mins:.1f}min"
        )

        # Notify
        if self.on_exit:
            try:
                self.on_exit(pos, reason)
            except Exception as e:
                logger.error(f"Exit callback error: {e}")

    async def monitor_position(
        self,
        window_seconds: int = 300,
        signal_check_fn: Optional[Callable] = None,
    ) -> PositionState:
        """
        Main monitoring loop. Runs for the duration of the prediction window.

        Args:
            window_seconds: Total window duration (default 300 = 5 minutes)
            signal_check_fn: Optional async callable that returns True if
                           mid-window signal check says to flip/exit.
                           Called once at the mid-window mark.

        Returns:
            Final PositionState with exit details.
        """
        pos = self._position
        if not pos:
            raise ValueError("No position to monitor")

        self._monitoring = True
        start_time = time.time()
        end_time = start_time + window_seconds
        mid_check_done = False
        tick_count = 0

        logger.info(
            f"Monitoring started: {pos.direction} position | "
            f"Window: {window_seconds}s | Poll: every {self.strategy.poll_interval}s | "
            f"TP: {self.strategy.take_profit_pct}% | "
            f"Trail: {self.strategy.trailing_stop_pct}% | "
            f"SL: {self.strategy.stop_loss_pct}%"
        )

        try:
            while self._monitoring and time.time() < end_time and not pos.exited:
                tick_count += 1
                elapsed = time.time() - start_time
                remaining = end_time - time.time()

                # Fetch current BTC price from Hyperliquid
                try:
                    btc_price = self.hl.get_btc_price()
                    pos.update_btc_price(btc_price)
                except Exception as e:
                    logger.warning(f"BTC price fetch failed (tick {tick_count}): {e}")
                    await asyncio.sleep(self.strategy.poll_interval)
                    continue

                # Notify tick listener
                if self.on_tick:
                    try:
                        self.on_tick(pos, tick_count)
                    except Exception as e:
                        logger.error(f"Tick callback error: {e}")

                # Log every 5th tick (~2.5 min at 30s intervals)
                if tick_count % 5 == 0:
                    logger.info(
                        f"  Tick {tick_count} | "
                        f"BTC ${btc_price:,.2f} ({pos.btc_change_pct:+.2f}%) | "
                        f"Share ~${pos.estimated_share_price:.4f} "
                        f"(PnL: ${pos.unrealized_pnl:+.2f} / {pos.unrealized_pnl_pct:+.1f}%) | "
                        f"Peak: ${pos.peak_share_price:.4f} | "
                        f"Remaining: {remaining/60:.0f}min"
                    )

                # Check exit conditions
                exit_reason = self._check_exit_conditions()
                if exit_reason:
                    self._execute_exit(exit_reason)
                    break

                # Mid-window signal re-check
                if (
                    not mid_check_done
                    and signal_check_fn
                    and elapsed >= self.strategy.mid_window_check_minute * 60
                ):
                    mid_check_done = True
                    logger.info("Running mid-window signal re-check...")
                    try:
                        should_exit = await signal_check_fn(pos)
                        if should_exit:
                            logger.info("Mid-window check says EXIT — signal flipped")
                            self._execute_exit(ExitReason.SIGNAL_FLIP)
                            break
                    except Exception as e:
                        logger.warning(f"Mid-window signal check failed: {e}")

                # Wait for next tick
                await asyncio.sleep(self.strategy.poll_interval)

            # If we made it to the end without exiting, it's a time exit
            if not pos.exited:
                # Final price check
                try:
                    btc_price = self.hl.get_btc_price()
                    pos.update_btc_price(btc_price)
                except Exception:
                    pass
                self._execute_exit(ExitReason.TIME_EXIT)

        except asyncio.CancelledError:
            logger.info("Position monitoring cancelled")
            if not pos.exited:
                self._execute_exit(ExitReason.MANUAL)
        finally:
            self._monitoring = False

        return pos

    def stop_monitoring(self):
        """Stop the monitoring loop (for emergency shutdown)."""
        self._monitoring = False

    def get_position_summary(self) -> Optional[dict]:
        """Get a summary dict of the current position for reporting."""
        pos = self._position
        if not pos:
            return None

        return {
            "cycle_id": pos.cycle_id,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "shares": pos.shares,
            "cost_usd": pos.cost_usd,
            "entry_btc_price": pos.entry_btc_price,
            "current_btc_price": pos.current_btc_price,
            "btc_change_pct": round(pos.btc_change_pct, 4),
            "estimated_share_price": round(pos.estimated_share_price, 4),
            "unrealized_pnl": round(pos.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(pos.unrealized_pnl_pct, 2),
            "peak_share_price": round(pos.peak_share_price, 4),
            "peak_pnl_pct": round(pos.peak_pnl_pct, 2),
            "drawdown_from_peak_pct": round(pos.drawdown_from_peak_pct, 2),
            "hold_duration_min": round(pos.hold_duration_seconds / 60, 1),
            "exited": pos.exited,
            "exit_reason": pos.exit_reason.value if pos.exit_reason else None,
            "realized_pnl": round(pos.realized_pnl, 2) if pos.exited else None,
            "total_ticks": len(pos.btc_price_ticks),
        }
