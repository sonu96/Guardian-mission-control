#!/usr/bin/env bun
/**
 * Test Obsidian Integration
 * Verifies note creation, agent verdicts, and alerts
 */

import { getObsidianClient } from "../src/storage/obsidian-client";

async function test() {
  console.log("🧪 Testing Obsidian Integration...\n");

  const obsidian = getObsidianClient();

  try {
    // Test 1: Create position note
    console.log("1. Creating position note...");
    await obsidian.createPositionNote({
      symbol: "TEST",
      expiration: "2026-03-20",
      strategy: "iron_condor",
      execId: "test-" + Date.now(),
      entryPremium: 250.00,
      strikes: {
        longCall: 100,
        shortCall: 95,
        longPut: 85,
        shortPut: 90,
      },
      guardianVerdict: {
        winnerAgent: "theta-decay",
        confidence: 8.5,
        reasoning: "High IV rank (87) suggests premium selling. Positive GEX supports range-bound action.",
      },
      entryDate: new Date().toISOString(),
    });
    console.log("✅ Position note created\n");

    // Test 2: Log agent verdict
    console.log("2. Logging agent verdict...");
    await obsidian.logAgentVerdict({
      symbol: "TEST",
      agentName: "technical-scout",
      status: "HOLD",
      keyFinding: "RSI 58, ADX 22 (range-bound), no divergence detected",
      confidence: 7.5,
      execId: "test-" + Date.now(),
      timestamp: new Date().toLocaleTimeString(),
    });
    console.log("✅ Agent verdict logged\n");

    // Test 3: Log alert
    console.log("3. Logging alert...");
    await obsidian.logAlert({
      symbol: "TEST",
      severity: "warning",
      message: "P&L approaching -$50 (stop loss: -$100)",
      triggeredBy: "position-health-monitor",
      timestamp: new Date().toLocaleTimeString(),
    });
    console.log("✅ Alert logged\n");

    // Test 4: Update position outcome
    console.log("4. Updating position outcome...");
    await obsidian.updatePositionOutcome({
      symbol: "TEST",
      expiration: "2026-03-20",
      exitPremium: 125.00,
      realizedPnL: -125.00,
      exitReason: "Stop loss triggered by technical scout",
      daysHeld: 7,
      exitDate: new Date().toISOString(),
    });
    console.log("✅ Position outcome updated\n");

    console.log("╔══════════════════════════════════════════════╗");
    console.log("║  ✅ All Tests Passed!                       ║");
    console.log("║                                              ║");
    console.log("║  Check Obsidian TradingVault:                ║");
    console.log("║  - Positions/TEST_20260320.md                ║");
    console.log("║  - Daily Notes/[today].md                    ║");
    console.log("╚══════════════════════════════════════════════╝");

  } catch (error) {
    console.error("\n❌ Test failed:", error);
    process.exit(1);
  }
}

test();
