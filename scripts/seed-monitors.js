#!/usr/bin/env node
/**
 * Seed Monitor Agents for Guardian Mission Control
 *
 * Creates the 8 monitoring agents in Convex database
 *
 * Usage: node scripts/seed-monitors.js
 */

const monitors = [
  {
    id: 'guardian',
    name: 'Guardian',
    category: 'position_health',
    heartbeatInterval: '5min',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'risk-monitor',
    name: 'Risk Monitor',
    category: 'risk_assessment',
    heartbeatInterval: '15min',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'flow-monitor',
    name: 'Flow Monitor',
    category: 'flow_analysis',
    heartbeatInterval: '1hour',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'gex-monitor',
    name: 'GEX Monitor',
    category: 'gex_monitoring',
    heartbeatInterval: '4hour',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'volatility-monitor',
    name: 'Volatility Monitor',
    category: 'volatility_tracking',
    heartbeatInterval: 'daily',
    status: 'idle',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'earnings-monitor',
    name: 'Earnings Monitor',
    category: 'earnings_watch',
    heartbeatInterval: 'daily',
    status: 'idle',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'technical-scout',
    name: 'Technical Scout',
    category: 'position_health',
    heartbeatInterval: '15min',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  },
  {
    id: 'position-health',
    name: 'Position Health Monitor',
    category: 'position_health',
    heartbeatInterval: '5min',
    status: 'active',
    consecutiveFailures: 0,
    totalRunsToday: 0,
    positionsMonitored: 0
  }
];

console.log('📊 Guardian Mission Control - Monitor Agents Setup\n');
console.log('This script should be run via Convex after Convex dev is initialized:\n');
console.log('  npx convex dev\n');
console.log('Then create a mutation in convex/monitors.ts:\n');
console.log(`
import { mutation } from "./_generated/server";
import { v } from "convex/values";

export const seedMonitors = mutation({
  handler: async (ctx) => {
    const monitors = ${JSON.stringify(monitors, null, 2)};

    for (const monitor of monitors) {
      // Check if monitor already exists
      const existing = await ctx.db
        .query("monitors")
        .withIndex("by_tenant_id", (q) =>
          q.eq("tenantId", undefined).eq("id", monitor.id)
        )
        .first();

      if (!existing) {
        await ctx.db.insert("monitors", monitor);
        console.log(\`✅ Created monitor: \${monitor.name}\`);
      } else {
        console.log(\`⏭️  Monitor exists: \${monitor.name}\`);
      }
    }

    return { success: true, count: monitors.length };
  },
});
`);
console.log('Then run:\n');
console.log('  npx convex run monitors:seedMonitors\n');
console.log('🔍 Monitor Details:\n');

monitors.forEach((monitor, i) => {
  console.log(`${i + 1}. ${monitor.name}`);
  console.log(`   ID: ${monitor.id}`);
  console.log(`   Frequency: ${monitor.heartbeatInterval}`);
  console.log(`   Category: ${monitor.category}`);
  console.log('');
});

console.log('✅ Copy the mutation code above to convex/monitors.ts');
