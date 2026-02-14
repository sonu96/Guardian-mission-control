/**
 * Auto-Discovery Pattern for Position Tracking
 *
 * Agents auto-discover positions from Webull/SnapTrade instead of waiting for manual /entered
 *
 * Flow:
 * 1. Position Health agent runs every 5min
 * 2. Calls webull_get_option_positions (source of truth)
 * 3. Compares with Convex positions table
 * 4. NEW positions → Create exec_id, fetch data, start monitoring
 * 5. CLOSED positions → Archive to Obsidian, stop monitoring
 */

import { ConvexHttpClient } from "convex/browser";
import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { api } from "../../convex/_generated/api";
import { getObsidianClient } from "./obsidian-client";

interface WebullPosition {
  ticker: string;
  strategy: string;
  expiration: string;
  strikes: {
    longCall?: number;
    shortCall?: number;
    longPut?: number;
    shortPut?: number;
  };
  quantity: number;
  entryPrice: number;
  currentPrice: number;
  unrealizedPnL: number;
  accountId: string;
}

interface ConvexPosition {
  _id: string;
  ticker: string;
  expiration: string;
  status: "active" | "closed" | "expired";
  execId?: string;
}

export class AutoDiscoveryManager {
  private convex: ConvexHttpClient;
  private supabase: SupabaseClient;
  private obsidian = getObsidianClient();

  constructor(config: { convexUrl: string; supabaseUrl: string; supabaseKey: string }) {
    this.convex = new ConvexHttpClient(config.convexUrl);
    this.supabase = createClient(config.supabaseUrl, config.supabaseKey);
  }

  /**
   * Main auto-discovery cycle (runs every 5 minutes)
   * Called by Position Health agent
   */
  async discoverPositions(webullPositions: WebullPosition[]): Promise<{
    newPositions: WebullPosition[];
    closedPositions: ConvexPosition[];
    existingPositions: WebullPosition[];
  }> {
    // Get current positions from Convex
    const convexPositions = await this.convex.query(api.queries.getAllPositions);

    // Detect NEW positions (in Webull, not in Convex)
    const newPositions = this.findNewPositions(webullPositions, convexPositions);

    // Detect CLOSED positions (in Convex, not in Webull)
    const closedPositions = this.findClosedPositions(webullPositions, convexPositions);

    // Existing positions (in both)
    const existingPositions = this.findExistingPositions(webullPositions, convexPositions);

    // Process new positions
    for (const position of newPositions) {
      await this.handleNewPosition(position);
    }

    // Process closed positions
    for (const position of closedPositions) {
      await this.handleClosedPosition(position);
    }

    return { newPositions, closedPositions, existingPositions };
  }

  /**
   * Handle newly discovered position
   */
  private async handleNewPosition(position: WebullPosition): Promise<void> {
    console.log(`🆕 New position discovered: ${position.ticker} ${position.strategy}`);

    // 1. Create exec_id for this monitoring session
    const execId = `${position.ticker.toLowerCase()}-${position.strategy}-${Date.now()}`;

    // 2. Create position in Convex (real-time tracking)
    const convexPositionId = await this.convex.mutation(api.mutations.createPosition, {
      ticker: position.ticker,
      strategy: position.strategy as any,
      expiration: position.expiration,
      strikes: position.strikes,
      quantity: position.quantity,
      entryPrice: position.entryPrice,
      currentPrice: position.currentPrice,
      unrealizedPnL: position.unrealizedPnL,
      accountId: position.accountId,
      execId,
      status: "active",
      openedAt: Date.now(),
      lastUpdated: Date.now(),
    });

    // 3. Create position tracking in Supabase (audit trail)
    await this.supabase.from("position_tracking").insert({
      symbol: position.ticker,
      expiration: position.expiration,
      status: "ENTERED",
      first_exec_id: execId,
      latest_exec_id: execId,
      all_exec_ids: [execId],
      analysis_count: 0,
      original_price: position.entryPrice,
      original_strategy: position.strategy,
      latest_price: position.currentPrice,
      entry_date: new Date().toISOString(),
      entry_premium: position.entryPrice,
      entry_legs: position.strikes,
    });

    // 4. Create Obsidian note (human-readable journal)
    await this.obsidian.createPositionNote({
      symbol: position.ticker,
      expiration: position.expiration,
      strategy: position.strategy,
      execId,
      entryPremium: position.entryPrice,
      strikes: position.strikes,
      guardianVerdict: {
        winnerAgent: "auto-discovery",
        confidence: 10,
        reasoning: `Position auto-discovered in Webull account ${position.accountId}`,
      },
      entryDate: new Date().toISOString(),
    });

    // 5. Log to daily note
    await this.obsidian.logAlert({
      symbol: position.ticker,
      severity: "info",
      message: `New ${position.strategy} position discovered (${this.formatStrikes(position.strikes)})`,
      triggeredBy: "position-health-monitor",
      timestamp: new Date().toLocaleTimeString(),
    });

    console.log(`✅ Position ${position.ticker} initialized with exec_id: ${execId}`);
  }

