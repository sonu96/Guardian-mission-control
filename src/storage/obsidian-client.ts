/**
 * Obsidian CLI Integration
 * Creates human-readable trading journals alongside Mission Control dashboard
 *
 * Purpose:
 * - Dashboard = Real-time monitoring
 * - Obsidian = Historical journal + full-text search
 *
 * Integration Points:
 * 1. Position Health agent auto-discovery → Create position note
 * 2. Agent verdicts → Append to daily note
 * 3. Position Health agent (position gone) → Update position note with outcome
 * 4. Guardian alerts → Log to daily note
 */

import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

export interface ObsidianConfig {
  vaultName: string; // e.g., "TradingVault"
  vaultPath?: string; // Optional: full path to vault
}

export interface PositionNoteData {
  symbol: string;
  expiration: string;
  strategy: string;
  execId: string;
  entryPremium: number;
  strikes: {
    longCall?: number;
    shortCall?: number;
    longPut?: number;
    shortPut?: number;
  };
  guardianVerdict: {
    winnerAgent: string;
    confidence: number;
    reasoning: string;
  };
  entryDate: string;
}

export interface AgentVerdictData {
  symbol: string;
  agentName: string;
  status: "HOLD" | "ADJUST" | "EXIT";
  keyFinding: string;
  confidence: number;
  execId: string;
  timestamp: string;
}

export interface PositionOutcomeData {
  symbol: string;
  expiration: string;
  exitPremium: number;
  realizedPnL: number;
  exitReason: string;
  daysHeld: number;
  exitDate: string;
}

export class ObsidianClient {
  private config: ObsidianConfig;

  constructor(config: ObsidianConfig) {
    this.config = config;
  }

  /**
   * Create position entry note
   * Called by Position Health agent when NEW position is auto-discovered
   */
  async createPositionNote(data: PositionNoteData): Promise<void> {
    const noteName = `${data.symbol}_${data.expiration.replace(/-/g, "")}`;
    const content = this.formatPositionNote(data);

    await this.createNote({
      vault: this.config.vaultName,
      name: `Positions/${noteName}`,
      content,
    });
  }

  /**
   * Append agent verdict to daily note
   * Called by each agent after analysis
   */
  async logAgentVerdict(data: AgentVerdictData): Promise<void> {
    const content = this.formatAgentVerdict(data);

    await this.appendToDaily({
      vault: this.config.vaultName,
      content,
    });
  }

  /**
   * Update position note with outcome
   * Called by Position Health agent when position is no longer detected in Webull
   */
  async updatePositionOutcome(data: PositionOutcomeData): Promise<void> {
    const noteName = `${data.symbol}_${data.expiration.replace(/-/g, "")}`;
    const content = this.formatOutcome(data);

    await this.appendToNote({
      vault: this.config.vaultName,
      name: `Positions/${noteName}`,
      content,
    });
  }

  /**
   * Log Guardian alert to daily note
   * Called by alert system
   */
  async logAlert(data: {
    symbol: string;
    severity: "info" | "warning" | "critical";
    message: string;
    triggeredBy: string;
    timestamp: string;
  }): Promise<void> {
    const severityEmoji = {
      info: "ℹ️",
      warning: "⚠️",
      critical: "🚨",
    }[data.severity];

    const content = `
## ${data.timestamp} - ${data.symbol} Alert ${severityEmoji}
- **Severity**: ${data.severity.toUpperCase()}
- **Triggered by**: ${data.triggeredBy}
- **Message**: ${data.message}

---
`;

    await this.appendToDaily({
      vault: this.config.vaultName,
      content,
    });
  }

  // ===== PRIVATE HELPERS =====

  private formatPositionNote(data: PositionNoteData): string {
    const strikesSummary = this.formatStrikes(data.strikes);

    return `---
symbol: ${data.symbol}
expiration: ${data.expiration}
strategy: ${data.strategy}
exec_id: ${data.execId}
status: ACTIVE
entry_date: ${data.entryDate}
entry_premium: ${data.entryPremium}
---

# ${data.symbol} ${data.strategy} - ${data.expiration}

## Entry Details
- **Date**: ${data.entryDate}
- **Strategy**: ${data.strategy}
- **Strikes**: ${strikesSummary}
- **Entry Premium**: $${data.entryPremium.toFixed(2)}
- **exec_id**: \`${data.execId}\`

## Guardian Verdict
- **Winner**: ${data.guardianVerdict.winnerAgent}
- **Confidence**: ${data.guardianVerdict.confidence}/10
- **Reasoning**: ${data.guardianVerdict.reasoning}

## Agent Updates
<!-- Agent verdicts will be appended here -->

## Position Outcome
<!-- Outcome will be added when position closes -->
`;
  }

