"""
Base agent class and inter-agent communication bus.

All agents inherit from BaseAgent and communicate through AgentBus.
The bus is a simple in-process pub/sub — agents publish signals,
other agents subscribe to topics they need.
"""

import asyncio
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional, Callable

from models.health import AgentHealth, AgentStatus

logger = logging.getLogger(__name__)


class AgentBus:
    """
    In-process message bus for inter-agent communication.

    Agents publish signals to named topics. Other agents subscribe
    to topics they need. The bus keeps the latest value for each topic
    so late subscribers can read current state.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._latest: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, data: Any, source: str = ""):
        """Publish data to a topic. Notifies all subscribers."""
        async with self._lock:
            self._latest[topic] = {
                "data": data,
                "source": source,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        callbacks = self._subscribers.get(topic, [])
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"Bus callback error on {topic}: {e}")

    def subscribe(self, topic: str, callback: Callable):
        """Subscribe to a topic with a callback."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def get_latest(self, topic: str) -> Optional[Any]:
        """Get the latest value published to a topic."""
        entry = self._latest.get(topic)
        return entry["data"] if entry else None

    def get_all_latest(self) -> dict[str, Any]:
        """Get latest values for all topics."""
        return {k: v["data"] for k, v in self._latest.items()}


class BaseAgent(ABC):
    """
    Base class for all Guardian agents.

    Provides:
      - Lifecycle management (start, stop, run_cycle)
      - Health tracking (heartbeat, errors, response time)
      - Bus integration (publish/subscribe)
      - Structured logging
    """

    def __init__(self, name: str, bus: AgentBus):
        self.name = name
        self.bus = bus
        self.logger = logging.getLogger(f"agent.{name}")

        # Health tracking
        self._health = AgentHealth(agent_name=name)
        self._started = False
        self._cycle_count = 0
        self._total_response_time = 0.0
        self._error_count = 0

    @property
    def health(self) -> AgentHealth:
        return self._health

    async def start(self):
        """Initialize the agent. Override to add setup logic."""
        self._started = True
        self._health.status = AgentStatus.HEALTHY
        self._health.last_heartbeat = datetime.now(timezone.utc)
        self.logger.info(f"{self.name} agent started")

    async def stop(self):
        """Shut down the agent. Override to add cleanup logic."""
        self._started = False
        self._health.status = AgentStatus.OFFLINE
        self.logger.info(f"{self.name} agent stopped")

    @abstractmethod
    async def run_cycle(self, cycle_id: str) -> Any:
        """
        Execute one prediction cycle. Must be implemented by each agent.

        Args:
            cycle_id: Unique identifier for this prediction cycle.

        Returns:
            The agent's signal/output for this cycle.
        """
        pass

    async def execute_cycle(self, cycle_id: str) -> Optional[Any]:
        """
        Wrapper around run_cycle that handles timing, errors, and health.
        Called by the orchestrator — agents should NOT override this.
        """
        start = time.monotonic()
        self._health.last_heartbeat = datetime.now(timezone.utc)

        try:
            result = await self.run_cycle(cycle_id)

            # Update health metrics
            elapsed = (time.monotonic() - start) * 1000  # ms
            self._cycle_count += 1
            self._total_response_time += elapsed
            self._health.avg_response_time_ms = (
                self._total_response_time / self._cycle_count
            )
            self._health.last_signal_time = datetime.now(timezone.utc)
            self._health.consecutive_failures = 0
            self._health.status = AgentStatus.HEALTHY

            self.logger.info(
                f"{self.name} cycle {cycle_id} completed in {elapsed:.0f}ms"
            )
            return result

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            self._error_count += 1
            self._health.error_count_1h += 1
            self._health.consecutive_failures += 1
            self._health.last_error = str(e)

            if self._health.consecutive_failures >= 3:
                self._health.status = AgentStatus.FAILING
            else:
                self._health.status = AgentStatus.DEGRADED

            self.logger.error(
                f"{self.name} cycle {cycle_id} failed after {elapsed:.0f}ms: {e}"
            )
            return None

    def publish(self, topic: str, data: Any):
        """Convenience method to publish to bus."""
        return self.bus.publish(topic, data, source=self.name)

    def get_signal(self, topic: str) -> Optional[Any]:
        """Convenience method to read latest signal from bus."""
        return self.bus.get_latest(topic)
