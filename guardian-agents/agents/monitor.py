"""
Monitor Agent — System Self-Monitoring.

Responsibilities:
  - Track health of all agents (heartbeat, response times, errors)
  - Monitor data source connectivity (Hyperliquid WS/REST, Binance, Polymarket)
  - Detect anomalies (stuck agents, data staleness, unusual patterns)
  - Track system resources (memory, CPU)
  - Generate alerts when thresholds are breached
  - Produce SystemHealthReport for dashboard
  - Auto-recovery: restart failed agents, reconnect data sources

Bus topics published:
  - "system_health": SystemHealthReport
  - "alert": dict with alert details

This agent runs independently and monitors ALL other agents.
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from agents.base import BaseAgent, AgentBus
from models.health import (
    SystemHealthReport, AgentHealth, AgentStatus, DataSourceHealth,
    PerformanceMetrics, CycleMetrics, SystemStatus,
)
from config.settings import settings


class MonitorAgent(BaseAgent):
    """Self-monitoring agent that watches the entire system."""

    def __init__(self, bus: AgentBus):
        super().__init__("monitor", bus)

        # References to all other agents (set by orchestrator)
        self._agents: dict[str, BaseAgent] = {}
        self._data_sources: dict[str, DataSourceHealth] = {}

        # Alert history
        self._alerts: list[dict] = []
        self._active_alerts: list[str] = []

        # Cycle tracking
        self._cycle_metrics: list[CycleMetrics] = []
        self._last_report: Optional[SystemHealthReport] = None

    def register_agent(self, agent: BaseAgent):
        """Register an agent for monitoring."""
        self._agents[agent.name] = agent

    def register_data_source(self, name: str):
        """Register a data source for monitoring."""
        self._data_sources[name] = DataSourceHealth(source=name)

    def update_data_source(self, name: str, **kwargs):
        """Update data source health status."""
        if name in self._data_sources:
            for k, v in kwargs.items():
                if hasattr(self._data_sources[name], k):
                    setattr(self._data_sources[name], k, v)

    async def start(self):
        await super().start()
        self.logger.info(
            f"Monitor ready — watching {len(self._agents)} agents, "
            f"{len(self._data_sources)} data sources"
        )

    def _check_agent_health(self) -> list[AgentHealth]:
        """Check health status of all registered agents."""
        health_list = []
        now = datetime.now(timezone.utc)

        for name, agent in self._agents.items():
            h = agent.health

            # Check for stale heartbeat
            if h.last_heartbeat:
                age = (now - h.last_heartbeat).total_seconds()
                if age > settings.monitor.max_agent_response_time * 3:
                    h.status = AgentStatus.FAILING
                    self._raise_alert(
                        f"Agent '{name}' heartbeat stale ({age:.0f}s)",
                        severity="high",
                    )
                elif age > settings.monitor.max_agent_response_time:
                    h.status = AgentStatus.DEGRADED

            # Check for consecutive failures
            if h.consecutive_failures >= settings.monitor.alert_on_consecutive_failures:
                self._raise_alert(
                    f"Agent '{name}' has {h.consecutive_failures} consecutive failures: {h.last_error}",
                    severity="critical",
                )

            # Check response time degradation
            if h.avg_response_time_ms > settings.monitor.max_agent_response_time * 1000:
                h.status = AgentStatus.DEGRADED
                self._raise_alert(
                    f"Agent '{name}' slow: {h.avg_response_time_ms:.0f}ms avg",
                    severity="medium",
                )

            health_list.append(h)

        return health_list

    def _check_data_sources(self) -> list[DataSourceHealth]:
        """Check connectivity of all data sources."""
        now = datetime.now(timezone.utc)
        sources = []

        for name, ds in self._data_sources.items():
            # Check for stale data
            if ds.last_data_received:
                age = (now - ds.last_data_received).total_seconds()
                if age > 120:  # No data for 2 minutes
                    ds.connected = False
                    self._raise_alert(
                        f"Data source '{name}' stale ({age:.0f}s since last data)",
                        severity="high",
                    )

            if not ds.connected:
                self._raise_alert(
                    f"Data source '{name}' disconnected",
                    severity="critical",
                )

            sources.append(ds)

        return sources

    def _get_performance_metrics(self) -> Optional[PerformanceMetrics]:
        """Build performance metrics from Auditor data."""
        cycle_result = self.get_signal("cycle_result")
        if not cycle_result:
            return None

        return PerformanceMetrics(
            timestamp=datetime.now(timezone.utc),
            window="24h",
            total_predictions=cycle_result.total_predictions,
            correct_predictions=cycle_result.correct_predictions,
            win_rate=cycle_result.win_rate,
            total_pnl_usd=cycle_result.cumulative_pnl,
            current_streak=cycle_result.current_streak,
        )

    def _get_system_resources(self) -> tuple[float, float]:
        """Get memory and CPU usage."""
        try:
            import resource
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except (ImportError, Exception):
            mem_mb = 0.0

        try:
            load = os.getloadavg()[0]
            cpu_count = os.cpu_count() or 1
            cpu_pct = (load / cpu_count) * 100
        except (OSError, Exception):
            cpu_pct = 0.0

        return mem_mb, cpu_pct

    def _raise_alert(self, message: str, severity: str = "medium"):
        """Raise an alert."""
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "severity": severity,
        }
        self._alerts.append(alert)

        # Deduplicate active alerts
        if message not in self._active_alerts:
            self._active_alerts.append(message)
            self.logger.warning(f"ALERT [{severity}]: {message}")

        # Keep only last 100 alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]
        if len(self._active_alerts) > 20:
            self._active_alerts = self._active_alerts[-20:]

    async def run_cycle(self, cycle_id: str) -> SystemHealthReport:
        """
        Generate a full system health report.
        """
        # 1. Check all agents
        agent_health = self._check_agent_health()

        # 2. Check data sources
        source_health = self._check_data_sources()

        # 3. Performance metrics
        performance = self._get_performance_metrics()

        # 4. System resources
        mem_mb, cpu_pct = self._get_system_resources()

        # 5. Check for risk threshold alerts
        if performance:
            if performance.win_rate < 0.40 and performance.total_predictions >= 10:
                self._raise_alert(
                    f"Win rate critically low: {performance.win_rate:.0%} "
                    f"({performance.correct_predictions}/{performance.total_predictions})",
                    severity="critical",
                )

            if performance.total_pnl_usd < -settings.agent.max_daily_loss_usd * 0.8:
                self._raise_alert(
                    f"Approaching daily loss limit: ${performance.total_pnl_usd:.2f}",
                    severity="high",
                )

        # 6. Memory check
        if mem_mb > 1024:
            self._raise_alert(
                f"High memory usage: {mem_mb:.0f}MB",
                severity="medium",
            )

        # Build report
        report = SystemHealthReport(
            timestamp=datetime.now(timezone.utc),
            agents=agent_health,
            data_sources=source_health,
            performance=performance,
            active_alerts=self._active_alerts.copy(),
            memory_usage_mb=mem_mb,
            cpu_usage_pct=cpu_pct,
        )
        report.status = report.compute_status()

        # Publish to bus
        await self.publish("system_health", report)

        # Clear alerts that have resolved
        self._active_alerts = [
            a for a in self._active_alerts
            if any(
                agent.status in (AgentStatus.FAILING, AgentStatus.OFFLINE)
                for agent in agent_health
            )
            or any(not ds.connected for ds in source_health)
        ]

        self._last_report = report

        # Log summary
        failing = [a.agent_name for a in agent_health if a.status == AgentStatus.FAILING]
        disconnected = [s.source for s in source_health if not s.connected]

        self.logger.info(
            f"Monitor: {report.status.value} — "
            f"{len(agent_health)} agents ({len(failing)} failing), "
            f"{len(source_health)} sources ({len(disconnected)} disconnected), "
            f"{len(self._active_alerts)} alerts, "
            f"Mem: {mem_mb:.0f}MB, CPU: {cpu_pct:.1f}%"
        )

        return report