  private formatAgentVerdict(data: AgentVerdictData): string {
    const statusEmoji = {
      HOLD: "✅",
      ADJUST: "🔧",
      EXIT: "🚪",
    }[data.status];

    return `
## ${data.timestamp} - ${data.symbol} ${statusEmoji}
- **Agent**: ${data.agentName}
- **Status**: ${data.status}
- **Finding**: ${data.keyFinding}
- **Confidence**: ${data.confidence}/10
- **exec_id**: \`${data.execId}\`

---
`;
  }

  private formatOutcome(data: PositionOutcomeData): string {
    const pnlEmoji = data.realizedPnL >= 0 ? "💰" : "📉";
    const pnlPercent = ((data.realizedPnL / (data.exitPremium - data.realizedPnL)) * 100).toFixed(2);

    return `
---

## Final Outcome ${pnlEmoji}
- **Exit Date**: ${data.exitDate}
- **Exit Premium**: $${data.exitPremium.toFixed(2)}
- **Realized P&L**: $${data.realizedPnL.toFixed(2)} (${pnlPercent}%)
- **Days Held**: ${data.daysHeld}
- **Exit Reason**: ${data.exitReason}

**Status**: CLOSED
`;
  }

  private formatStrikes(strikes: PositionNoteData["strikes"]): string {
    const parts: string[] = [];

    if (strikes.longCall) parts.push(`Long Call ${strikes.longCall}`);
    if (strikes.shortCall) parts.push(`Short Call ${strikes.shortCall}`);
    if (strikes.longPut) parts.push(`Long Put ${strikes.longPut}`);
    if (strikes.shortPut) parts.push(`Short Put ${strikes.shortPut}`);

    return parts.join(" / ");
  }

  // ===== OBSIDIAN URI OPERATIONS =====

  /**
   * Create new note via Obsidian URI
   */
  private async createNote(params: {
    vault: string;
    name: string;
    content: string;
  }): Promise<void> {
    const uri = this.buildObsidianURI("new", {
      vault: params.vault,
      name: params.name,
      content: params.content,
      silent: "true",
    });

    await this.executeURI(uri);
  }

  /**
   * Append to existing note via Obsidian URI
   */
  private async appendToNote(params: {
    vault: string;
    name: string;
    content: string;
  }): Promise<void> {
    const uri = this.buildObsidianURI("new", {
      vault: params.vault,
      name: params.name,
      content: params.content,
      append: "true",
      silent: "true",
    });

    await this.executeURI(uri);
  }

  /**
   * Append to daily note via Obsidian URI
   */
  private async appendToDaily(params: {
    vault: string;
    content: string;
  }): Promise<void> {
    const uri = this.buildObsidianURI("new", {
      vault: params.vault,
      content: params.content,
      append: "true",
      silent: "true",
    });

    // Use daily note action
    const dailyUri = uri.replace("obsidian://new", "obsidian://daily");

    await this.executeURI(dailyUri);
  }

  /**
   * Build Obsidian URI with proper encoding
   */
  private buildObsidianURI(
    action: string,
    params: Record<string, string>
  ): string {
    const encodedParams = Object.entries(params)
      .map(([key, value]) => {
        const encodedValue = encodeURIComponent(value)
          .replace(/%2F/g, "/"); // Don't encode forward slashes
        return `${key}=${encodedValue}`;
      })
      .join("&");

    return `obsidian://${action}?${encodedParams}`;
  }

  /**
   * Execute Obsidian URI via system open command
   */
  private async executeURI(uri: string): Promise<void> {
    try {
      // Platform-specific open command
      const command = process.platform === "darwin"
        ? `open "${uri}"`
        : process.platform === "win32"
        ? `start "" "${uri}"`
        : `xdg-open "${uri}"`;

      await execAsync(command);
    } catch (error) {
      console.error("Obsidian URI execution failed:", error);
      // Don't throw - we don't want to block operations if Obsidian is closed
    }
  }
}

// ===== SINGLETON INSTANCE =====

let obsidianInstance: ObsidianClient | null = null;

export function getObsidianClient(): ObsidianClient {
  if (!obsidianInstance) {
    const config: ObsidianConfig = {
      vaultName: process.env.OBSIDIAN_VAULT_NAME || "TradingVault",
      vaultPath: process.env.OBSIDIAN_VAULT_PATH,
    };

    obsidianInstance = new ObsidianClient(config);
  }

  return obsidianInstance;
}
