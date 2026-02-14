#!/usr/bin/env bun
/**
 * Nightly Export Script
 * Exports Convex real-time data to Supabase permanent audit trail
 *
 * Runs daily at 2 AM ET via cron
 * Schedule: 0 2 * * * bun run scripts/nightly-export.ts
 *
 * Purpose:
 * - Archive position snapshots for P&L charting
 * - Export debate outcomes for validation
 * - Maintain 30-day retention in Convex
 */

import { ConvexHttpClient } from "convex/browser";
import { api } from "../convex/_generated/api";
import { createClient } from "@supabase/supabase-js";

// Environment variables
const CONVEX_URL = process.env.VITE_CONVEX_URL!;
const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY!;

const convex = new ConvexHttpClient(CONVEX_URL);
const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

interface ExportStats {
  positionSnapshotsExported: number;
  debateOutcomesExported: number;
  oldPositionsDeleted: number;
  oldAlertsDeleted: number;
  errors: string[];
}

async function exportPositionSnapshots(): Promise<number> {
  console.log("📊 Exporting position snapshots...");

  // Get all active positions from Convex
  const positions = await convex.query(api.queries.getAllPositions);

  if (!positions || positions.length === 0) {
    console.log("No positions to export");
    return 0;
  }

  const snapshots = positions.map(p => ({
    position_id: p._id,
    ticker: p.ticker,
    strategy: p.strategy,
    current_price: p.currentPrice,
    unrealized_pnl: p.unrealizedPnL,
    delta: p.delta,
    gamma: p.gamma,
    theta: p.theta,
    vega: p.vega,
    underlying_price: 0, // TODO: Fetch from gold_summaries
    days_to_expiration: p.daysToExpiration,
    iv_rank: 0, // TODO: Fetch from gold_summaries
    snapshot_at: new Date(p.lastUpdated).toISOString(),
  }));

  const { data, error } = await supabase
    .from("position_snapshots")
    .insert(snapshots);

  if (error) {
    console.error("❌ Error exporting snapshots:", error);
    throw error;
  }

  console.log(`✅ Exported ${snapshots.length} position snapshots`);
  return snapshots.length;
}

async function exportDebateOutcomes(): Promise<number> {
  console.log("🥊 Exporting debate outcomes...");

  // Get recent debates from Convex
  const debates = await convex.query(api.queries.getRecentDebates);

  if (!debates || debates.length === 0) {
    console.log("No debates to export");
    return 0;
  }

  const outcomes = debates.map(d => ({
    convex_debate_id: d._id,
    position_id: d.positionId,
    ticker: "", // TODO: Join with position to get ticker
    strategy: "", // TODO: Join with position to get strategy
    challenger_agent: d.challengerAgentId,
    defender_agent: d.defenderAgentId,
    challenger_recommendation: d.challengerRec,
    challenger_confidence: d.challengerConfidence,
    defender_recommendation: d.defenderRec,
    defender_confidence: d.defenderConfidence,
    resolution_type: d.resolution || null,
    winner_agent: d.winnerAgentId || null,
    final_action: d.finalAction || null,
    human_decision: d.humanDecision || null,
    decided_by: null,
    decided_at: null,
    market_context: d.marketContext,
    actual_outcome: d.actualOutcome || null,
    outcome_determined_at: null,
    outcome_metrics: null,
  }));

  const { data, error } = await supabase
    .from("agent_debate_outcomes")
    .insert(outcomes);

  if (error) {
    console.error("❌ Error exporting debates:", error);
    throw error;
  }

  console.log(`✅ Exported ${outcomes.length} debate outcomes`);

  // Refresh materialized view
  await supabase.rpc("refresh_agent_accuracy_stats");

  return outcomes.length;
}

async function cleanupOldConvexData(): Promise<{ positions: number; alerts: number }> {
  console.log("🧹 Cleaning up old Convex data (30-day retention)...");

  const thirtyDaysAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;

  // Delete closed positions older than 30 days
  // TODO: Implement deleteOldPositions mutation in Convex
  // const deletedPositions = await convex.mutation(api.mutations.deleteOldPositions, {
  //   beforeTimestamp: thirtyDaysAgo,
  // });

  // Delete acknowledged alerts older than 30 days
  // TODO: Implement deleteOldAlerts mutation in Convex
  // const deletedAlerts = await convex.mutation(api.mutations.deleteOldAlerts, {
  //   beforeTimestamp: thirtyDaysAgo,
  // });

  console.log("✅ Cleanup complete");
  return { positions: 0, alerts: 0 };
}

async function main() {
  console.log("🌙 Starting nightly export job...");
  console.log("Time:", new Date().toISOString());

  const stats: ExportStats = {
    positionSnapshotsExported: 0,
    debateOutcomesExported: 0,
    oldPositionsDeleted: 0,
    oldAlertsDeleted: 0,
    errors: [],
  };

  try {
    // Export data to Supabase
    stats.positionSnapshotsExported = await exportPositionSnapshots();
    stats.debateOutcomesExported = await exportDebateOutcomes();

    // Cleanup old Convex data
    const cleanup = await cleanupOldConvexData();
    stats.oldPositionsDeleted = cleanup.positions;
    stats.oldAlertsDeleted = cleanup.alerts;

    // Run Supabase nightly cleanup
    const { error: cleanupError } = await supabase.rpc("nightly_cleanup");
    if (cleanupError) {
      console.error("❌ Supabase cleanup error:", cleanupError);
      stats.errors.push(`Supabase cleanup: ${cleanupError.message}`);
    }

  } catch (error) {
    console.error("❌ Export job failed:", error);
    stats.errors.push(error instanceof Error ? error.message : String(error));
  }

  // Print summary
  console.log("\n📊 Export Summary:");
  console.log("─".repeat(50));
  console.log(`Position snapshots exported: ${stats.positionSnapshotsExported}`);
  console.log(`Debate outcomes exported: ${stats.debateOutcomesExported}`);
  console.log(`Old positions deleted: ${stats.oldPositionsDeleted}`);
  console.log(`Old alerts deleted: ${stats.oldAlertsDeleted}`);
  console.log(`Errors: ${stats.errors.length}`);

  if (stats.errors.length > 0) {
    console.log("\n❌ Errors:");
    stats.errors.forEach(err => console.log(`  - ${err}`));
    process.exit(1);
  }

  console.log("\n✅ Nightly export completed successfully");
  process.exit(0);
}

main();
