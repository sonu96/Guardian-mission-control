## Obsidian Integration - Human-Readable Trading Journal

# Obsidian Integration for Guardian Mission Control

## Overview

Obsidian provides a **human-readable trading journal** alongside the Mission Control dashboard:

- **Dashboard** = Real-time monitoring (Convex)
- **Supabase** = Audit trail & analytics (SQL queries)
- **Obsidian** = Historical journal & full-text search (Markdown)

## Architecture

```
Guardian Alert/Analysis
         │
         ├─► Convex (real-time UI)
         ├─► Supabase (SQL audit trail)
         └─► Obsidian (Markdown journal)
```

**Triple-Write Pattern:**
1. Convex first (instant UI)
2. Supabase async (compliance)
3. Obsidian async (journal)

## Setup

### 1. Run Setup Script

```bash
cd /Users/abhisonu/Documents/GitHub/Guardian-mission-control
./scripts/setup-obsidian-vault.sh
```

This creates:
- `~/Documents/TradingVault/` vault
- Folder structure (Positions, Daily Notes, etc.)
- Note templates
- Obsidian config

### 2. Open Vault in Obsidian

1. Download Obsidian: https://obsidian.md
2. Open Obsidian
3. Click "Open folder as vault"
4. Select `~/Documents/TradingVault`

### 3. Configure Environment

Add to `.env.local`:

```bash
OBSIDIAN_VAULT_NAME=TradingVault
OBSIDIAN_VAULT_PATH=/Users/abhisonu/Documents/TradingVault
```

### 4. Test Integration

```bash
bun run scripts/test-obsidian.ts
```

Verify notes created in:
- `Positions/TEST_20260320.md`
- `Daily Notes/2026-02-13.md`

## Integration Points

### 1. Position Entry (`/entered` skill)

**Trigger:** User calls `/entered` skill

**Action:** Creates position note

**File:** `Positions/{SYMBOL}_{EXPIRATION}.md`

**Example:**
```markdown
---
symbol: MSFT
expiration: 2026-02-20
strategy: covered_call
exec_id: msft-1707532800
status: ACTIVE
---

# MSFT Covered Call - 2026-02-20

## Entry Details
- **Date**: 2026-02-13
- **Strategy**: covered_call
- **Strikes**: Short Call 420
- **Entry Premium**: $2.50
- **exec_id**: `msft-1707532800`

## Guardian Verdict
- **Winner**: theta-decay
- **Confidence**: 8.5/10
- **Reasoning**: IV rank 27.3% ideal for selling premium
```

### 2. Agent Verdicts

**Trigger:** Agent completes analysis (every 5min - daily)

**Action:** Appends to daily note

**File:** `Daily Notes/{TODAY}.md`

**Example:**
```markdown
## 14:30 - MSFT ✅
- **Agent**: technical-scout
- **Status**: HOLD
- **Finding**: RSI 58, no divergence, ADX 22 (ranging)
- **Confidence**: 7.5/10
- **exec_id**: `msft-1707532801`
```

### 3. Guardian Alerts

**Trigger:** Alert system detects threshold breach

**Action:** Logs to daily note

**Example:**
```markdown
## 15:45 - MSFT Alert ⚠️
- **Severity**: WARNING
- **Triggered by**: position-health-monitor
- **Message**: P&L at -$105 (stop: -$100)
```

### 4. Position Close (`/closed` skill)

**Trigger:** User calls `/closed` skill

**Action:** Updates position note

**Appends to:** `Positions/{SYMBOL}_{EXPIRATION}.md`

**Example:**
```markdown
## Final Outcome 💰
- **Exit Date**: 2026-02-20
- **Exit Premium**: $1.25
- **Realized P&L**: -$125.00 (-50%)
- **Days Held**: 7
- **Exit Reason**: Stop loss triggered

**Status**: CLOSED
```

## Vault Structure

```
TradingVault/
├── Positions/              # Individual position notes
│   ├── MSFT_20260220.md
│   ├── AAPL_20260320.md
│   └── ...
├── Daily Notes/            # Daily journal (auto-created)
│   ├── 2026-02-13.md
│   ├── 2026-02-14.md
│   └── ...
├── Guardian Battles/       # Guardian skill records
│   └── MSFT_20260220_Battle.md
├── Symbols/                # Stock research
│   ├── MSFT.md
│   └── AAPL.md
├── Strategies/             # Strategy templates
│   ├── Iron Condor.md
│   └── Covered Call.md
├── Templates/              # Note templates
│   ├── position-entry.md
│   ├── daily-summary.md
│   └── guardian-battle.md
└── README.md
```

## Obsidian Features Used

### 1. Daily Notes Plugin

**Config:** `.obsidian/daily-notes.json`

```json
{
  "folder": "Daily Notes",
  "format": "YYYY-MM-DD",
  "template": "Templates/daily-summary.md"
}
```

**Usage:** Cmd+D opens today's note

### 2. Obsidian URI

**Protocol:** `obsidian://`

**Actions:**
- `new` - Create note
- `daily` - Open/create daily note

**Example:**
```bash
obsidian://daily?vault=TradingVault&content=New+alert
```

### 3. Frontmatter (YAML)

Position notes use YAML frontmatter for metadata:

```yaml
---
symbol: MSFT
expiration: 2026-02-20
strategy: covered_call
exec_id: msft-1707532800
status: ACTIVE
tags: [position, MSFT, covered_call]
---
```

### 4. Dataview Queries (Optional)

Install Dataview plugin for advanced queries:

**Active Positions:**
```dataview
TABLE entry_premium, status, strategy
FROM "Positions"
WHERE status = "ACTIVE"
SORT entry_date DESC
```

