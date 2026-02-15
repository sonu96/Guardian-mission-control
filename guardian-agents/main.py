"""
Guardian Agent Orchestrator — Main Entry Point.

Full 1-hour cycle with active position management:

  PHASE 1 — ANALYZE (minutes 0-5):
    Step 1: Auditor evaluates previous cycle outcome
    Step 2: Oracle collects BTC data from Hyperliquid + Binance
    Step 3: Hawk + Quant + Sentinel analyze in parallel
    Step 4: Strategist aggregates signals → decision
    Step 5: Dealer places trade on Polymarket (if signal strong)

  PHASE 2 — MONITOR (minutes 5-55):
    Dealer actively watches the position:
      - Polls BTC price from Hyperliquid every 30s
      - Estimates Polymarket share price movement
      - Checks: take profit, trailing stop, stop loss
      - At minute 30: re-runs Hawk+Sentinel for signal flip check
      - Exits early if any condition triggers
    Monitor checks system health every 60s in parallel

  PHASE 3 — RESOLVE (minutes 55-60):
    If still in position: hold to market resolution
    Auditor will score the result at start of next cycle

Usage:
  python main.py                 # Run the full orchestration loop
  python main.py --once          # Run a single cycle (for testing)
  python main.py --dry-run       # Run without placing real trades
"""

import asyncio
import argparse
import logging
import signal
import uuid
from datetime import datetime, timezone

from agents.base import AgentBus
from agents.oracle import OracleAgent
from agents.hawk import HawkAgent
from agents.quant import QuantAgent
from agents.sentinel import SentinelAgent
from agents.strategist import StrategistAgent
from agents.dealer import DealerAgent
from agents.auditor import AuditorAgent
from agents.monitor import MonitorAgent
from services.hyperliquid_client import HyperliquidClient
from services.polymarket_client import PolymarketClient
from services.dashboard_reporter import DashboardReporter
from config.settings import settings


