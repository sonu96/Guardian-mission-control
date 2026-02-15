"""
Dashboard Reporter — Reports agent activity to Mission Control.

Sends events to the Convex HTTP webhook so the dashboard can display:
  - Agent status changes
  - Prediction decisions
  - Trade executions
  - Cycle results
  - System health alerts

Uses the same OpenClaw webhook format that the dashboard already supports.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class DashboardReporter:
    """Reports agent events to the Guardian Mission Control dashboard."""

    def __init__(self):
        self.webhook_url = settings.dashboard.webhook_url
        self.api_token = settings.dashboard.api_token
        self.tenant_id = settings.dashboard.tenant_id
        self._enabled = bool(self.webhook_url)

        if not self._enabled:
            logger.info("Dashboard reporting disabled (no webhook URL configured)")

    def _send_event(self, payload: dict) -> bool:
        """Send an event to the dashboard webhook."""
        if not self._enabled:
            return False

        try:
            payload["tenantId"] = self.tenant_id
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                timeout=5,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Dashboard report failed: {e}")
            return False

    def report_cycle_start(self, cycle_id: str, agents: list[str]):
        """Report that a new prediction cycle has started."""
        self._send_event({
            "runId": cycle_id,
            "action": "start",
            "agentId": "Strategist",
            "source": "guardian-agents",
            "prompt": f"Prediction cycle {cycle_id}",
            "message": f"Starting prediction cycle with agents: {', '.join(agents)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_agent_signal(self, agent_name: str, cycle_id: str, signal_summary: str):
        """Report an individual agent's signal."""
        self._send_event({
            "runId": cycle_id,
            "action": "progress",
            "agentId": agent_name.capitalize(),
            "source": "guardian-agents",
            "message": signal_summary,
            "eventType": "signal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_decision(self, cycle_id: str, direction: str, confidence: float,
                        should_trade: bool, position_size: float, reasoning: str):
        """Report the Strategist's prediction decision."""
        self._send_event({
            "runId": cycle_id,
            "action": "progress",
            "agentId": "Strategist",
            "source": "guardian-agents",
            "message": (
                f"Decision: {direction} @ {confidence:.0%} — "
                f"{'TRADE $' + f'{position_size:.0f}' if should_trade else 'SKIP'}"
            ),
            "eventType": "decision",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_trade(self, cycle_id: str, trade: dict):
        """Report a trade execution."""
        self._send_event({
            "runId": cycle_id,
            "action": "progress",
            "agentId": "Dealer",
            "source": "guardian-agents",
            "message": (
                f"Trade: {trade.get('direction', 'N/A')} — "
                f"{trade.get('shares', 0):.2f} {trade.get('outcome', 'N/A')} shares "
                f"@ ${trade.get('price', 0):.4f} (${trade.get('cost_usd', 0):.2f})"
            ),
            "eventType": "trade",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_cycle_result(self, cycle_id: str, result: dict):
        """Report cycle outcome after resolution."""
        correct = result.get("prediction_correct", False)
        self._send_event({
            "runId": cycle_id,
            "action": "end",
            "agentId": "Auditor",
            "source": "guardian-agents",
            "response": (
                f"{'CORRECT' if correct else 'WRONG'} — "
                f"BTC {result.get('btc_change_pct', 0):+.2f}% | "
                f"PnL: ${result.get('polymarket_pnl_usd', 0):+.2f} | "
                f"Cumulative: ${result.get('cumulative_pnl', 0):+.2f} | "
                f"Win rate: {result.get('win_rate', 0):.0%}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_health_alert(self, alert_message: str, severity: str):
        """Report a system health alert."""
        self._send_event({
            "runId": f"monitor-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            "action": "error",
            "agentId": "Monitor",
            "source": "guardian-agents",
            "error": f"[{severity.upper()}] {alert_message}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def report_system_status(self, status: str, agent_count: int,
                             active_alerts: int, performance: Optional[dict] = None):
        """Report overall system health status."""
        perf_str = ""
        if performance:
            perf_str = (
                f" | Win rate: {performance.get('win_rate', 0):.0%} | "
                f"PnL: ${performance.get('total_pnl_usd', 0):+.2f}"
            )

        self._send_event({
            "runId": f"monitor-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            "action": "progress",
            "agentId": "Monitor",
            "source": "guardian-agents",
            "message": (
                f"System: {status} | {agent_count} agents | "
                f"{active_alerts} alerts{perf_str}"
            ),
            "eventType": "health",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
