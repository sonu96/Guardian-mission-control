# Obsidian CLI Integration for Guardian Mission Control

## Overview

This integration creates a human-readable trading journal in Obsidian alongside the Mission Control dashboard. The vault provides:

- **Real-time Dashboard**: Mission Control (Convex)
- **Historical Journal**: Obsidian Vault (markdown notes)

## Prerequisites

1. **Install Obsidian**: https://obsidian.md/download
2. **Install Obsidian CLI**:
   ```bash
   # macOS/Linux
   npm install -g @obsidian/cli

   # Or install from Obsidian settings (requires Obsidian v1.5.0+)
   ```
3. **Create Vault**: Named "TradingVault"

## Vault Setup

### 1. Create Vault Directory

```bash
mkdir -p ~/Documents/ObsidianVaults/TradingVault
```

### 2. Initialize Vault Structure

```bash
cd ~/Documents/ObsidianVaults/TradingVault

# Create directories
mkdir -p Positions
mkdir -p Daily
mkdir -p Templates
mkdir -p Agents
mkdir -p Outcomes

# Create .obsidian config
mkdir -p .obsidian
```

### 3. Copy Templates

Copy template files from this directory to your vault:

```bash
cp /Users/abhisonu/Documents/GitHub/Guardian-mission-control/obsidian/templates/* ~/Documents/ObsidianVaults/TradingVault/Templates/
```

### 4. Configure Obsidian

Open Obsidian and:
1. Open vault: `~/Documents/ObsidianVaults/TradingVault`
2. Settings > Core plugins > Enable "Templates"
3. Settings > Templates > Template folder: `Templates`
4. Settings > Core plugins > Enable "Daily notes"
5. Settings > Daily notes > Daily note folder: `Daily`
6. Settings > Daily notes > Template: `Templates/Daily Note Template.md`

## Environment Variables

Add to Guardian Mission Control `.env.local`:

```bash
# Obsidian CLI Integration
OBSIDIAN_VAULT=TradingVault
OBSIDIAN_VAULT_PATH=~/Documents/ObsidianVaults/TradingVault
```

## Usage Patterns

### 1. Position Entry (via /entered skill)

When a position is entered, create a position note:

```bash
obsidian create \
  vault=TradingVault \
  name="Positions/AAPL-2026-02-20-IC" \
  template="Position Entry" \
  silent
```

### 2. Agent Verdict (during monitoring)

Append agent analysis to daily note:

```bash
obsidian daily:append \
  vault=TradingVault \
  content="
## 14:32 - AAPL Alert
- **Status**: HOLD
- **Guardian**: Greeks stable, 76% max profit reached
- **exec_id**: aapl-1708012800
"
```

### 3. Position Close (via /closed skill)

Update position note with outcome:

```bash
# Append outcome section to position note
obsidian append \
  vault=TradingVault \
  file="Positions/AAPL-2026-02-20-IC.md" \
  content="
## Outcome
- **Closed**: 2026-02-15
- **Exit Premium**: \$1.42
- **Realized P&L**: +\$215 (+23.2%)
- **Days Held**: 9
- **Result**: ✅ Win
"
```

### 4. Guardian Battle Result

Create battle analysis note:

```bash
obsidian create \
  vault=TradingVault \
  name="Agents/Guardian-Battle-MSFT-2026-02-13" \
  template="Guardian Battle" \
  silent
```

## File Structure

```
TradingVault/
├── Positions/
│   ├── AAPL-2026-02-20-IC.md
│   ├── NVDA-2026-03-21-BPS.md
│   └── MSFT-2026-02-20-CC.md
├── Daily/
│   ├── 2026-02-13.md
│   ├── 2026-02-14.md
│   └── 2026-02-15.md
├── Agents/
│   ├── Guardian-Battle-MSFT-2026-02-13.md
│   └── Risk-Monitor-AAPL-2026-02-14.md
├── Outcomes/
│   └── 2026-02-Monthly-Review.md
└── Templates/
    ├── Position Entry.md
    ├── Daily Note Template.md
    ├── Guardian Battle.md
    └── Monthly Review.md
```

## Integration Points

### Agent Developer (Task #4)

