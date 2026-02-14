# Obsidian Integration for Guardian Mission Control

## Quick Start

This integration creates a human-readable trading journal in Obsidian that runs in parallel with the Mission Control dashboard.

### Installation (5 minutes)

1. **Install Obsidian**
   - Download: https://obsidian.md/download
   - Install Obsidian CLI: `npm install -g @obsidian/cli`

2. **Create Vault**
   ```bash
   mkdir -p ~/Documents/ObsidianVaults/TradingVault
   cd ~/Documents/ObsidianVaults/TradingVault
   mkdir -p Positions Daily Templates Agents Outcomes
   ```

3. **Copy Templates**
   ```bash
   cp /Users/abhisonu/Documents/GitHub/Guardian-mission-control/obsidian/templates/* ~/Documents/ObsidianVaults/TradingVault/Templates/
   ```

4. **Configure Environment**
   Add to `.env.local`:
   ```bash
   OBSIDIAN_VAULT=TradingVault
   OBSIDIAN_VAULT_PATH=~/Documents/ObsidianVaults/TradingVault
   ```

5. **Test Integration**
   ```bash
   node scripts/test-obsidian-integration.js
   ```

## File Structure

```
obsidian/
├── README.md                          # This file
├── OBSIDIAN_SETUP.md                  # Complete setup guide
└── templates/
    ├── Position Entry.md              # Created when position entered
    ├── Daily Note Template.md         # Agent alerts append here
    ├── Guardian Battle.md             # Battle analysis notes
    └── Monthly Review.md              # Performance summaries
```

## Usage

### From Agent Code

```typescript
import {
  logAgentVerdict,
  createPositionNote,
  closePositionNote,
  createBattleNote
} from '../utils/obsidian-logger';

// Log agent verdict to daily note
await logAgentVerdict('AAPL', 'Guardian', {
  action: 'HOLD',
  summary: 'Greeks stable, 76% max profit'
}, execId);

// Create position entry
await createPositionNote('AAPL', '2026-02-20', 'iron_condor', {
  entryPrice: 1.85,
  contracts: 5,
  strikes: { shortPut: 170, longPut: 165, shortCall: 185, longCall: 190 },
  underlyingPrice: 175.32,
  dte: 14,
  maxLoss: -500,
  maxGain: 425
});

// Close position with outcome
await closePositionNote('Positions/AAPL-2026-02-20-IC', {
  closeDate: new Date(),
  exitPremium: 1.42,
  realizedPnL: 215,
  daysHeld: 9,
  result: 'Win'
});
```

### From Command Line

```bash
# Append to daily note
obsidian daily:append vault=TradingVault content="## Test Entry"

# Create position note
obsidian create vault=TradingVault name="Positions/TEST" template="Position Entry"

# Search vault
obsidian search vault=TradingVault query="AAPL"
```

## Benefits

- **Human-Readable**: Markdown notes, easy to read and search
- **Full-Text Search**: Find any trade or analysis instantly
- **Graph View**: Visualize position relationships
- **Mobile Access**: Obsidian Sync or iCloud
- **Git-Compatible**: Version control your journal
- **Offline**: All data local, no internet required

## Architecture

```
Guardian Mission Control
├── Real-Time Dashboard (Convex)
│   └── Live P&L, alerts, agent status
│
└── Historical Journal (Obsidian)
    └── Daily notes, position logs, battle analysis
```

Both systems run in parallel:
- **Dashboard**: Real-time monitoring
- **Obsidian**: Long-term audit trail

## Templates

### 1. Position Entry
Created when `/entered` skill is called. Tracks position lifecycle from entry to close.

### 2. Daily Note
Auto-created each day. Agents append verdicts here via `logAgentVerdict()`.

### 3. Guardian Battle
Created for each Guardian battle. Records all agent proposals and judge verdict.

### 4. Monthly Review
Manual template for monthly performance analysis.

## Testing

Run the test script to verify integration:

```bash
node scripts/test-obsidian-integration.js
```

Tests:
1. ✅ CLI installed
2. ✅ Vault accessible
3. ✅ Daily note creation
4. ✅ Content appending
5. ✅ Position note creation
6. ✅ Search functionality
7. ✅ Tag listing

## Troubleshooting

### "Obsidian CLI not found"
```bash
npm install -g @obsidian/cli
which obsidian  # Verify installation
```

### "Vault not found"
```bash
obsidian vaults  # List available vaults
# Verify vault exists at path in OBSIDIAN_VAULT_PATH
```

### Templates not working
1. Open vault in Obsidian
2. Settings > Core plugins > Enable "Templates"
3. Settings > Templates > Template folder: `Templates`

## Documentation

- **Setup Guide**: `OBSIDIAN_SETUP.md` (complete documentation)
- **Code Reference**: `src/utils/obsidian-logger.ts` (TypeScript functions)
- **Testing**: `scripts/test-obsidian-integration.js` (integration tests)

## Integration Status

✅ Infrastructure complete
✅ Templates created
✅ Utility functions ready
✅ Testing script available
⏳ Agent integration (Task #4)
⏳ QA testing (Task #6)

---

**Maintained by**: Infrastructure Engineer
**Last Updated**: 2026-02-13
**Version**: 1.0