**Recent Alerts:**
```dataview
LIST
FROM "Daily Notes"
WHERE contains(file.outlinks, "Alert")
SORT file.name DESC
LIMIT 10
```

**P&L Summary:**
```dataview
TABLE realized_pnl, days_held, exit_reason
FROM "Positions"
WHERE status = "CLOSED"
SORT exit_date DESC
LIMIT 20
```

### 5. Graph View

Visualize position relationships:
- Symbol → Positions
- Positions → Guardian Battles
- Positions → Daily Notes
- Agents → Verdicts

## Code Integration

### TypeScript Client

**File:** `/src/storage/obsidian-client.ts`

**Usage:**

```typescript
import { getObsidianClient } from "./storage/obsidian-client";

const obsidian = getObsidianClient();

// Create position note
await obsidian.createPositionNote({
  symbol: "MSFT",
  expiration: "2026-02-20",
  strategy: "covered_call",
  execId: "msft-1707532800",
  entryPremium: 2.50,
  strikes: { shortCall: 420 },
  guardianVerdict: {
    winnerAgent: "theta-decay",
    confidence: 8.5,
    reasoning: "IV rank ideal for premium selling",
  },
  entryDate: new Date().toISOString(),
});

// Log agent verdict
await obsidian.logAgentVerdict({
  symbol: "MSFT",
  agentName: "technical-scout",
  status: "HOLD",
  keyFinding: "RSI 58, no divergence",
  confidence: 7.5,
  execId: "msft-1707532801",
  timestamp: new Date().toLocaleTimeString(),
});

// Log alert
await obsidian.logAlert({
  symbol: "MSFT",
  severity: "warning",
  message: "P&L at -$105",
  triggeredBy: "position-health-monitor",
  timestamp: new Date().toLocaleTimeString(),
});

// Update outcome
await obsidian.updatePositionOutcome({
  symbol: "MSFT",
  expiration: "2026-02-20",
  exitPremium: 1.25,
  realizedPnL: -125.00,
  exitReason: "Stop loss triggered",
  daysHeld: 7,
  exitDate: new Date().toISOString(),
});
```

### Error Handling

Obsidian writes **never block operations**:

```typescript
try {
  await executeURI(uri);
} catch (error) {
  console.error("Obsidian write failed:", error);
  // Don't throw - continue with Convex/Supabase writes
}
```

## Benefits

### 1. Full-Text Search

Search across all trades, verdicts, and alerts:
- `"stop loss"` - Find all stop loss exits
- `"technical-scout HOLD"` - Find scout's hold recommendations
- `tag:#MSFT` - Find all MSFT positions

### 2. Graph View

Visualize:
- Position relationships
- Agent collaboration patterns
- Symbol correlations

### 3. Mobile Access

With Obsidian Sync ($10/mo):
- Review positions on mobile
- Add manual notes while traveling
- Cross-device synchronization

### 4. Template Consistency

Templates ensure consistent structure:
- Position notes always have same sections
- Daily notes follow same format
- Easy to parse and analyze

### 5. Version Control

With Obsidian Git plugin:
- Auto-commit every hour
- Full history of all changes
- Rollback if needed

## Recommended Plugins

### Core Plugins (Built-in)
- ✅ Daily notes
- ✅ Templates
- ✅ Graph view
- ✅ Search
- ✅ Backlinks

### Community Plugins
- **Dataview** - SQL-like queries on notes
- **Obsidian Git** - Auto-commit to GitHub
- **Calendar** - Visual calendar with daily notes
- **Advanced Tables** - Better table editing

## Troubleshooting

### Obsidian not opening notes

**Check:**
1. Obsidian is installed and running
2. TradingVault vault is open
3. Environment variables set correctly

**Test:**
```bash
open "obsidian://daily?vault=TradingVault&content=Test"
```

### Notes not created

**Check:**
1. Vault path exists: `~/Documents/TradingVault`
2. Daily Notes plugin enabled in Obsidian
3. Template files exist in `Templates/`

### Permission errors

**macOS:**
```bash
# Grant terminal access to Documents folder
System Preferences → Security & Privacy → Full Disk Access
```

## Best Practices

### 1. Don't Manually Edit Automated Sections

Sections marked with `<!-- ... -->` are auto-updated:

```markdown
## Agent Updates
<!-- Agent verdicts will be appended here -->
```

Manual edits will be overwritten!

### 2. Use Links Liberally

Link related notes:
- `[[MSFT]]` - Link to symbol research
- `[[2026-02-20]]` - Link to expiration cycle
- `[[Guardian Battles]]` - Link to all battles

### 3. Add Manual Notes

Each position note has a `## Notes` section for manual observations.

### 4. Review Daily Notes Weekly

Daily notes accumulate quickly. Review weekly to:
- Identify patterns in agent verdicts
- Learn from alerts
- Improve strategies

### 5. Backup Regularly

Use Obsidian Sync or Git plugin for automatic backups.

## Future Enhancements

### Phase 2 (Optional)
- **Obsidian Publish** - Share analysis publicly
- **Excalidraw** - Visual trade diagrams
- **Charts** - Embed P&L charts
- **AI Copilot** - Query vault with natural language

## Support

- **Obsidian Docs**: https://help.obsidian.md
- **Obsidian Forum**: https://forum.obsidian.md
- **Integration Code**: `/src/storage/obsidian-client.ts`
- **Templates**: `/obsidian-templates/`

---

**Status:** ✅ Production-ready
**Dependencies:** Obsidian app installed
**Testing:** `bun run scripts/test-obsidian.ts`