def setup_logging():
    """Configure structured logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


class Orchestrator:
    """
    Coordinates the multi-agent prediction cycle with active position management.

    The key change from v1: after placing a trade, the system does NOT sleep
    for 60 minutes. Instead, the Dealer actively monitors the position using
    Hyperliquid BTC price data and can exit early for profit or loss protection.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._running = False
        self._cycle_count = 0

        # Shared infrastructure
        self.bus = AgentBus()
        self.hl_client = HyperliquidClient()
        self.poly_client = PolymarketClient()
        self.reporter = DashboardReporter()

        # Initialize all agents
        self.oracle = OracleAgent(self.bus, self.hl_client)
        self.hawk = HawkAgent(self.bus, self.hl_client)
        self.quant = QuantAgent(self.bus)
        self.sentinel = SentinelAgent(self.bus, self.hl_client)
        self.strategist = StrategistAgent(self.bus)
        self.dealer = DealerAgent(self.bus, self.hl_client, self.poly_client)
        self.auditor = AuditorAgent(self.bus, self.hl_client)
        self.monitor = MonitorAgent(self.bus)

        # Wire up cross-references
        self.auditor.set_strategist(self.strategist)

        # Register agents with monitor
        self.all_agents = [
            self.oracle, self.hawk, self.quant, self.sentinel,
            self.strategist, self.dealer, self.auditor, self.monitor,
        ]
        for agent in self.all_agents:
            if agent.name != "monitor":
                self.monitor.register_agent(agent)

        # Register data sources
        self.monitor.register_data_source("hyperliquid_rest")
        self.monitor.register_data_source("hyperliquid_ws")
        self.monitor.register_data_source("binance_rest")

        self.logger = logging.getLogger("orchestrator")

    async def start(self):
        """Start all agents and initialize Polymarket connection."""
        self.logger.info("Starting Guardian Agent System...")
        self.logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.logger.info(f"Cycle interval: {settings.agent.cycle_minutes} minutes")
        self.logger.info(f"Exit strategy: TP={settings.agent.exit_take_profit_pct}% / "
                        f"Trail={settings.agent.exit_trailing_stop_pct}% / "
                        f"SL={settings.agent.exit_stop_loss_pct}%")

        # Initialize Polymarket client (CLOB + on-chain approvals)
        try:
            self.poly_client.initialize()
            if self.poly_client.is_ready and not self.poly_client.is_read_only:
                self.poly_client.ensure_approvals()
                balance = self.poly_client.get_usdc_balance()
                self.logger.info(f"Polymarket wallet ready — USDC balance: ${balance:.2f}")
            elif self.poly_client.is_read_only:
                self.logger.warning("No POLY_PRIVATE_KEY — running in simulation mode")
        except Exception as e:
            self.logger.error(f"Polymarket init failed: {e} — falling back to simulation")

        for agent in self.all_agents:
            await agent.start()
            self.logger.info(f"  Started: {agent.name}")

        self._running = True
        self.logger.info("All agents started. System operational.")

    async def stop(self):
        """Stop all agents and clean up."""
        self.logger.info("Shutting down Guardian Agent System...")
        self._running = False

        # Stop position monitoring if active
        self.dealer.position_manager.stop_monitoring()

        for agent in reversed(self.all_agents):
            await agent.stop()

        await self.hl_client.close()
        self.logger.info("System shut down cleanly.")

    async def _mid_window_signal_check(self, position) -> bool:
        """
        Re-run Hawk + Sentinel at the mid-window mark to detect signal flips.

        Returns True if the original signal has reversed (should exit).
        """
        self.logger.info("=== MID-WINDOW SIGNAL CHECK ===")
        mid_cycle_id = f"mid_{position.cycle_id}"

        try:
            # Re-fetch fresh data
            await self.oracle.execute_cycle(mid_cycle_id)

            # Re-run Hawk and Sentinel in parallel
            hawk_result, sentinel_result = await asyncio.gather(
                self.hawk.execute_cycle(mid_cycle_id),
                self.sentinel.execute_cycle(mid_cycle_id),
                return_exceptions=True,
            )

            original_direction = position.direction  # "UP" or "DOWN"
            flip_signals = 0
            total_signals = 0

            # Check if Hawk signal flipped
            if hawk_result and not isinstance(hawk_result, Exception):
                total_signals += 1
                if hawk_result.direction.value != original_direction and hawk_result.direction.value != "NEUTRAL":
                    flip_signals += 1
                    self.logger.warning(
                        f"Hawk FLIPPED: was {original_direction}, now {hawk_result.direction.value} "
                        f"@ {hawk_result.confidence:.0%}"
                    )

                self.reporter.report_agent_signal(
                    "Hawk", mid_cycle_id,
                    f"Mid-check: {hawk_result.direction.value} @ {hawk_result.confidence:.0%}"
                )

            # Check if Sentinel signal flipped
            if sentinel_result and not isinstance(sentinel_result, Exception):
                total_signals += 1
                if sentinel_result.direction.value != original_direction and sentinel_result.direction.value != "NEUTRAL":
                    flip_signals += 1
                    self.logger.warning(
                        f"Sentinel FLIPPED: was {original_direction}, now {sentinel_result.direction.value} "
                        f"@ {sentinel_result.confidence:.0%}"
                    )

                self.reporter.report_agent_signal(
                    "Sentinel", mid_cycle_id,
                    f"Mid-check: {sentinel_result.direction.value} @ {sentinel_result.confidence:.0%}"
                )

            # Exit if BOTH signals flipped (high confidence reversal)
            if total_signals >= 2 and flip_signals >= 2:
                self.logger.warning(
                    f"SIGNAL FLIP CONFIRMED: {flip_signals}/{total_signals} signals reversed"
                )
                return True

            # Also exit if one flipped with high confidence AND we're in loss
            if flip_signals >= 1 and position.unrealized_pnl_pct < -5:
                self.logger.warning(
                    "Signal partially flipped + position in loss — exiting"
                )
                return True

            self.logger.info(
                f"Mid-window check: {flip_signals}/{total_signals} flipped — "
                f"{'HOLD' if flip_signals < 2 else 'EXIT'}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Mid-window signal check failed: {e}")
            return False  # Don't exit on check failure

    async def _monitor_health_during_window(self, cycle_id: str):
        """Run Monitor agent periodically during the trade window."""
        interval = settings.monitor.health_check_interval
        while self._running and self.dealer.position_manager.has_position:
            try:
                await self.monitor.execute_cycle(cycle_id)
            except Exception as e:
                self.logger.error(f"Health check failed: {e}")
            await asyncio.sleep(interval)

    async def run_cycle(self) -> dict:
        """
        Execute one complete prediction cycle with active position management.
        """
        self._cycle_count += 1
        cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:6]}"

        self.logger.info(f"\n{'='*70}")
        self.logger.info(f"CYCLE {self._cycle_count}: {cycle_id}")
        self.logger.info(f"{'='*70}")

        agent_names = [a.name for a in self.all_agents if a.name != "monitor"]
        self.reporter.report_cycle_start(cycle_id, agent_names)

        summary = {"cycle_id": cycle_id, "cycle_number": self._cycle_count}

        # ============================================================
        # PHASE 1: ANALYZE — Collect signals and make prediction
        # ============================================================
        self.logger.info("--- PHASE 1: ANALYZE ---")

        # Step 1: Audit previous cycle
        self.logger.info("Step 1: Auditing previous cycle...")
        audit_result = await self.auditor.execute_cycle(cycle_id)
        if audit_result:
            summary["previous_result"] = {
                "prediction_correct": audit_result.prediction_correct,
                "btc_change_pct": audit_result.btc_change_pct,
                "pnl": audit_result.polymarket_pnl_usd,
                "cumulative_pnl": audit_result.cumulative_pnl,
                "win_rate": audit_result.win_rate,
            }
            self.reporter.report_cycle_result(cycle_id, summary["previous_result"])

        # Step 2: Oracle collects market data
        self.logger.info("Step 2: Oracle collecting market data...")
        oracle_data = await self.oracle.execute_cycle(cycle_id)
        if oracle_data:
            price = oracle_data.get("price")
            if price:
                self.reporter.report_agent_signal(
                    "Oracle", cycle_id,
                    f"BTC ${price.hl_mid_price:,.0f} | "
                    f"HL-Binance spread: {price.spread_hl_binance}bps"
                )
            self.monitor.update_data_source(
                "hyperliquid_rest",
                connected=True,
                last_data_received=datetime.now(timezone.utc),
            )

        # Step 3: Hawk + Quant + Sentinel in parallel
        self.logger.info("Step 3: Running Hawk, Quant, Sentinel in parallel...")
        whale_signal, tech_signal, sentinel_signal = await asyncio.gather(
            self.hawk.execute_cycle(cycle_id),
            self.quant.execute_cycle(cycle_id),
            self.sentinel.execute_cycle(cycle_id),
            return_exceptions=True,
        )

        if whale_signal and not isinstance(whale_signal, Exception):
            self.reporter.report_agent_signal(
                "Hawk", cycle_id,
                f"{whale_signal.direction.value} @ {whale_signal.confidence:.0%} — "
                f"{whale_signal.whales_long}L/{whale_signal.whales_short}S"
            )
        if tech_signal and not isinstance(tech_signal, Exception):
            self.reporter.report_agent_signal(
                "Quant", cycle_id,
                f"{tech_signal.direction.value} @ {tech_signal.confidence:.0%} — "
                f"RSI {tech_signal.rsi_14:.0f}"
            )
        if sentinel_signal and not isinstance(sentinel_signal, Exception):
            self.reporter.report_agent_signal(
                "Sentinel", cycle_id,
                f"{sentinel_signal.direction.value} @ {sentinel_signal.confidence:.0%} — "
                f"Funding {sentinel_signal.funding.hl_funding_rate:.6f}"
            )

        # Step 4: Strategist decides
        self.logger.info("Step 4: Strategist aggregating signals...")
        decision = await self.strategist.execute_cycle(cycle_id)
        if decision:
            self.reporter.report_decision(
                cycle_id,
                direction=decision.direction.value,
                confidence=decision.confidence,
                should_trade=decision.should_trade,
                position_size=decision.position_size_usd,
                reasoning=decision.reasoning,
            )
            summary["decision"] = {
                "direction": decision.direction.value,
                "confidence": decision.confidence,
                "should_trade": decision.should_trade,
                "position_size": decision.position_size_usd,
            }

        # Step 5: Dealer places trade
        trade_placed = False
        if decision and decision.should_trade and not self.dry_run:
            self.logger.info("Step 5: Dealer entering position...")
            trade = await self.dealer.execute_cycle(cycle_id)
            if trade and trade.get("action") in ("trade", "simulated_trade"):
                self.reporter.report_trade(cycle_id, trade)
                summary["trade"] = trade
                trade_placed = True
        elif self.dry_run and decision and decision.should_trade:
            self.logger.info("Step 5: DRY RUN — simulating trade entry...")
            trade = await self.dealer.execute_cycle(cycle_id)
            if trade:
                summary["trade"] = trade
                trade_placed = True
        else:
            self.logger.info("Step 5: No trade this cycle")
            summary["trade"] = {"action": "skip"}

        # ============================================================
        # PHASE 2: MONITOR — Actively manage position during window
        # ============================================================
        if trade_placed and self.dealer.position_manager.has_position:
            self.logger.info("\n--- PHASE 2: MONITOR (active position management) ---")
            self.logger.info(
                f"Monitoring for up to {settings.agent.cycle_minutes} minutes | "
                f"Polling BTC every {settings.agent.exit_poll_interval}s | "
                f"Mid-window signal check at {settings.agent.exit_mid_check_minute}min"
            )

            # Run position monitoring and health checks in parallel
            monitor_task = asyncio.create_task(
                self._monitor_health_during_window(cycle_id)
            )

            position_result = await self.dealer.monitor_position(
                signal_check_fn=self._mid_window_signal_check,
            )

            # Cancel health monitoring (position is closed)
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            if position_result:
                summary["position_result"] = position_result
                exit_reason = position_result.get("exit_reason", "unknown")
                realized_pnl = position_result.get("realized_pnl", 0)
                hold_min = position_result.get("hold_duration_min", 0)

                self.logger.info(
                    f"\n--- PHASE 2 COMPLETE ---\n"
                    f"Exit: {exit_reason} | "
                    f"PnL: ${realized_pnl:+.2f} | "
                    f"Held: {hold_min:.1f}min | "
                    f"BTC move: {position_result.get('btc_change_pct', 0):+.2f}%"
                )

                self.reporter.report_agent_signal(
                    "Dealer", cycle_id,
                    f"Position closed: {exit_reason} | "
                    f"PnL: ${realized_pnl:+.2f} | "
                    f"Held: {hold_min:.1f}min"
                )
        else:
            # No position — just run health check and wait
            self.logger.info("\n--- PHASE 2: WAIT (no active position) ---")
            await self.monitor.execute_cycle(cycle_id)

            # Still need to wait for the window to complete
            # so the next cycle aligns with the hourly boundary
            wait_seconds = settings.agent.cycle_minutes * 60
            self.logger.info(f"Waiting {settings.agent.cycle_minutes}min for next cycle...")
            await asyncio.sleep(wait_seconds)

        # ============================================================
        # PHASE 3: RESOLVE — Final health check
        # ============================================================
        self.logger.info("\n--- PHASE 3: RESOLVE ---")
        health = await self.monitor.execute_cycle(cycle_id)
        if health:
            perf = None
            if health.performance:
                perf = {
                    "win_rate": health.performance.win_rate,
                    "total_pnl_usd": health.performance.total_pnl_usd,
                }
            self.reporter.report_system_status(
                status=health.status.value,
                agent_count=len(health.agents),
                active_alerts=len(health.active_alerts),
                performance=perf,
            )
            summary["health"] = {
                "status": health.status.value,
                "alerts": health.active_alerts,
            }

        self.logger.info(f"\nCycle {cycle_id} complete.")
        self.logger.info(f"{'='*70}\n")

        return summary

    async def run_loop(self):
        """Run the prediction cycle in a continuous loop."""
        await self.start()

        try:
            while self._running:
                try:
                    summary = await self.run_cycle()

                    decision = summary.get("decision", {})
                    pos_result = summary.get("position_result", {})
                    self.logger.info(
                        f"Cycle summary: {decision.get('direction', 'N/A')} "
                        f"@ {decision.get('confidence', 0):.0%} | "
                        f"Exit: {pos_result.get('exit_reason', 'N/A')} | "
                        f"PnL: ${pos_result.get('realized_pnl', 0):+.2f}"
                    )

                except Exception as e:
                    self.logger.error(f"Cycle failed: {e}", exc_info=True)
                    # Wait before retrying to avoid tight error loops
                    await asyncio.sleep(60)

                # No additional sleep needed — the monitoring phase
                # already consumed the full window duration

        except asyncio.CancelledError:
            self.logger.info("Run loop cancelled")
        finally:
            await self.stop()


async def main():
    parser = argparse.ArgumentParser(description="Guardian Agent System")
    parser.add_argument("--once", action="store_true", help="Run a single cycle")
    parser.add_argument("--dry-run", action="store_true", help="No real trades")
    args = parser.parse_args()

    setup_logging()

    orchestrator = Orchestrator(dry_run=args.dry_run)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        orchestrator._running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    if args.once:
        await orchestrator.start()
        try:
            summary = await orchestrator.run_cycle()
            print(f"\nCycle complete: {summary}")
        finally:
            await orchestrator.stop()
    else:
        await orchestrator.run_loop()


if __name__ == "__main__":
    asyncio.run(main())