  /**
   * Handle position that no longer exists in Webull (closed)
   */
  private async handleClosedPosition(position: ConvexPosition): Promise<void> {
    console.log(`🚪 Position closed: ${position.ticker} (no longer in Webull)`);

    // 1. Update Convex status
    await this.convex.mutation(api.mutations.updatePosition, {
      positionId: position._id,
      status: "closed",
      closedAt: Date.now(),
    });

    // 2. Update Supabase tracking
    await this.supabase
      .from("position_tracking")
      .update({
        status: "CLOSED",
        exit_date: new Date().toISOString(),
      })
      .eq("symbol", position.ticker)
      .eq("expiration", position.expiration);

    // 3. Archive to Obsidian
    await this.obsidian.updatePositionOutcome({
      symbol: position.ticker,
      expiration: position.expiration,
      exitPremium: 0, // TODO: Calculate from last snapshot
      realizedPnL: 0, // TODO: Calculate from snapshots
      exitReason: "Position no longer detected in Webull (auto-closed)",
      daysHeld: 0, // TODO: Calculate
      exitDate: new Date().toISOString(),
    });

    // 4. Log to daily note
    await this.obsidian.logAlert({
      symbol: position.ticker,
      severity: "info",
      message: `Position closed (no longer detected in Webull)`,
      triggeredBy: "position-health-monitor",
      timestamp: new Date().toLocaleTimeString(),
    });

    console.log(`✅ Position ${position.ticker} archived`);
  }

  /**
   * Find positions in Webull but not in Convex (NEW)
   */
  private findNewPositions(
    webull: WebullPosition[],
    convex: ConvexPosition[]
  ): WebullPosition[] {
    return webull.filter(wp => {
      return !convex.some(
        cp =>
          cp.ticker === wp.ticker &&
          cp.expiration === wp.expiration &&
          cp.status === "active"
      );
    });
  }

  /**
   * Find positions in Convex but not in Webull (CLOSED)
   */
  private findClosedPositions(
    webull: WebullPosition[],
    convex: ConvexPosition[]
  ): ConvexPosition[] {
    return convex
      .filter(cp => cp.status === "active")
      .filter(cp => {
        return !webull.some(
          wp => wp.ticker === cp.ticker && wp.expiration === cp.expiration
        );
      });
  }

  /**
   * Find positions in both (EXISTING)
   */
  private findExistingPositions(
    webull: WebullPosition[],
    convex: ConvexPosition[]
  ): WebullPosition[] {
    return webull.filter(wp => {
      return convex.some(
        cp =>
          cp.ticker === wp.ticker &&
          cp.expiration === wp.expiration &&
          cp.status === "active"
      );
    });
  }

  /**
   * Format strikes for display
   */
  private formatStrikes(strikes: WebullPosition["strikes"]): string {
    const parts: string[] = [];
    if (strikes.longCall) parts.push(`LC${strikes.longCall}`);
    if (strikes.shortCall) parts.push(`SC${strikes.shortCall}`);
    if (strikes.longPut) parts.push(`LP${strikes.longPut}`);
    if (strikes.shortPut) parts.push(`SP${strikes.shortPut}`);
    return parts.join("/");
  }
}

// ===== SINGLETON INSTANCE =====

let autoDiscoveryInstance: AutoDiscoveryManager | null = null;

export function getAutoDiscoveryManager(): AutoDiscoveryManager {
  if (!autoDiscoveryInstance) {
    const config = {
      convexUrl: process.env.VITE_CONVEX_URL || "",
      supabaseUrl: process.env.SUPABASE_URL || "",
      supabaseKey: process.env.SUPABASE_SERVICE_KEY || "",
    };

    autoDiscoveryInstance = new AutoDiscoveryManager(config);
  }

  return autoDiscoveryInstance;
}
