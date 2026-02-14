/**
 * Triple-Write Pattern
 * Writes to Convex (real-time) + Supabase (audit trail) + Obsidian (journal)
 *
 * Pattern:
 * 1. Write to Convex first (instant UI update)
 * 2. Write to Supabase async (audit trail, don't block UI)
 * 3. Write to Obsidian async (human-readable journal)
 * 4. If Supabase/Obsidian fail, log error but don't roll back Convex
 */

import { ConvexHttpClient } from "convex/browser";
import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { api } from "../../convex/_generated/api";
import { getObsidianClient } from "./obsidian-client";

interface DualWriteConfig {
  convexUrl: string;
  supabaseUrl: string;
  supabaseKey: string;
}

interface PositionSnapshot {
  position_id: string;
  ticker: string;
  strategy: string;
  current_price: number;
  unrealized_pnl: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  underlying_price?: number;
  days_to_expiration?: number;
  iv_rank?: number;
  snapshot_at: string;
}

export class DualWriteManager {
  private convex: ConvexHttpClient;
  private supabase: SupabaseClient;

  constructor(config: DualWriteConfig) {
    this.convex = new ConvexHttpClient(config.convexUrl);
    this.supabase = createClient(config.supabaseUrl, config.supabaseKey);
  }

  /**
   * Update position P&L (5-min heartbeat)
   * Writes to both Convex and Supabase
   */
  async updatePositionGreeks(
    positionId: string,
    data: {
      currentPrice: number;
      unrealizedPnL: number;
      delta: number;
      gamma: number;
      theta: number;
      vega: number;
      underlyingPrice?: number;
      daysToExpiration?: number;
    }
  ): Promise<void> {
    // 1. Write to Convex (instant UI update)
    await this.convex.mutation(api.mutations.updatePositionGreeks, {
      positionId,
      ...data,
    });

    // 2. Write to Supabase (audit trail, async)
    const snapshot: PositionSnapshot = {
      position_id: positionId,
      ticker: "", // TODO: Fetch from position
      strategy: "", // TODO: Fetch from position
      current_price: data.currentPrice,
      unrealized_pnl: data.unrealizedPnL,
      delta: data.delta,
      gamma: data.gamma,
      theta: data.theta,
      vega: data.vega,
      underlying_price: data.underlyingPrice,
      days_to_expiration: data.daysToExpiration,
      snapshot_at: new Date().toISOString(),
    };

    const { error } = await this.supabase
      .from("position_snapshots")
      .insert(snapshot);

    if (error) {
      console.error("Supabase snapshot write failed:", error);
      // Don't throw - we don't want to block UI updates
    }
  }

  /**
   * Create alert (dual-write with cooldown check)
   */
  async createAlert(data: {
    positionId: string;
    severity: "info" | "warning" | "critical";
    type: string;
    message: string;
    triggeredBy: string;
    dedupeKey: string;
    metric?: {
      name: string;
      value: number;
      threshold: number;
    };
  }): Promise<string | null> {
    // Check cooldown in Convex
    const cooldown = await this.convex.query(api.queries.getAlertCooldown, {
      dedupeKey: data.dedupeKey,
    });

    if (cooldown && cooldown.cooldownUntil > Date.now()) {
      console.log(`Alert suppressed (cooldown until ${new Date(cooldown.cooldownUntil)})`);
      return null;
    }

    // Create alert in Convex
    const alertId = await this.convex.mutation(api.mutations.createAlert, {
      ...data,
      acknowledged: false,
    });

    // No Supabase write for alerts - they're real-time only
    // Archived during nightly export if needed

    return alertId;
  }

  /**
   * Create trade plan (Guardian battle result)
   */
  async createTradePlan(data: {
    positionId?: string;
    planType: "entry" | "exit" | "adjust" | "roll";
    content: string;
    summary: string;
    battleResults?: {
      sessionId: string;
      execId: string;
      winnerAgent: string;
      confidence: number;
      allProposals: any[];
    };
  }): Promise<string> {
    // Create in Convex
    const planId = await this.convex.mutation(api.mutations.createTradePlan, {
      ...data,
      approved: false,
    });

    // If battle results exist, write to Supabase battle_results
    if (data.battleResults) {
      const { error } = await this.supabase
        .from("battle_results")
        .insert({
          exec_id: data.battleResults.execId,
          symbol: "", // TODO: Extract from execId lookup
          expiration: "", // TODO: Extract from execId lookup
          winning_agent: data.battleResults.winnerAgent,
          winning_strategy: data.planType,
          winning_proposal: {}, // TODO: Extract winner from allProposals
          all_proposals: data.battleResults.allProposals,
          user_approved: false,
          executed: false,
        });

      if (error) {
        console.error("Supabase battle_results write failed:", error);
      }
    }

    return planId;
  }

  /**
   * Record debate outcome
   */
  async createDebate(data: {
    positionId: string;
    challengerAgentId: string;
    defenderAgentId: string;
    challengerRec: "HOLD" | "EXIT" | "ADJUST" | "ROLL";
    challengerConfidence: number;
    defenderRec: "HOLD" | "EXIT" | "ADJUST" | "ROLL";
    defenderConfidence: number;
    marketContext: {
      price: number;
      pnl: number;
      dte: number;
    };
  }): Promise<string> {
    // Create in Convex
    const debateId = await this.convex.mutation(api.mutations.createDebate, data);

    // Supabase write happens during nightly export
    // This allows validation workflow to update actual_outcome

    return debateId;
  }

  /**
   * Update debate resolution
   */
  async resolveDebate(
    debateId: string,
    resolution: {
      resolution: "veto" | "confidence_gap" | "majority_consensus" | "human_escalation";
      winnerAgentId: string;
      finalAction: string;
      humanDecision?: string;
    }
  ): Promise<void> {
    // Update in Convex
    await this.convex.mutation(api.mutations.resolveDebate, {
      debateId,
      ...resolution,
    });

    // Export to Supabase for validation
    // Will be synced during nightly export
  }

  /**
   * Get position with audit history
   */
  async getPositionHistory(positionId: string): Promise<any> {
    // Real-time state from Convex
    const position = await this.convex.query(api.queries.getPosition, {
      positionId,
    });

    // Historical snapshots from Supabase
    const { data: snapshots } = await this.supabase
      .from("position_snapshots")
      .select("*")
      .eq("position_id", positionId)
      .order("snapshot_at", { ascending: false })
      .limit(100);

    return {
      current: position,
      history: snapshots || [],
    };
  }

  /**
   * Get agent accuracy stats (from Supabase materialized view)
   */
  async getAgentAccuracy(agentName: string): Promise<any> {
    const { data, error } = await this.supabase
      .from("agent_accuracy_stats")
      .select("*")
      .eq("agent_name", agentName);

    if (error) {
      throw new Error(`Failed to get accuracy stats: ${error.message}`);
    }

    return data;
  }
}

// ===== SINGLETON INSTANCE =====

let dualWriteInstance: DualWriteManager | null = null;

export function getDualWriteManager(): DualWriteManager {
  if (!dualWriteInstance) {
    const config: DualWriteConfig = {
      convexUrl: process.env.VITE_CONVEX_URL || "",
      supabaseUrl: process.env.SUPABASE_URL || "",
      supabaseKey: process.env.SUPABASE_SERVICE_KEY || "",
    };

    dualWriteInstance = new DualWriteManager(config);
  }

  return dualWriteInstance;
}
