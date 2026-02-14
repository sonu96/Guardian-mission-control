/**
 * Obsidian CLI Integration Utilities
 *
 * Helper functions for logging to Obsidian vault from Guardian Mission Control agents
 */

import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

interface ObsidianConfig {
  vault: string;
  vaultPath: string;
}

const config: ObsidianConfig = {
  vault: process.env.OBSIDIAN_VAULT || 'TradingVault',
  vaultPath: process.env.OBSIDIAN_VAULT_PATH || '~/Documents/ObsidianVaults/TradingVault',
};

/**
 * Escape content for Obsidian CLI (handle newlines and quotes)
 */
function escapeContent(content: string): string {
  return content
    .replace(/\n/g, '\\n')
    .replace(/\t/g, '\\t')
    .replace(/"/g, '\\"');
}

/**
 * Log agent verdict to daily note
 */
export async function logAgentVerdict(
  symbol: string,
  agentName: string,
  verdict: {
    action: string;
    summary: string;
  },
  execId?: string
): Promise<void> {
  const timestamp = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  });

  const content = `
## ${timestamp} - ${symbol} Alert
- **Status**: ${verdict.action}
- **${agentName}**: ${verdict.summary}
${execId ? `- **exec_id**: ${execId}` : ''}
`;

  await appendToDaily(content);
}

/**
 * Append content to today's daily note
 */
export async function appendToDaily(content: string): Promise<void> {
  const escapedContent = escapeContent(content);

  const command = `obsidian daily:append vault="${config.vault}" content="${escapedContent}"`;

  try {
    await execAsync(command);
  } catch (error) {
    console.error('Failed to append to Obsidian daily note:', error);
    // Don't throw - logging failure shouldn't break agent
  }
}

/**
 * Create position entry note
 */
export async function createPositionNote(
  symbol: string,
  expiration: string,
  strategy: string,
  details: {
    entryPrice: number;
    contracts: number;
    strikes?: {
      shortPut?: number;
      longPut?: number;
      shortCall?: number;
      longCall?: number;
    };
    underlyingPrice: number;
    ivRank?: number;
    gexRegime?: string;
    dte: number;
    maxLoss: number;
    maxGain: number;
    breakEven?: number[];
    guardianBattle?: {
      winningAgent: string;
      confidence: number;
      battleId: string;
    };
  }
): Promise<string> {
  const noteName = `Positions/${symbol}-${expiration}-${strategy.replace(/_/g, '-').toUpperCase()}`;

  // Build position details
  let positionContent = `---
created: ${new Date().toISOString()}
type: position
symbol: ${symbol}
strategy: ${strategy}
status: ENTERED
tags: [${strategy.replace(/_/g, '-')}]
---

# ${symbol} - ${strategy.replace(/_/g, ' ').toUpperCase()}

## Position Details

- **Symbol**: ${symbol}
- **Strategy**: ${strategy.replace(/_/g, ' ')}
- **Expiration**: ${expiration}
- **Entry Date**: ${new Date().toLocaleDateString()}
- **Entry Price**: $${details.entryPrice.toFixed(2)}
- **Contracts**: ${details.contracts}

## Strikes
`;

  if (details.strikes) {
    if (details.strikes.shortPut) positionContent += `- **Short Put**: $${details.strikes.shortPut}\n`;
    if (details.strikes.longPut) positionContent += `- **Long Put**: $${details.strikes.longPut}\n`;
    if (details.strikes.shortCall) positionContent += `- **Short Call**: $${details.strikes.shortCall}\n`;
    if (details.strikes.longCall) positionContent += `- **Long Call**: $${details.strikes.longCall}\n`;
  }

  positionContent += `
## Entry Analysis

### Market Context
- **Underlying Price**: $${details.underlyingPrice.toFixed(2)}
${details.ivRank ? `- **IV Rank**: ${details.ivRank}%` : ''}
${details.gexRegime ? `- **GEX Regime**: ${details.gexRegime}` : ''}
- **Days to Expiration**: ${details.dte}

### Risk Metrics
- **Max Loss**: $${details.maxLoss.toFixed(2)}
- **Max Gain**: $${details.maxGain.toFixed(2)}
${details.breakEven ? `- **Break-Even**: $${details.breakEven.join(', $')}` : ''}
- **P&L Ratio**: ${(details.maxGain / Math.abs(details.maxLoss)).toFixed(2)}

${details.guardianBattle ? `
### Guardian Battle Result
- **Winning Agent**: ${details.guardianBattle.winningAgent}
- **Confidence**: ${details.guardianBattle.confidence}/10
- **Battle Link**: [[Agents/Guardian-Battle-${symbol}-${new Date().toISOString().split('T')[0]}]]
` : ''}

## Monitoring

### Agent Alerts

<!-- Agents append here via Obsidian CLI -->

## Exit Plan

- [ ] Take profit at 75% max gain
- [ ] Stop loss at 50% max loss
- [ ] Adjust if underlying reaches short strikes
- [ ] Close 3-5 days before expiration

## Notes

`;

  const escapedContent = escapeContent(positionContent);
  const command = `obsidian create vault="${config.vault}" name="${noteName}" content="${escapedContent}" silent`;

  try {
    await execAsync(command);
    return noteName;
  } catch (error) {
    console.error('Failed to create Obsidian position note:', error);
    throw error;
  }
}

