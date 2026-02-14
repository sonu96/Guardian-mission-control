# Guardian Mission Control - Infrastructure Setup Guide

## Overview

This guide walks you through setting up the complete infrastructure for Guardian Mission Control's 8-agent options monitoring system.

## Prerequisites

- Node.js 18+ (or Bun)
- npm or bun package manager
- Convex account (https://dashboard.convex.dev)
- Supabase account (https://supabase.com)
- Discord webhook URL (for alerts)

## Phase 1: Convex Setup

### 1.1 Login to Convex

```bash
npx convex login
```

### 1.2 Initialize Convex Project

```bash
npx convex dev
```

This will:
- Create a new Convex project
- Deploy the schema (including options tables)
- Generate `.env.local` with your deployment URL

### 1.3 Verify Schema Deployment

Check that these tables are created:
- `agents`, `tasks`, `messages`, `activities`, `documents` (base)
- `positions`, `alerts`, `monitors`, `heartbeat_runs` (options)
- `trade_plans`, `agent_debates`, `market_regime` (guardian)
- `alert_cooldowns` (deduplication)

### 1.4 Get Convex Deployment URL

After `convex dev` completes, note your deployment URL:
```
https://your-project.convex.cloud
```

## Phase 2: Supabase Setup

### 2.1 Create Supabase Project

1. Go to https://supabase.com/dashboard
2. Click "New Project"
3. Choose a name (e.g., "guardian-mission-control")
4. Select region (closest to you)
5. Generate a strong database password

### 2.2 Enable pgvector Extension

In the SQL Editor, run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2.3 Run Migrations

Navigate to SQL Editor and run each migration file in order:

```bash
# See supabase/migrations/ directory
001_create_exec_sessions.sql
002_create_position_tracking.sql
003_create_agent_debates.sql
004_create_mem0_tables.sql
```

### 2.4 Get Supabase Credentials

From Project Settings > API:
- Project URL: `https://your-project.supabase.co`
- Anon/Public Key: `eyJ...` (for frontend)
- Service Role Key: `eyJ...` (for backend - KEEP SECRET!)

## Phase 3: Environment Variables

### 3.1 Copy Template

```bash
cp .env.local.example .env.local
```

### 3.2 Fill in Values

Edit `.env.local`:

```bash
# Convex
CONVEX_DEPLOYMENT=prod:your-project-name-123
VITE_CONVEX_URL=https://your-project.convex.cloud

# Supabase
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...your-anon-key
SUPABASE_SERVICE_ROLE_KEY=eyJ...your-service-role-key

# Discord (get from Discord Server Settings > Integrations > Webhooks)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123.../abc...

# Mission Control URL (for MCP server callbacks)
MISSION_CONTROL_URL=https://your-project.convex.site
```

### 3.3 Add to Convex Environment

In Convex Dashboard > Settings > Environment Variables, add:
- `DISCORD_WEBHOOK_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Phase 4: Discord Webhook Setup

### 4.1 Create Webhook

1. Open your Discord server
2. Go to Server Settings > Integrations
3. Click "Create Webhook"
4. Name it "Guardian Alerts"
5. Select channel (#trading-alerts)
6. Copy webhook URL

### 4.2 Test Webhook

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Guardian Mission Control is online! 🚀",
    "embeds": [{
      "title": "Infrastructure Test",
      "description": "All systems operational",
      "color": 65280
    }]
  }' \
  "YOUR_DISCORD_WEBHOOK_URL"
```

You should see a message in Discord.

## Phase 5: Development Environment

### 5.1 Install Dependencies

```bash
npm install
# or
bun install
```

### 5.2 Start Development Server

```bash
npm run dev
```

This starts:
- Vite dev server (frontend): http://localhost:5173
- Convex dev mode (backend): Real-time sync enabled

### 5.3 Verify Dashboard Access

1. Open http://localhost:5173
2. You should see the Mission Control dashboard
3. Check browser console for errors

## Phase 6: Seed Initial Data

### 6.1 Create Monitor Agents

Run the seed script to create the 8 monitoring agents:

```bash
npx convex run seed:createMonitors
```

This creates:
- Guardian (5min heartbeat)
- Risk Monitor (15min)
- Flow Monitor (1hour)
- GEX Monitor (4hour)
- Volatility Monitor (daily)
- Earnings Monitor (daily)
- Technical Scout (15min)
- Position Health Monitor (5min)

### 6.2 Verify Agents

In the dashboard, you should see all 8 agents listed in the Agents Sidebar.

## Phase 7: Integration Testing

### 7.1 Test Position Creation

```bash
npx convex run testing:createTestPosition '{
  "symbol": "AAPL",
  "strategy": "iron_condor",
  "strikes": {"shortPut": 170, "longPut": 165, "shortCall": 185, "longCall": 190}
}'
```

### 7.2 Test Alert Generation

```bash
npx convex run testing:createTestAlert '{
  "positionId": "...",
  "severity": "warning",
  "message": "Test alert"
}'
```

Check Discord for webhook delivery.

### 7.3 Test Heartbeat

```bash
npx convex run testing:triggerHeartbeat '{
  "monitorId": "guardian"
}'
```

## Phase 8: MCP Server Integration

### 8.1 Configure MCP Webhook

In your massive-options-mcp project, add to `.env`:

```bash
MISSION_CONTROL_URL=https://your-project.convex.site
```

### 8.2 Test Webhook Endpoint

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "positionId": "test-123",
    "agentId": "guardian",
    "type": "greeks_update",
    "data": {"delta": 0.5, "gamma": 0.02}
  }' \
  "https://your-project.convex.site/agent/event"
```

## Troubleshooting

### Convex Schema Errors

If you see schema validation errors:

```bash
# Push schema changes
npx convex deploy

# Or reset if needed (WARNING: deletes data)
npx convex data delete --table positions --all
```

### Supabase Connection Issues

Test Supabase connectivity:

```javascript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.VITE_SUPABASE_URL,
  process.env.VITE_SUPABASE_ANON_KEY
);

const { data, error } = await supabase.from('position_tracking').select('count');
console.log('Supabase test:', { data, error });
```

### Discord Webhook Not Working

- Verify webhook URL is correct
- Check Discord server permissions
- Test with curl command above
- Check rate limits (30 messages per minute)

## Production Deployment

### Convex Production

```bash
npx convex deploy --prod
```

### Environment Variables

Update production environment variables in Convex Dashboard.

### Monitoring

Set up alerts for:
- Convex function errors
- Supabase connection failures
- Discord webhook failures
- Agent heartbeat failures

## Security Checklist

- [ ] `.env.local` added to `.gitignore`
- [ ] Service role key stored in Convex environment only
- [ ] Discord webhook URL not committed to git
- [ ] Supabase RLS policies enabled
- [ ] API rate limiting configured
- [ ] CORS configured for production domain

## Next Steps

1. Complete frontend UI components (Task #3)
2. Implement 8 monitor agents (Task #4)
3. Integrate Mem0 for agent learning (Task #5)
4. Setup production deployment (Task #6)

## Support

For issues or questions:
- Team lead: Use SendMessage tool
- Convex docs: https://docs.convex.dev
- Supabase docs: https://supabase.com/docs
- Project README: /Users/abhisonu/Documents/GitHub/Guardian-mission-control/README.md