Add Obsidian calls to each agent's verdict workflow:

```javascript
// In agent monitoring loop
async function logAgentVerdict(symbol, agent, verdict, execId) {
  const timestamp = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  });

  const content = `
## ${timestamp} - ${symbol} Alert
- **Status**: ${verdict.action}
- **${agent}**: ${verdict.summary}
- **exec_id**: ${execId}
`;

  await exec(`obsidian daily:append vault=${process.env.OBSIDIAN_VAULT} content="${content.replace(/\n/g, '\\n')}"`);
}
```

### Infrastructure Engineer (Task #1) - ✅ YOU

Create templates and setup documentation (this file).

### QA/DevOps (Task #6)

Test Obsidian integration:

```bash
# Test daily note creation
obsidian daily vault=TradingVault

# Test append
obsidian daily:append vault=TradingVault content="Test entry"

# Test template-based note creation
obsidian create vault=TradingVault name="Test-Position" template="Position Entry" silent

# Test search
obsidian search vault=TradingVault query="AAPL"

# Test tags
obsidian tags vault=TradingVault counts
```

## Template Variables

Templates support variables that are replaced at creation:

- `{{date}}` - Current date (YYYY-MM-DD)
- `{{time}}` - Current time (HH:MM)
- `{{title}}` - Note title
- Custom variables via CLI parameters

## Benefits

1. **Human-Readable Audit Trail**: Markdown notes, easy to read and search
2. **Full-Text Search**: Find any trade or analysis instantly
3. **Graph View**: Visualize position relationships and patterns
4. **Mobile Access**: Obsidian Sync or iCloud for mobile
5. **Template Consistency**: Standardized note structure
6. **Version Control**: Git-compatible (optional)
7. **Offline Access**: All data local, no internet required

## Advanced Features

### Linking Notes

Use wiki-links to connect notes:

```markdown
This position was based on [[Guardian-Battle-MSFT-2026-02-13]]
```

### Tags for Organization

```markdown
#iron-condor #low-iv #earnings-play
```

### Queries with Dataview Plugin

Install Dataview plugin for advanced queries:

```dataview
TABLE
  realized_pnl as "P&L",
  days_held as "Days"
FROM "Positions"
WHERE result = "Win"
SORT realized_pnl DESC
```

### Daily Summary Automation

Use Templater plugin to auto-generate summaries:

```javascript
// Calculate daily P&L from all position notes
const positions = app.vault.getMarkdownFiles()
  .filter(f => f.path.startsWith('Positions/'))
  .map(f => app.vault.read(f));
```

## Backup Strategy

### Option 1: Git

```bash
cd ~/Documents/ObsidianVaults/TradingVault
git init
git add .
git commit -m "Daily backup"
git push origin main
```

### Option 2: Obsidian Sync

Subscribe to Obsidian Sync ($8/month) for automatic cloud backup.

### Option 3: iCloud/Dropbox

Store vault in iCloud Drive or Dropbox folder.

## Troubleshooting

### Obsidian CLI not found

```bash
# Check installation
which obsidian

# Reinstall if needed
npm install -g @obsidian/cli
```

### Vault not found

```bash
# List available vaults
obsidian vaults

# Verify vault path
ls ~/Documents/ObsidianVaults/TradingVault
```

### Templates not working

1. Check Settings > Templates > Template folder
2. Verify template files exist
3. Ensure file has `.md` extension

### Daily notes not created

1. Enable Daily notes plugin
2. Set daily note folder: `Daily`
3. Set template: `Templates/Daily Note Template.md`

## Security Considerations

- Vault stored locally (not in cloud by default)
- Contains sensitive trading data
- Encrypt vault folder for extra security
- Add `.obsidian/workspace` to `.gitignore` if using git

## Next Steps

1. **Infrastructure Engineer**: Create templates (below)
2. **Agent Developer**: Integrate Obsidian CLI calls
3. **QA/DevOps**: Test all integration points
4. **User**: Configure Obsidian vault and plugins

---

**Status**: Ready for template creation
**Integration**: Parallel with Mission Control dashboard
**Maintenance**: Vault grows ~1MB per month (text only)
