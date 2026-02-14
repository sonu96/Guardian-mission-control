/**
 * Options Trading Schema Extensions for Guardian Mission Control
 *
 * This file extends the base schema with options-specific tables for
 * position tracking, alerts, agent heartbeats, and portfolio metrics.
 */

import { defineTable } from "convex/server";
import { v } from "convex/values";

export const optionsTables = {
  // Position tracking with real-time Greeks and P&L
  positions: defineTable({
    symbol: v.string(),
    strategy: v.union(
      v.literal("iron_condor"),
      v.literal("bull_put_spread"),
      v.literal("bear_call_spread"),
      v.literal("long_call"),
      v.literal("long_put"),
      v.literal("covered_call"),
      v.literal("cash_secured_put")
    ),
    entryDate: v.number(),
    expiration: v.string(), // YYYY-MM-DD
    strikes: v.object({
      longCall: v.optional(v.number()),
      shortCall: v.optional(v.number()),
      longPut: v.optional(v.number()),
      shortPut: v.optional(v.number()),
    }),
    contracts: v.number(),
    entryPrice: v.number(),
    currentPrice: v.optional(v.number()),
    currentPnL: v.optional(v.number()),
    currentPnLPercent: v.optional(v.number()),
    greeks: v.optional(v.object({
      delta: v.number(),
      gamma: v.number(),
      theta: v.number(),
      vega: v.number(),
    })),
    status: v.union(
      v.literal("monitoring"),
      v.literal("warning"),
      v.literal("critical"),
      v.literal("closed")
    ),
    mcpExecId: v.optional(v.string()), // Links to Supabase gold summary
    assignedMonitorId: v.optional(v.id("monitors")),
    webullPositionId: v.optional(v.string()),
    guardianSessionId: v.optional(v.string()),
    closeDate: v.optional(v.number()),
    closePnL: v.optional(v.number()),
    lastUpdated: v.number(),
    accountId: v.optional(v.string()),
    underlyingPrice: v.optional(v.number()),
    daysToExpiration: v.optional(v.number()),
    maxLoss: v.optional(v.number()),
    maxGain: v.optional(v.number()),
    breakEven: v.optional(v.array(v.number())),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_status", ["tenantId", "status"])
    .index("by_tenant_symbol", ["tenantId", "symbol"])
    .index("by_expiration", ["expiration"])
    .index("by_monitor", ["assignedMonitorId"]),

  // Multi-severity alerts with Discord integration
  alerts: defineTable({
    positionId: v.id("positions"),
    severity: v.union(
      v.literal("info"),
      v.literal("warning"),
      v.literal("critical")
    ),
    type: v.union(
      v.literal("price_movement"),
      v.literal("greek_threshold"),
      v.literal("earnings_risk"),
      v.literal("flow_divergence"),
      v.literal("technical_signal"),
      v.literal("stop_loss_approaching"),
      v.literal("profit_target_reached")
    ),
    message: v.string(),
    triggeredBy: v.id("monitors"),
    metric: v.optional(v.object({
      name: v.string(),
      value: v.number(),
      threshold: v.number(),
    })),
    dedupeKey: v.string(), // e.g., "position-123:price_movement:2026-02-13"
    cooldownUntil: v.optional(v.number()),
    acknowledged: v.boolean(),
    acknowledgedAt: v.optional(v.number()),
    actionTaken: v.optional(v.string()),
    discordMessageId: v.optional(v.string()),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_position", ["tenantId", "positionId"])
    .index("by_tenant_severity", ["tenantId", "severity"])
    .index("by_dedupe_key", ["dedupeKey"]),

  // Agent heartbeat tracking for 8-monitor system
  monitors: defineTable({
    id: v.string(), // e.g., "guardian", "risk-monitor", "flow-monitor"
    name: v.string(),
    category: v.union(
      v.literal("position_health"),
      v.literal("risk_assessment"),
      v.literal("flow_analysis"),
      v.literal("gex_monitoring"),
      v.literal("volatility_tracking"),
      v.literal("earnings_watch")
    ),
    status: v.union(
      v.literal("active"),
      v.literal("idle"),
      v.literal("error"),
      v.literal("blocked")
    ),
    heartbeatInterval: v.string(), // "5min", "15min", "1hour", "4hour", "daily"
    lastHeartbeat: v.optional(v.number()),
    nextHeartbeat: v.optional(v.number()),
    consecutiveFailures: v.number(),
    totalRunsToday: v.number(),
    avgExecutionMs: v.optional(v.number()),
    positionsMonitored: v.number(),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_id", ["tenantId", "id"]),

  // Heartbeat execution logs
  heartbeat_runs: defineTable({
    runId: v.string(),
    monitorId: v.id("monitors"),
    action: v.union(
      v.literal("position_check"),
      v.literal("risk_assessment"),
      v.literal("flow_analysis"),
      v.literal("alert_generation")
    ),
    prompt: v.optional(v.string()),
    response: v.optional(v.string()),
    error: v.optional(v.string()),
    executionMs: v.number(),
    apiCallsMade: v.number(),
    positionsChecked: v.number(),
    alertsGenerated: v.number(),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_monitor", ["monitorId"]),

  // Trade plans from Guardian battles
  trade_plans: defineTable({
    positionId: v.optional(v.id("positions")), // null for entry plans
    planType: v.union(
      v.literal("entry"),
      v.literal("exit"),
      v.literal("adjust"),
      v.literal("roll")
    ),
    content: v.string(),
    summary: v.string(),
    battleResults: v.optional(v.object({
      sessionId: v.string(),
      execId: v.string(),
      winnerAgent: v.string(),
      winnerScore: v.number(),
      allProposals: v.array(v.any()),
    })),
    approved: v.boolean(),
    approvedBy: v.optional(v.string()),
    approvedAt: v.optional(v.number()),
    deniedReason: v.optional(v.string()),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_position", ["positionId"]),

  // Agent debates and resolutions
  agent_debates: defineTable({
    positionId: v.id("positions"),
    challengerAgentId: v.string(),
    defenderAgentId: v.string(),
    challengerRecommendation: v.string(),
    challengerConfidence: v.number(),
    defenderRecommendation: v.string(),
    defenderConfidence: v.number(),
    resolution: v.optional(v.union(
      v.literal("veto"),
      v.literal("confidence_gap"),
      v.literal("majority_consensus"),
      v.literal("human_escalation")
    )),
    winnerAgentId: v.optional(v.string()),
    finalAction: v.optional(v.string()),
    humanDecision: v.optional(v.string()),
    marketContext: v.object({
      price: v.number(),
      daysToExpiration: v.number(),
      unrealizedPnL: v.number(),
    }),
    actualOutcome: v.optional(v.union(
      v.literal("challenger_correct"),
      v.literal("defender_correct"),
      v.literal("both_wrong")
    )),
    discordMessageId: v.optional(v.string()),
    tenantId: v.optional(v.string()),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_position", ["positionId"]),

  // Market regime tracking (15-min cache)
  market_regime: defineTable({
    vix: v.number(),
    vixChange24h: v.number(),
    vixRegime: v.string(), // "low", "medium", "high", "extreme"
    spyGex: v.number(),
    spyGexRegime: v.string(), // "positive", "negative", "neutral"
    spyPrice: v.number(),
    marketOpen: v.boolean(),
    marketPhase: v.string(), // "pre", "open", "post", "closed"
    putCallRatio: v.optional(v.number()),
    timestamp: v.number(),
  }),

  // Alert cooldown deduplication
  alert_cooldowns: defineTable({
    dedupeKey: v.string(),
    cooldownUntil: v.number(),
    alertCount: v.number(),
    firstAlertId: v.id("alerts"),
    lastAlertId: v.id("alerts"),
  })
    .index("by_dedupe_key", ["dedupeKey"])
    .index("by_cooldown", ["cooldownUntil"]),
};
