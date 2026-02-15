"""
Guardian Agent System Configuration.

All settings loaded from environment variables with sensible defaults.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class HyperliquidConfig(BaseSettings):
    """Hyperliquid API configuration (data source only - no trading)."""

    base_url: str = "https://api.hyperliquid.xyz"
    ws_url: str = "wss://api.hyperliquid.xyz/ws"
    # No API key needed for Info API (read-only, public)

    # Polling intervals (seconds)
    whale_poll_interval: int = 30
    funding_poll_interval: int = 60
    oi_poll_interval: int = 60
    orderbook_snapshot_interval: int = 10

    class Config:
        env_prefix = "HL_"


class PolymarketConfig(BaseSettings):
    """Polymarket CLOB configuration (execution venue)."""

    host: str = "https://clob.polymarket.com"
    chain_id: int = 137  # Polygon
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""

    # Position sizing
    max_position_usd: float = 100.0
    min_confidence_to_trade: float = 0.60  # 60% confidence minimum

    class Config:
        env_prefix = "POLY_"


class AgentConfig(BaseSettings):
    """Multi-agent system configuration."""

    # LLM for agent reasoning
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-5-20250929"

    # Prediction cycle
    cycle_minutes: int = 60  # 1-hour prediction windows
    pre_trade_lead_minutes: int = 5  # Start analysis 5 min before cycle

    # Signal weights for Strategist ensemble
    weight_quant: float = 0.25
    weight_hawk: float = 0.30  # Whale data gets highest weight
    weight_sentinel: float = 0.25
    weight_sage: float = 0.20

    # Confidence thresholds
    min_confidence_trade: float = 0.60  # Minimum to enter any trade
    high_confidence_threshold: float = 0.75  # Scale up position size

    # Risk management
    max_daily_loss_usd: float = 200.0
    max_consecutive_losses: int = 5
    kelly_fraction: float = 0.25  # Quarter-Kelly for conservative sizing

    class Config:
        env_prefix = "AGENT_"


class Mem0Config(BaseSettings):
    """Memory layer configuration."""

    api_key: str = ""
    user_id: str = "guardian-system"
    agent_ids: list[str] = [
        "oracle", "hawk", "quant", "sentinel",
        "sage", "strategist", "dealer", "auditor", "monitor",
    ]

    class Config:
        env_prefix = "MEM0_"


class DashboardConfig(BaseSettings):
    """Mission Control dashboard webhook configuration."""

    webhook_url: str = ""  # Convex HTTP endpoint
    api_token: str = ""
    tenant_id: str = "default"

    class Config:
        env_prefix = "DASHBOARD_"


class MonitorConfig(BaseSettings):
    """System monitoring configuration."""

    health_check_interval: int = 30  # seconds
    max_agent_response_time: float = 10.0  # seconds
    max_cycle_duration: float = 300.0  # 5 minutes max per cycle
    alert_on_consecutive_failures: int = 3
    metrics_retention_hours: int = 168  # 7 days

    class Config:
        env_prefix = "MONITOR_"


class Settings(BaseSettings):
    """Root configuration aggregating all sub-configs."""

    hyperliquid: HyperliquidConfig = Field(default_factory=HyperliquidConfig)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    mem0: Mem0Config = Field(default_factory=Mem0Config)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)

    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
