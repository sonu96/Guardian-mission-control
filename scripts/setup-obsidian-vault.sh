#!/bin/bash
# Setup Obsidian TradingVault for Guardian Mission Control
# Run this script once to initialize the vault structure

VAULT_NAME="TradingVault"
VAULT_PATH="${HOME}/Documents/${VAULT_NAME}"

echo "🗂️  Setting up Obsidian TradingVault..."

# Create vault directory
mkdir -p "${VAULT_PATH}"

# Create folder structure
mkdir -p "${VAULT_PATH}/Positions"
mkdir -p "${VAULT_PATH}/Daily Notes"
mkdir -p "${VAULT_PATH}/Guardian Battles"
mkdir -p "${VAULT_PATH}/Templates"
mkdir -p "${VAULT_PATH}/Symbols"
mkdir -p "${VAULT_PATH}/Strategies"
mkdir -p "${VAULT_PATH}/.obsidian"

echo "✅ Created vault structure at ${VAULT_PATH}"

# Copy templates
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_SRC="${SCRIPT_DIR}/../obsidian-templates"

if [ -d "${TEMPLATES_SRC}" ]; then
  cp "${TEMPLATES_SRC}"/*.md "${VAULT_PATH}/Templates/"
  echo "✅ Copied note templates"
fi

# Create Obsidian config
cat > "${VAULT_PATH}/.obsidian/app.json" << 'EOF'
{
  "newFileLocation": "folder",
  "newFileFolderPath": "Daily Notes",
  "attachmentFolderPath": "Attachments",
  "alwaysUpdateLinks": true,
  "useMarkdownLinks": false,
  "showFrontmatter": true,
  "defaultViewMode": "source",
  "livePreview": true
}
EOF

echo "✅ Created Obsidian config"

# Create daily notes plugin config
cat > "${VAULT_PATH}/.obsidian/daily-notes.json" << 'EOF'
{
  "folder": "Daily Notes",
  "format": "YYYY-MM-DD",
  "template": "Templates/daily-summary.md"
}
EOF

echo "✅ Configured Daily Notes plugin"

# Create hotkeys config
cat > "${VAULT_PATH}/.obsidian/hotkeys.json" << 'EOF'
{
  "daily-notes": [
    {
      "modifiers": ["Mod"],
      "key": "D"
    }
  ]
}
EOF

echo "✅ Configured hotkeys"

# Create community plugins manifest
mkdir -p "${VAULT_PATH}/.obsidian/plugins"
cat > "${VAULT_PATH}/.obsidian/community-plugins.json" << 'EOF'
[
  "dataview",
  "obsidian-git"
]
EOF

echo "✅ Enabled recommended plugins"

# Create README
cat > "${VAULT_PATH}/README.md" << 'EOF'
# Trading Vault - Guardian Mission Control

This vault contains your human-readable trading journal alongside the Mission Control dashboard.

## Structure

- **Positions/** - Individual position notes (one per trade)
- **Daily Notes/** - Daily trading journal (market context, alerts, P&L)
- **Guardian Battles/** - Guardian skill analysis records
- **Symbols/** - Stock-specific research and analysis
- **Strategies/** - Strategy templates and playbooks
- **Templates/** - Note templates

## Usage

### Position Entry (Automated)
When you call `/entered`, a position note is automatically created:
```
Positions/MSFT_20260220.md
```

### Agent Verdicts (Automated)
Agent verdicts are appended to today's daily note:
```
Daily Notes/2026-02-13.md
```

### Manual Notes
- Use Cmd+D to open today's daily note
- Link positions: [[MSFT_20260220]]
- Tag symbols: #MSFT
- Link battles: [[Guardian Battles/MSFT_20260220_Battle]]

## Queries with Dataview

### Active Positions
```dataview
TABLE entry_premium, status, strategy
FROM "Positions"
WHERE status = "ACTIVE"
SORT entry_date DESC
```

### Recent Alerts
```dataview
TABLE severity, message
FROM "Daily Notes"
WHERE contains(file.outlinks, "Alert")
SORT file.name DESC
LIMIT 10
```

### P&L Summary
```dataview
TABLE realized_pnl, days_held, exit_reason
FROM "Positions"
WHERE status = "CLOSED"
SORT exit_date DESC
LIMIT 20
```

## Integration

This vault is automatically updated by:
- Guardian Mission Control (position management)
- 8 monitoring agents (verdicts and alerts)
- /entered, /closed skills (trade lifecycle)

Do NOT manually edit automated sections unless you know what you're doing!

## Backup

Consider enabling Obsidian Sync or Git plugin for automatic backups.
EOF

echo "✅ Created README"

# Create example position note
cat > "${VAULT_PATH}/Positions/Example_Position.md" << 'EOF'
---
symbol: EXAMPLE
expiration: 2026-03-20
strategy: iron_condor
exec_id: example-1234567890
status: ACTIVE
entry_date: 2026-02-13
entry_premium: 250.00
tags: [position, EXAMPLE, iron_condor]
---

# EXAMPLE Iron Condor - 2026-03-20

This is an example position note. Real notes are created automatically by `/entered`.

Delete this file once you have real positions.
EOF

echo "✅ Created example note"

# Print success message
cat << EOF

╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║  ✅ TradingVault Setup Complete!                            ║
║                                                              ║
║  Location: ${VAULT_PATH}
║                                                              ║
║  Next Steps:                                                 ║
║  1. Open Obsidian and click "Open folder as vault"          ║
║  2. Select: ${VAULT_PATH}
║  3. Enable Daily Notes plugin (should auto-enable)           ║
║  4. Install Dataview plugin (optional, for queries)          ║
║  5. Add to .env.local:                                       ║
║     OBSIDIAN_VAULT_NAME=TradingVault                         ║
║     OBSIDIAN_VAULT_PATH=${VAULT_PATH}
║                                                              ║
║  Test Integration:                                           ║
║  bun run scripts/test-obsidian.ts                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

EOF