/**
 * Append position update to existing note
 */
export async function updatePositionNote(
  positionNoteName: string,
  content: string
): Promise<void> {
  const escapedContent = escapeContent(content);
  const command = `obsidian append vault="${config.vault}" file="${positionNoteName}.md" content="${escapedContent}"`;

  try {
    await execAsync(command);
  } catch (error) {
    console.error('Failed to update Obsidian position note:', error);
  }
}

/**
 * Close position note with outcome
 */
export async function closePositionNote(
  positionNoteName: string,
  outcome: {
    closeDate: Date;
    exitPremium: number;
    realizedPnL: number;
    daysHeld: number;
    result: 'Win' | 'Loss' | 'Breakeven';
  }
): Promise<void> {
  const content = `
## Outcome

- **Closed**: ${outcome.closeDate.toLocaleDateString()}
- **Exit Premium**: $${outcome.exitPremium.toFixed(2)}
- **Realized P&L**: ${outcome.realizedPnL >= 0 ? '+' : ''}$${outcome.realizedPnL.toFixed(2)} (${((outcome.realizedPnL / outcome.exitPremium) * 100).toFixed(1)}%)
- **Days Held**: ${outcome.daysHeld}
- **Result**: ${outcome.result === 'Win' ? '✅' : outcome.result === 'Loss' ? '❌' : '➖'} ${outcome.result}
`;

  await updatePositionNote(positionNoteName, content);
}

/**
 * Create Guardian battle analysis note
 */
export async function createBattleNote(
  symbol: string,
  expiration: string,
  battleData: {
    execId: string;
    underlyingPrice: number;
    ivRank: number;
    gexRegime: string;
    proposals: Array<{
      agent: string;
      strategy: string;
      confidence: number;
      keyPoints: string[];
    }>;
    winner: {
      agent: string;
      score: number;
      rationale: string;
    };
  }
): Promise<string> {
  const noteName = `Agents/Guardian-Battle-${symbol}-${new Date().toISOString().split('T')[0]}`;

  let content = `---
created: ${new Date().toISOString()}
type: guardian-battle
symbol: ${symbol}
outcome: pending
tags: [guardian, analysis, ${symbol.toLowerCase()}]
---

# Guardian Battle - ${symbol}

## Battle Context

- **Symbol**: ${symbol}
- **Expiration**: ${expiration}
- **Analysis Date**: ${new Date().toLocaleString()}
- **exec_id**: ${battleData.execId}

## Market Snapshot

- **Underlying Price**: $${battleData.underlyingPrice.toFixed(2)}
- **IV Rank**: ${battleData.ivRank}%
- **GEX Regime**: ${battleData.gexRegime}

## Agent Proposals

`;

  battleData.proposals.forEach((proposal, i) => {
    content += `
### ${i + 1}. ${proposal.agent}
- **Strategy**: ${proposal.strategy}
- **Confidence**: ${proposal.confidence}/10
- **Key Points**:
${proposal.keyPoints.map(point => `  - ${point}`).join('\n')}
`;
  });

  content += `
## Judge Verdict

### Winner
- **Agent**: ${battleData.winner.agent}
- **Score**: ${battleData.winner.score}/10

### Rationale
${battleData.winner.rationale}

## User Decision

- [ ] Approved
- [ ] Denied
- [ ] Modified

**Notes**:

## Outcome

<!-- Update after position closed -->

---

**Links**:
- Position Note: [[]]
- exec_id for replay: ${battleData.execId}
`;

  const escapedContent = escapeContent(content);
  const command = `obsidian create vault="${config.vault}" name="${noteName}" content="${escapedContent}" silent`;

  try {
    await execAsync(command);
    return noteName;
  } catch (error) {
    console.error('Failed to create Guardian battle note:', error);
    throw error;
  }
}

/**
 * Search vault
 */
export async function searchVault(query: string): Promise<string> {
  const command = `obsidian search vault="${config.vault}" query="${query}"`;

  try {
    const { stdout } = await execAsync(command);
    return stdout;
  } catch (error) {
    console.error('Failed to search Obsidian vault:', error);
    return '';
  }
}

/**
 * Test Obsidian CLI availability
 */
export async function testObsidianCLI(): Promise<boolean> {
  try {
    await execAsync('which obsidian');
    return true;
  } catch {
    console.warn('Obsidian CLI not found. Install: npm install -g @obsidian/cli');
    return false;
  }
}

/**
 * Initialize vault (create if doesn't exist)
 */
export async function initializeVault(): Promise<void> {
  try {
    // Test if vault exists by trying to open daily note
    await execAsync(`obsidian daily vault="${config.vault}"`);
    console.log('✅ Obsidian vault initialized:', config.vault);
  } catch (error) {
    console.error('❌ Obsidian vault not found:', config.vault);
    console.log('Create vault at:', config.vaultPath);
    throw new Error(`Obsidian vault "${config.vault}" not found. See OBSIDIAN_SETUP.md`);
  }
}
