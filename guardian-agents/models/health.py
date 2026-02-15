"""
Health and monitoring data models for system self-monitoring.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    OFFLINE = "offline"


class SystemStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    HALTED = "halted"


class AgentHealth(BaseModel):
    """Health status of a single agent."""
    agent_name: str
    status: AgentStatus = AgentStatus.HEALTHY
    last_heartbeat: Optional[datetime] = None
    last_signal_time: Optional[datetime] = None
    avg_response_time_ms: float = 0.0
    error_count_1h: int = 0
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    uptime_pct_24h: float = 100.0


class DataSourceHealth(BaseModel):
    """Health of external data connections."""
    source: str  # "hyperliquid_rest", "hyperliquid_ws", "binance_ws", "polymarket"
    connected: bool = False
    last_data_received: Optional[datetime] = None
    latency_ms: float = 0.0
    error_rate_1h: float = 0.0
    reconnect_count_1h: int = 0


class CycleMetrics(BaseModel):
    """Metrics for a single prediction cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    agents_responded: list[str] = Field(default_factory=list)
    agents_failed: list[str] = Field(default_factory=list)
    trade_executed: bool = False
    anomalies_detected: list[str] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    """Rolling performance metrics."""
    timestamp: datetime
    window: str = "24h"

    # Prediction accuracy
    total_predictions: int = 0
    correct_predictions: int = 0
    win_rate: float = 0.0

    # PnL
    total_pnl_usd: float = 0.0
    avg_pnl_per_trade: float = 0.0
    max_drawdown_usd: float = 0.0
    sharpe_ratio: Optional[float] = None

    # Risk
    current_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    daily_loss_limit_remaining: float = 0.0

    # Per-signal accuracy
    quant_accuracy: float = 0.0
    hawk_accuracy: float = 0.0
    sentinel_accuracy: float = 0.0
    sage_accuracy: float = 0.0


class SystemHealthReport(BaseModel):
    """Complete system health snapshot."""
    timestamp: datetime
    status: SystemStatus = SystemStatus.OPERATIONAL

    # Agent health
    agents: list[AgentHealth] = Field(default_factory=list)

    # Data sources
    data_sources: list[DataSourceHealth] = Field(default_factory=list)

    # Performance
    performance: Optional[PerformanceMetrics] = None

    # Recent cycle
    last_cycle: Optional[CycleMetrics] = None

    # Alerts
    active_alerts: list[str] = Field(default_factory=list)

    # System resources
    memory_usage_mb: float = 0.0
    cpu_usage_pct: float = 0.0

    def compute_status(self) -> SystemStatus:
        """Derive system status from component health."""
        failing_agents = [a for a in self.agents if a.status == AgentStatus.FAILING]
        offline_agents = [a for a in self.agents if a.status == AgentStatus.OFFLINE]
        disconnected_sources = [s for s in self.data_sources if not s.connected]

        if offline_agents or len(disconnected_sources) > 1:
            return SystemStatus.HALTED
        if failing_agents or disconnected_sources:
            return SystemStatus.CRITICAL
        if any(a.status == AgentStatus.DEGRADED for a in self.agents):
            return SystemStatus.DEGRADED
        return SystemStatus.OPERATIONAL
