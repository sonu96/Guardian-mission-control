"""
Signal data models passed between agents.

Each agent produces a typed signal that the Strategist consumes.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class TimeFrame(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# ---- Oracle signals (raw market data) ----

class PriceSnapshot(BaseModel):
    """Current BTC price data from multiple sources."""
    timestamp: datetime
    hl_mark_price: float
    hl_oracle_price: float
    hl_mid_price: float
    binance_price: Optional[float] = None
    spread_hl_binance: Optional[float] = None  # basis points


class OrderBookSnapshot(BaseModel):
    """Hyperliquid BTC order book summary."""
    timestamp: datetime
    best_bid: float
    best_ask: float
    spread_bps: float
    bid_depth_1pct: float  # total bid size within 1% of mid
    ask_depth_1pct: float  # total ask size within 1% of mid
    bid_ask_imbalance: float  # (bid_depth - ask_depth) / (bid_depth + ask_depth)


class CandleData(BaseModel):
    """OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: TimeFrame


# ---- Hawk signals (whale tracking) ----

class WhalePosition(BaseModel):
    """Single whale's BTC position on Hyperliquid."""
    address: str
    label: Optional[str] = None
    coin: str = "BTC"
    size: float  # signed: positive=long, negative=short
    entry_price: float
    liquidation_price: Optional[float] = None
    leverage: float
    leverage_type: str  # "cross" or "isolated"
    unrealized_pnl: float
    margin_used: float
    position_value_usd: float


class WhaleSignal(BaseModel):
    """Aggregated whale sentiment from Hawk agent."""
    timestamp: datetime
    total_whales_tracked: int
    whales_long: int
    whales_short: int
    whales_neutral: int  # no BTC position
    net_whale_exposure: float  # sum of all whale BTC positions (signed)
    largest_long: Optional[WhalePosition] = None
    largest_short: Optional[WhalePosition] = None
    position_changes: list[dict] = Field(default_factory=list)  # recent changes
    direction: Direction = Direction.NEUTRAL
    confidence: float = 0.0  # 0-1
    reasoning: str = ""


# ---- Quant signals (technical analysis) ----

class TechnicalSignal(BaseModel):
    """Technical analysis output from Quant agent."""
    timestamp: datetime
    timeframe: TimeFrame

    # Trend
    rsi_14: float
    macd_signal: float  # MACD - Signal line
    macd_histogram: float
    ema_9: float
    ema_21: float
    sma_50: float

    # Volatility
    bollinger_upper: float
    bollinger_lower: float
    bollinger_width: float
    atr_14: float

    # Volume
    vwap: float
    volume_sma_ratio: float  # current vol / 20-period SMA

    # Derived
    direction: Direction = Direction.NEUTRAL
    confidence: float = 0.0
    reasoning: str = ""


# ---- Sentinel signals (funding & OI) ----

class FundingData(BaseModel):
    """Funding rate data across venues."""
    timestamp: datetime
    hl_funding_rate: float  # current hourly rate
    hl_predicted_funding: float
    binance_funding_rate: Optional[float] = None
    hl_binance_spread: Optional[float] = None  # funding rate arbitrage


class OpenInterestData(BaseModel):
    """Open interest snapshot."""
    timestamp: datetime
    hl_open_interest: float  # in BTC
    hl_oi_usd: float  # in USD
    oi_change_1h_pct: float
    oi_change_24h_pct: float


class SentinelSignal(BaseModel):
    """Funding & OI analysis from Sentinel agent."""
    timestamp: datetime
    funding: FundingData
    open_interest: OpenInterestData

    # Analysis
    funding_extreme: bool = False  # funding > 2 std deviations
    oi_divergence: bool = False  # OI moving opposite to price
    liquidation_cluster_above: Optional[float] = None  # price level
    liquidation_cluster_below: Optional[float] = None  # price level

    direction: Direction = Direction.NEUTRAL
    confidence: float = 0.0
    reasoning: str = ""


# ---- Sage signals (historical pattern matching) ----

class SageSignal(BaseModel):
    """Historical pattern match from Sage agent."""
    timestamp: datetime
    matching_patterns: list[dict] = Field(default_factory=list)
    historical_win_rate: Optional[float] = None  # win rate in similar conditions
    sample_size: int = 0
    direction: Direction = Direction.NEUTRAL
    confidence: float = 0.0
    reasoning: str = ""


# ---- Strategist output (final decision) ----

class PredictionDecision(BaseModel):
    """Final prediction decision from Strategist."""
    timestamp: datetime
    cycle_id: str  # unique identifier for this prediction cycle
    prediction_window_start: datetime
    prediction_window_end: datetime

    # Decision
    direction: Direction
    confidence: float  # 0-1 weighted ensemble confidence
    position_size_usd: float  # Kelly-sized position

    # Component signals
    quant_signal: Optional[TechnicalSignal] = None
    whale_signal: Optional[WhaleSignal] = None
    sentinel_signal: Optional[SentinelSignal] = None
    sage_signal: Optional[SageSignal] = None

    # Weights applied
    weights_used: dict = Field(default_factory=dict)

    # Trade or skip?
    should_trade: bool = False
    skip_reason: Optional[str] = None

    reasoning: str = ""


# ---- Auditor output (cycle result) ----

class CycleResult(BaseModel):
    """Outcome of a completed prediction cycle."""
    cycle_id: str
    prediction: PredictionDecision
    btc_open_price: float
    btc_close_price: float
    btc_change_pct: float
    actual_direction: Direction
    prediction_correct: bool

    # PnL
    polymarket_pnl_usd: float = 0.0
    total_pnl_usd: float = 0.0

    # Running stats
    cumulative_pnl: float = 0.0
    win_rate: float = 0.0
    total_predictions: int = 0
    correct_predictions: int = 0
    current_streak: int = 0  # positive = wins, negative = losses
