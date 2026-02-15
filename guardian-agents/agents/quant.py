"""
Quant Agent — Technical Analysis.

Responsibilities:
  - Compute RSI, MACD, Bollinger Bands, EMA/SMA on Hyperliquid candles
  - Analyze volume patterns (VWAP, volume ratio)
  - Compute ATR for volatility context
  - Produce directional signal with confidence

Bus topics consumed:
  - "candles_1h": list of CandleData (from Oracle)
  - "candles_5m": list of CandleData (from Oracle)

Bus topics published:
  - "technical_signal": TechnicalSignal
"""

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import numpy as np

from agents.base import BaseAgent, AgentBus
from models.signals import TechnicalSignal, CandleData, Direction, TimeFrame


class QuantAgent(BaseAgent):
    """Technical analysis on Hyperliquid BTC candle data."""

    def __init__(self, bus: AgentBus):
        super().__init__("quant", bus)

    async def start(self):
        await super().start()
        self.logger.info("Quant ready — technical analysis engine")

    def _candles_to_df(self, candles: list[CandleData]) -> pd.DataFrame:
        """Convert candle list to pandas DataFrame."""
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in candles])
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _compute_rsi(self, series: pd.Series, period: int = 14) -> float:
        """Relative Strength Index."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def _compute_macd(
        self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[float, float]:
        """MACD line and histogram."""
        ema_fast = series.ewm(span=fast).mean()
        ema_slow = series.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        return (
            float(macd_line.iloc[-1] - signal_line.iloc[-1]),
            float(histogram.iloc[-1]),
        )

    def _compute_bollinger(
        self, series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> tuple[float, float, float]:
        """Bollinger Bands — upper, lower, width."""
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = float(sma.iloc[-1] + std_dev * std.iloc[-1])
        lower = float(sma.iloc[-1] - std_dev * std.iloc[-1])
        width = (upper - lower) / float(sma.iloc[-1]) if sma.iloc[-1] else 0
        return upper, lower, width

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return float(atr.iloc[-1]) if not atr.empty else 0.0

    def _compute_vwap(self, df: pd.DataFrame) -> float:
        """Volume Weighted Average Price (using last 20 candles)."""
        recent = df.tail(20)
        typical_price = (recent["high"] + recent["low"] + recent["close"]) / 3
        vwap = (typical_price * recent["volume"]).sum() / recent["volume"].sum()
        return float(vwap) if not np.isnan(vwap) else float(recent["close"].iloc[-1])

    async def run_cycle(self, cycle_id: str) -> TechnicalSignal:
        """
        Run full TA suite on the latest candles from Oracle.
        """
        candles_1h = self.get_signal("candles_1h") or []
        candles_5m = self.get_signal("candles_5m") or []

        # Use 1h candles for primary analysis
        df = self._candles_to_df(candles_1h)

        if df.empty or len(df) < 30:
            self.logger.warning("Insufficient candle data for TA")
            return TechnicalSignal(
                timestamp=datetime.now(timezone.utc),
                timeframe=TimeFrame.H1,
                rsi_14=50, macd_signal=0, macd_histogram=0,
                ema_9=0, ema_21=0, sma_50=0,
                bollinger_upper=0, bollinger_lower=0, bollinger_width=0,
                atr_14=0, vwap=0, volume_sma_ratio=1.0,
                direction=Direction.NEUTRAL,
                confidence=0.0,
                reasoning="Insufficient data",
            )

        close = df["close"]
        current_price = float(close.iloc[-1])

        # Core indicators
        rsi = self._compute_rsi(close)
        macd_signal, macd_hist = self._compute_macd(close)
        bb_upper, bb_lower, bb_width = self._compute_bollinger(close)
        atr = self._compute_atr(df)
        vwap = self._compute_vwap(df)

        # Moving averages
        ema_9 = float(close.ewm(span=9).mean().iloc[-1])
        ema_21 = float(close.ewm(span=21).mean().iloc[-1])
        sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else ema_21

        # Volume analysis
        vol_sma = float(df["volume"].rolling(20).mean().iloc[-1])
        vol_ratio = float(df["volume"].iloc[-1]) / vol_sma if vol_sma > 0 else 1.0

        # ---- Signal scoring ----
        bullish_points = 0
        bearish_points = 0
        total_weight = 0

        # RSI (weight: 2)
        if rsi < 30:
            bullish_points += 2  # oversold = bullish
        elif rsi > 70:
            bearish_points += 2  # overbought = bearish
        elif rsi < 45:
            bullish_points += 1
        elif rsi > 55:
            bearish_points += 1
        total_weight += 2

        # MACD (weight: 2)
        if macd_hist > 0 and macd_signal > 0:
            bullish_points += 2
        elif macd_hist < 0 and macd_signal < 0:
            bearish_points += 2
        elif macd_hist > 0:
            bullish_points += 1
        elif macd_hist < 0:
            bearish_points += 1
        total_weight += 2

        # EMA cross (weight: 2)
        if ema_9 > ema_21:
            bullish_points += 2
        else:
            bearish_points += 2
        total_weight += 2

        # Price vs VWAP (weight: 1)
        if current_price > vwap:
            bullish_points += 1
        else:
            bearish_points += 1
        total_weight += 1

        # Bollinger position (weight: 1)
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        if bb_position < 0.2:
            bullish_points += 1  # near lower band = bounce potential
        elif bb_position > 0.8:
            bearish_points += 1  # near upper band = reversal potential
        total_weight += 1

        # Price vs SMA50 (weight: 1)
        if current_price > sma_50:
            bullish_points += 1
        else:
            bearish_points += 1
        total_weight += 1

        # Determine direction and confidence
        net_score = bullish_points - bearish_points
        max_score = total_weight
        raw_confidence = abs(net_score) / max_score

        if net_score > 0:
            direction = Direction.UP
        elif net_score < 0:
            direction = Direction.DOWN
        else:
            direction = Direction.NEUTRAL

        # Scale confidence — require strong conviction
        confidence = round(min(0.9, 0.4 + raw_confidence * 0.5), 3)

        reasoning_parts = []
        reasoning_parts.append(f"RSI={rsi:.1f}")
        reasoning_parts.append(f"MACD hist={'+'if macd_hist>0 else ''}{macd_hist:.1f}")
        reasoning_parts.append(f"EMA9{'>' if ema_9>ema_21 else '<'}EMA21")
        reasoning_parts.append(f"Price {'>' if current_price>vwap else '<'} VWAP")
        reasoning_parts.append(f"BB pos={bb_position:.2f}")
        reasoning_parts.append(f"Vol ratio={vol_ratio:.1f}x")
        reasoning = f"Score {net_score}/{max_score}: " + ", ".join(reasoning_parts)

        signal = TechnicalSignal(
            timestamp=datetime.now(timezone.utc),
            timeframe=TimeFrame.H1,
            rsi_14=round(rsi, 2),
            macd_signal=round(macd_signal, 2),
            macd_histogram=round(macd_hist, 2),
            ema_9=round(ema_9, 2),
            ema_21=round(ema_21, 2),
            sma_50=round(sma_50, 2),
            bollinger_upper=round(bb_upper, 2),
            bollinger_lower=round(bb_lower, 2),
            bollinger_width=round(bb_width, 5),
            atr_14=round(atr, 2),
            vwap=round(vwap, 2),
            volume_sma_ratio=round(vol_ratio, 2),
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
        )

        await self.publish("technical_signal", signal)
        self.logger.info(
            f"Quant: {direction.value} ({confidence:.0%}) — "
            f"RSI {rsi:.0f} | MACD {macd_hist:+.1f} | "
            f"EMA9{'>' if ema_9>ema_21 else '<'}21"
        )

        return signal
