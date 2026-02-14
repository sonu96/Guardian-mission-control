# Guardian Mission Control - Hybrid Storage Deployment Guide

## Overview

This guide covers the deployment of the 3-tier hybrid storage architecture:
- **Convex**: Real-time UI synchronization (30-day retention)
- **Supabase**: Permanent audit trail (7-year retention)
- **Mem0**: Agent working memory and learned patterns

## Prerequisites

- Bun 1.0+ installed
- Convex account (https://convex.dev)
- Supabase project created (https://supabase.com)
- Mem0 API key (https://mem0.ai)
- Node.js 18+ (for nightly export cron)

## Phase 1: Infrastructure Setup

### 1.1 Create Convex Project

```bash
cd /Users/abhisonu/Documents/GitHub/Guardian-mission-control
bunx convex dev
```

Follow prompts to create new project or link existing.

### 1.2 Create Supabase Project

1. Visit https://supabase.com/dashboard
2. Click "New Project"
3. Choose organization and region (use same region as Convex for latency)
4. Save connection details

### 1.3 Enable pgvector Extension

In Supabase SQL Editor:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 1.4 Configure Environment Variables

Create `.env.local`:

```bash
# Convex
VITE_CONVEX_URL=https://your-project.convex.cloud

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ... (anon key)
SUPABASE_SERVICE_KEY=eyJ... (service_role key - KEEP SECRET!)

# Mem0
MEM0_API_KEY=mem0_... (from https://app.mem0.ai)
MEM0_ORG_ID=org_... (optional)

# OpenAI (for embeddings)
OPENAI_API_KEY=sk-...
```

## Phase 2: Database Schema Deployment

### 2.1 Deploy Convex Schema

```bash
bunx convex deploy
```

This deploys `/convex/schema.ts` and `/convex/options-schema.ts`.

Verify deployment:
```bash
bunx convex dashboard
```

### 2.2 Run Supabase Migrations

```bash
cd supabase/migrations

# Run migrations in order
supabase db push

# Or manually via SQL Editor:
# 1. Copy 001_guardian_foundation.sql
# 2. Paste in Supabase SQL Editor
# 3. Run
# 4. Repeat for 002_mcp_integration.sql and 003_forensic_replay.sql
```

Verify tables created:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

Expected tables:
- `position_tracking`
- `position_snapshots` (with partitions)
- `agent_debate_outcomes`
- `approval_requests`
- `mem0_vectors`
- `supermemory_knowledge`
- `battle_results`
- `supermemory_archive`

### 2.3 Create Monthly Partitions

For upcoming months, run this in Supabase SQL Editor:

```sql
-- June 2026
CREATE TABLE position_snapshots_2026_06 PARTITION OF position_snapshots
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- July 2026
CREATE TABLE position_snapshots_2026_07 PARTITION OF position_snapshots
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

-- Add more as needed
```

## Phase 3: Data Flow Integration

### 3.1 Test Dual-Write Pattern

Create test script `test-dual-write.ts`:

```typescript
import { getDualWriteManager } from "./src/storage/dual-write";

async function test() {
  const dw = getDualWriteManager();

  // Test position update
  await dw.updatePositionGreeks("test-position-123", {
    currentPrice: 2.50,
    unrealizedPnL: 125.00,
    delta: 0.45,
    gamma: 0.08,
    theta: -12.50,
    vega: 15.30,
  });

  console.log("✅ Dual-write test passed");
}

test();
```

Run test:
```bash
bun run test-dual-write.ts
```

Verify:
1. Check Convex dashboard for position update
2. Check Supabase `position_snapshots` table for new row

### 3.2 Test Mem0 Integration

Create test script `test-mem0.ts`:

```typescript
import { getMem0Client } from "./src/memory/mem0-client";

async function test() {
  const mem0 = getMem0Client();

  const sessionId = "test-guardian-msft-" + Date.now();

  // Add session memory
  await mem0.add(sessionId, "Test finding: MSFT IV rank 87", {
    agent: "vega-master",
    symbol: "MSFT",
  });

  // Search session memory
  const results = await mem0.search("IV rank", sessionId);
  console.log("Search results:", results);

  // Cleanup
  await mem0.delete(sessionId);

  console.log("✅ Mem0 test passed");
}

test();
```

Run test:
```bash
bun run test-mem0.ts
```

### 3.3 Setup Nightly Export Cron

Add to crontab:

```bash
# Open crontab editor
crontab -e

# Add this line (runs daily at 2 AM ET)
0 2 * * * cd /Users/abhisonu/Documents/GitHub/Guardian-mission-control && bun run scripts/nightly-export.ts >> /var/log/guardian-export.log 2>&1
```

Test manually:
```bash
bun run scripts/nightly-export.ts
```

## Phase 4: Forensic Replay Testing

### 4.1 Test Battle Context Query

In Supabase SQL Editor:

```sql
-- Replace with actual exec_id from your system
SELECT * FROM get_battle_context('msft-1707532800');
```

### 4.2 Test Agent Decision Context

```sql
SELECT * FROM agent_decision_context(
  'vega-master',
  'MSFT',
  '2026-02-13'
);
```

### 4.3 Test Position Forensics

```sql
SELECT * FROM get_position_forensics('MSFT', '2026-02-20');
```

## Phase 5: Performance Validation

### 5.1 Query Performance Benchmarks

Run this in Supabase SQL Editor:

```sql
-- Check query performance stats
SELECT * FROM query_performance_stats;

-- Test position snapshot query (should be <100ms)
EXPLAIN ANALYZE
SELECT * FROM position_snapshots
WHERE position_id = 'test-position-123'
  AND snapshot_at > NOW() - INTERVAL '24 hours';

-- Test vector search (should be <200ms)
EXPLAIN ANALYZE
SELECT * FROM match_supermemory_knowledge(
  (SELECT embedding FROM supermemory_knowledge LIMIT 1),
  0.7,
  10
);
```

### 5.2 Convex Query Performance

In Convex dashboard, check:
- Mutation latency: Target <50ms p95
- Query latency: Target <100ms p95
- Real-time subscription updates: Target <500ms

### 5.3 Load Testing

Create load test script `load-test.ts`:

```typescript
import { getDualWriteManager } from "./src/storage/dual-write";

async function loadTest() {
  const dw = getDualWriteManager();
  const startTime = Date.now();
  const iterations = 100;

  for (let i = 0; i < iterations; i++) {
    await dw.updatePositionGreeks(`test-position-${i}`, {
      currentPrice: Math.random() * 10,
      unrealizedPnL: Math.random() * 500 - 250,
      delta: Math.random(),
      gamma: Math.random() * 0.1,
      theta: Math.random() * -20,
      vega: Math.random() * 30,
    });
  }

  const duration = Date.now() - startTime;
  const avgLatency = duration / iterations;

  console.log(`✅ Load test complete`);
  console.log(`${iterations} iterations in ${duration}ms`);
  console.log(`Average latency: ${avgLatency.toFixed(2)}ms`);
}

loadTest();
```

Run:
```bash
bun run load-test.ts
```

Target: <100ms average latency for dual-writes

## Phase 6: Disaster Recovery Setup

### 6.1 Enable Supabase Backups

In Supabase dashboard:
1. Settings → Database → Backups
2. Verify daily backups enabled (default on Pro plan)
3. Note point-in-time recovery available

### 6.2 Test Backup Restoration

```bash
# Download latest backup
supabase db dump --remote > backup.sql

# Test restore to new project (don't run on production!)
supabase db reset
psql -h localhost -U postgres -d postgres < backup.sql
```

### 6.3 Setup S3 Archive (Optional)

For 7-year compliance, setup weekly S3 backups:

Create `scripts/weekly-backup.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y-%m-%d)
BACKUP_FILE="guardian-backup-$DATE.sql"

# Dump Supabase database
pg_dump $SUPABASE_URL > $BACKUP_FILE

# Upload to S3
aws s3 cp $BACKUP_FILE s3://your-bucket/guardian-backups/

# Cleanup local file
rm $BACKUP_FILE

echo "✅ Backup uploaded to S3"
```

Add to crontab (Sundays at 3 AM):
```
0 3 * * 0 /path/to/scripts/weekly-backup.sh
```

## Phase 7: Monitoring & Alerts

### 7.1 Setup Discord Webhooks

Create webhook in Discord server settings.

Add to `.env.local`:
```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 7.2 Create Health Check Endpoint

In Convex, create `convex/health.ts`:

```typescript
import { query } from "./_generated/server";

export const healthCheck = query({
  handler: async (ctx) => {
    const positions = await ctx.db.query("positions").take(1);
    const monitors = await ctx.db.query("monitors").take(1);

    return {
      status: "healthy",
      timestamp: Date.now(),
      convex: {
        connected: true,
        positions: positions.length > 0,
        monitors: monitors.length > 0,
      },
    };
  },
});
```

### 7.3 Setup Uptime Monitoring

Use UptimeRobot or similar to monitor:
- Convex: https://your-project.convex.cloud/api/health
- Supabase: https://your-project.supabase.co/rest/v1/

## Troubleshooting

### Convex mutations slow (>500ms)

**Solution:**
1. Check indexes in `schema.ts`
2. Use optimistic updates for instant UI
3. Batch operations instead of individual mutations

### Supabase connection pool exhausted

**Solution:**
```typescript
// Add connection pooling
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(url, key, {
  db: {
    schema: "public",
  },
  global: {
    headers: { "x-my-custom-header": "guardian" },
  },
  realtime: {
    params: {
      eventsPerSecond: 10,
    },
  },
});
```

### Mem0 search returns stale results

**Solution:**
1. Verify session ID is correct
2. Check if session was deleted prematurely
3. Re-index embeddings: `await mem0Client.reindex()`

### Nightly export failing

**Check logs:**
```bash
tail -f /var/log/guardian-export.log
```

**Common issues:**
- Supabase connection timeout → Increase timeout in config
- Convex API rate limit → Add delays between batch operations
- Out of memory → Reduce batch size in export script

## Security Checklist

- [ ] Supabase RLS policies enabled
- [ ] Service role key in environment variables (not committed)
- [ ] Convex auth configured (Clerk/Auth0)
- [ ] API keys rotated every 90 days
- [ ] Backup encryption enabled
- [ ] SSL/TLS for all connections
- [ ] Rate limiting on public endpoints

## Production Checklist

- [ ] All migrations applied
- [ ] Indexes created and verified
- [ ] Nightly export cron running
- [ ] Backup restoration tested
- [ ] Load testing passed (100+ concurrent writes)
- [ ] Query performance meets targets (<100ms)
- [ ] Monitoring and alerts configured
- [ ] Documentation complete
- [ ] Team training completed

## Next Steps

1. **Integrate with OpenClaw**: Connect monitoring agents to Convex mutations
2. **Build Guardian UI**: Real-time dashboard using Convex React hooks
3. **Add MCP Tools**: Implement exec_id linkage for forensic replay
4. **Paper Trading**: Test system with simulated positions (4 weeks)
5. **Production Launch**: Deploy with 1-2 real positions for validation

## Support

- Convex docs: https://docs.convex.dev
- Supabase docs: https://supabase.com/docs
- Mem0 docs: https://docs.mem0.ai
- Internal docs: `/docs/storage-architecture.md`

## Architecture Diagrams

See `/docs/storage-architecture.md` for:
- Entity relationship diagrams
- Data flow patterns
- Forensic replay examples
- Performance benchmarks
