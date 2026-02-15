"""
Guardian Agent Orchestrator — Main Entry Point.

Runs the 1-hour prediction cycle:
  T-5min: Oracle collects market data snapshot
  T-4min: Hawk polls whale positions on Hyperliquid
  T-3min: Quant runs technical analysis on HL candles
  T-3min: Sentinel analyzes funding rates & OI (parallel with Quant)
  T-1min: Strategist aggregates all signals → decision
  T-0:    Dealer executes on Polymarket (if signal is strong)
  T+55min: Monitor checks system health
  T+60min: Auditor evaluates previous cycle outcome

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
import sys
from datetime import datetime, timezone

import structlog

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
from services.dashboard_reporter import DashboardReporter
from config.settings import settings


def setup_logging():
    """Configure structured logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


class Orchestrator:
    """
    Coordinates the multi-agent prediction cycle.

    Each cycle:
      1. Auditor evaluates previous cycle (if any)
      2. Oracle collects fresh market data
      3. Hawk + Quant + Sentinel run in parallel
      4. Strategist makes decision
      5. Dealer executes trade (if applicable)
      6. Monitor checks system health
      7. Dashboard reporter sends updates
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._running = False
        self._cycle_count = 0

        # Shared infrastructure
        self.bus = AgentBus()
        self.hl_client = HyperliquidClient()
        self.reporter = DashboardReporter()

        # Initialize all agents
        self.oracle = OracleAgent(self.bus, self.hl_client)
        self.hawk = HawkAgent(self.bus, self.hl_client)
        self.quant = QuantAgent(self.bus)
        self.sentinel = SentinelAgent(self.bus, self.hl_client)
        self.strategist = StrategistAgent(self.bus)
        self.dealer = DealerAgent(self.bus)
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
        """Start all agents."""
        self.logger.info("Starting Guardian Agent System...")
        self.logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.logger.info(f"Cycle interval: {settings.agent.cycle_minutes} minutes")

        for agent in self.all_agents:
            await agent.start()
            self.logger.info(f"  Started: {agent.name}")

        self._running = True
        self.logger.info("All agents started. System operational.")

    async def stop(self):
        """Stop all agents and clean up."""
        self.logger.info("Shutting down Guardian Agent System...")
        self._running = False

        for agent in reversed(self.all_agents):
            await agent.stop()

        await self.hl_client.close()
        self.logger.info("System shut down cleanly.")

    async def run_cycle(self) -> dict:
        """
        Execute one complete prediction cycle.

        Returns a summary dict of the cycle.
        """
        self._cycle_count += 1
        cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:6]}"

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"CYCLE {self._cycle_count}: {cycle_id}")
        self.logger.info(f"{'='*60}")

        agent_names = [a.name for a in self.all_agents if a.name != "monitor"]
        self.reporter.report_cycle_start(cycle_id, agent_names)

        summary = {"cycle_id": cycle_id, "cycle_number": self._cycle_count}

        # ---- Step 1: Audit previous cycle ----
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

        # ---- Step 2: Oracle collects market data ----
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
            # Mark data source as healthy
            self.monitor.update_data_source(
                "hyperliquid_rest",
                connected=True,
                last_data_received=datetime.now(timezone.utc),
            )

        # ---- Step 3: Hawk + Quant + Sentinel in parallel ----
        self.logger.info("Step 3: Running Hawk, Quant, Sentinel in parallel...")
        hawk_task = asyncio.create_task(self.hawk.execute_cycle(cycle_id))
        quant_task = asyncio.create_task(self.quant.execute_cycle(cycle_id))
        sentinel_task = asyncio.create_task(self.sentinel.execute_cycle(cycle_id))

        whale_signal, tech_signal, sentinel_signal = await asyncio.gather(
            hawk_task, quant_task, sentinel_task,
            return_exceptions=True,
        )

        # Report signals
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

        # ---- Step 4: Strategist decides ----
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

        # ---- Step 5: Dealer executes ----
        if decision and decision.should_trade and not self.dry_run:
            self.logger.info("Step 5: Dealer executing trade...")
            trade = await self.dealer.execute_cycle(cycle_id)
            if trade:
                self.reporter.report_trade(cycle_id, trade)
                summary["trade"] = trade
        elif self.dry_run and decision and decision.should_trade:
            self.logger.info("Step 5: DRY RUN — trade would be placed")
            summary["trade"] = {"action": "dry_run", "would_trade": True}
        else:
            self.logger.info("Step 5: No trade this cycle")
            summary["trade"] = {"action": "skip"}

        # ---- Step 6: Monitor checks health ----
        self.logger.info("Step 6: Monitor checking system health...")
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

        self.logger.info(f"Cycle {cycle_id} complete.")
        self.logger.info(f"{'='*60}\n")

        return summary

    async def run_loop(self):
        """Run the prediction cycle in a continuous loop."""
        await self.start()

        try:
            while self._running:
                try:
                    summary = await self.run_cycle()

                    # Log summary
                    decision = summary.get("decision", {})
                    self.logger.info(
                        f"Cycle summary: {decision.get('direction', 'N/A')} "
                        f"@ {decision.get('confidence', 0):.0%} — "
                        f"Trade: {summary.get('trade', {}).get('action', 'N/A')}"
                    )

                except Exception as e:
                    self.logger.error(f"Cycle failed: {e}", exc_info=True)

                # Wait for next cycle
                wait_seconds = settings.agent.cycle_minutes * 60
                self.logger.info(
                    f"Next cycle in {settings.agent.cycle_minutes} minutes..."
                )
                await asyncio.sleep(wait_seconds)

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
