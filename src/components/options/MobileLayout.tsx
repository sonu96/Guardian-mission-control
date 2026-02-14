import React, { useState } from "react";
import { Id } from "../../../convex/_generated/dataModel";
import PositionCard from "./PositionCard";
import PLDashboard from "./PLDashboard";
import AgentStatusPanel from "./AgentStatusPanel";
import AlertSystem from "./AlertSystem";
import {
  IconChartBar,
  IconBell,
  IconWallet,
  IconRobot,
} from "@tabler/icons-react";

interface Position {
  _id: Id<"positions">;
  symbol: string;
  strategy: "iron_condor" | "bull_put_spread" | "bear_call_spread" | "long_call" | "long_put" | "covered_call" | "cash_secured_put";
  entryDate: number;
  expiration: string;
  strikes: {
    longCall?: number;
    shortCall?: number;
    longPut?: number;
    shortPut?: number;
  };
  contracts: number;
  entryPrice: number;
  currentPrice?: number;
  currentPnL?: number;
  currentPnLPercent?: number;
  greeks?: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
  };
  status: "monitoring" | "warning" | "critical" | "closed";
  mcpExecId?: string;
  lastUpdate: number;
  assignedAgentId?: Id<"agents">;
}

interface MobileLayoutProps {
  positions: Position[];
  selectedPositionId?: Id<"positions"> | null;
  onSelectPosition?: (positionId: Id<"positions">) => void;
  getAgentName: (id: string) => string;
  formatRelativeTime: (timestamp: number) => string;
}

type MobileView = "positions" | "alerts" | "portfolio" | "agents";

const MobileLayout: React.FC<MobileLayoutProps> = ({
  positions,
  selectedPositionId,
  onSelectPosition,
  getAgentName,
  formatRelativeTime,
}) => {
  const [currentView, setCurrentView] = useState<MobileView>("positions");
  const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set());

  const toggleExpanded = (positionId: string) => {
    const newExpanded = new Set(expandedPositions);
    if (newExpanded.has(positionId)) {
      newExpanded.delete(positionId);
    } else {
      newExpanded.add(positionId);
    }
    setExpandedPositions(newExpanded);
  };

  // Count unread alerts (mock for now)
  const unreadAlertsCount = 3;

  return (
    <div className="md:hidden flex flex-col h-screen">
      {/* Mobile Content Area */}
      <div className="flex-1 overflow-y-auto pb-16">
        {/* Positions View */}
        {currentView === "positions" && (
          <div className="p-4 space-y-3">
            <h2 className="text-lg font-bold text-foreground">Active Positions</h2>

            {/* Grouped by Status */}
            {["monitoring", "warning", "critical", "closed"].map((status) => {
              const statusPositions = positions.filter((p) => p.status === status);
              if (statusPositions.length === 0) return null;

              return (
                <div key={status} className="space-y-2">
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase">
                    {status} ({statusPositions.length})
                  </h3>
                  {statusPositions.map((position) => {
                    const isExpanded = expandedPositions.has(position._id);

                    return (
                      <div key={position._id} className="space-y-2">
                        {/* Collapsed View */}
                        <div
                          onClick={() => toggleExpanded(position._id)}
                          className="bg-white rounded-lg border border-border p-3 shadow-sm cursor-pointer"
                        >
                          <div className="flex justify-between items-start mb-1">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-bold">{position.symbol}</span>
                              <span className="text-xs text-muted-foreground">
                                {position.strategy.replace(/_/g, " ")}
                              </span>
                            </div>
                            <div className={`text-sm font-bold ${
                              (position.currentPnL || 0) >= 0 ? "text-green-600" : "text-red-600"
                            }`}>
                              {position.currentPnL !== undefined
                                ? `${position.currentPnL >= 0 ? "+" : ""}$${position.currentPnL.toFixed(0)}`
                                : "—"}
                            </div>
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {position.assignedAgentId && getAgentName(position.assignedAgentId as string)}
                            {" • "}
                            {formatRelativeTime(position.lastUpdate)}
                          </div>
                        </div>

                        {/* Expanded View */}
                        {isExpanded && (
                          <div className="bg-white rounded-lg border border-border shadow-sm overflow-hidden">
                            <PositionCard
                              position={position}
                              isSelected={selectedPositionId === position._id}
                              onClick={() => onSelectPosition?.(position._id)}
                              getAgentName={getAgentName}
                              formatRelativeTime={formatRelativeTime}
                              columnId={status}
                              compact={false}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}

        {/* Alerts View */}
        {currentView === "alerts" && (
          <div className="p-4">
            <AlertSystem onViewPosition={onSelectPosition} />
          </div>
        )}

        {/* Portfolio View */}
        {currentView === "portfolio" && (
          <div>
            <PLDashboard positions={positions} />
          </div>
        )}

        {/* Agents View */}
        {currentView === "agents" && (
          <div className="p-4">
            <AgentStatusPanel />
          </div>
        )}
      </div>

      {/* Bottom Tab Bar */}
      <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-border z-50 safe-area-inset-bottom">
        <div className="flex justify-around items-center px-2 py-2">
          <button
            onClick={() => setCurrentView("positions")}
            className={`flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-colors ${
              currentView === "positions"
                ? "bg-[var(--accent-blue)] text-white"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            <IconChartBar size={20} />
            <span className="text-[10px] font-semibold">Positions</span>
          </button>

          <button
            onClick={() => setCurrentView("alerts")}
            className={`flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-colors relative ${
              currentView === "alerts"
                ? "bg-[var(--accent-blue)] text-white"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            <IconBell size={20} />
            <span className="text-[10px] font-semibold">Alerts</span>
            {unreadAlertsCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-bold rounded-full flex items-center justify-center">
                {unreadAlertsCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setCurrentView("portfolio")}
            className={`flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-colors ${
              currentView === "portfolio"
                ? "bg-[var(--accent-blue)] text-white"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            <IconWallet size={20} />
            <span className="text-[10px] font-semibold">Portfolio</span>
          </button>

          <button
            onClick={() => setCurrentView("agents")}
            className={`flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-colors ${
              currentView === "agents"
                ? "bg-[var(--accent-blue)] text-white"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            <IconRobot size={20} />
            <span className="text-[10px] font-semibold">Agents</span>
          </button>
        </div>
      </nav>
    </div>
  );
};

export default MobileLayout;
