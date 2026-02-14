import React, { useState, useEffect } from "react";
import { Id } from "../../../convex/_generated/dataModel";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";

interface AgentHeartbeat {
  _id: Id<"agentHeartbeats">;
  agentId: Id<"agents">;
  frequency: "5min" | "15min" | "1hour" | "4hour" | "daily";
  lastRun?: number;
  nextRun?: number;
  assignedPositions: number;
  alertsToday: number;
  avgRunTime?: number;
  apiCallsToday?: number;
}

interface Agent {
  _id: Id<"agents">;
  name: string;
  status: "active" | "idle" | "blocked" | "error";
}

interface AgentStatusPanelProps {
  className?: string;
}

const AgentStatusPanel: React.FC<AgentStatusPanelProps> = ({ className = "" }) => {
  const mockHeartbeats: AgentHeartbeat[] = [
    {
      _id: "1" as Id<"agentHeartbeats">,
      agentId: "a1" as Id<"agents">,
      frequency: "5min",
      lastRun: Date.now() - 27000,
      nextRun: Date.now() + 120000,
      assignedPositions: 7,
      alertsToday: 3,
      avgRunTime: 8200,
      apiCallsToday: 142,
    },
    {
      _id: "2" as Id<"agentHeartbeats">,
      agentId: "a2" as Id<"agents">,
      frequency: "15min",
      lastRun: Date.now() - 180000,
      nextRun: Date.now() + 720000,
      assignedPositions: 7,
      alertsToday: 1,
      avgRunTime: 5100,
      apiCallsToday: 48,
    },
    {
      _id: "3" as Id<"agentHeartbeats">,
      agentId: "a3" as Id<"agents">,
      frequency: "1hour",
      lastRun: Date.now() - 780000,
      nextRun: Date.now() + 2820000,
      assignedPositions: 7,
      alertsToday: 0,
      avgRunTime: 12300,
      apiCallsToday: 12,
    },
    {
      _id: "4" as Id<"agentHeartbeats">,
      agentId: "a4" as Id<"agents">,
      frequency: "4hour",
      lastRun: Date.now() - 3120000,
      nextRun: Date.now() + 11520000,
      assignedPositions: 7,
      alertsToday: 0,
      avgRunTime: 9800,
      apiCallsToday: 6,
    },
    {
      _id: "5" as Id<"agentHeartbeats">,
      agentId: "a5" as Id<"agents">,
      frequency: "daily",
      lastRun: Date.now() - 16620000,
      nextRun: Date.now() + 69780000,
      assignedPositions: 7,
      alertsToday: 0,
      avgRunTime: 7500,
      apiCallsToday: 1,
    },
    {
      _id: "6" as Id<"agentHeartbeats">,
      agentId: "a6" as Id<"agents">,
      frequency: "daily",
      lastRun: Date.now() - 43020000,
      nextRun: Date.now() + 43380000,
      assignedPositions: 7,
      alertsToday: 0,
      avgRunTime: 3200,
      apiCallsToday: 1,
    },
  ];

  const mockAgents: Record<string, Agent> = {
    a1: { _id: "a1" as Id<"agents">, name: "Guardian", status: "active" },
    a2: { _id: "a2" as Id<"agents">, name: "Risk Monitor", status: "active" },
    a3: { _id: "a3" as Id<"agents">, name: "Flow Monitor", status: "active" },
    a4: { _id: "a4" as Id<"agents">, name: "GEX Monitor", status: "idle" },
    a5: { _id: "a5" as Id<"agents">, name: "Volatility Monitor", status: "idle" },
    a6: { _id: "a6" as Id<"agents">, name: "Earnings Monitor", status: "idle" },
  };

  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [currentTime, setCurrentTime] = useState(Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const toggleExpanded = (agentId: string) => {
    const newExpanded = new Set(expandedAgents);
    if (newExpanded.has(agentId)) {
      newExpanded.delete(agentId);
    } else {
      newExpanded.add(agentId);
    }
    setExpandedAgents(newExpanded);
  };

  const formatCountdown = (timestampMs: number) => {
    const diff = timestampMs - currentTime;
    if (diff <= 0) return "now";

    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);

    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
      return `${minutes}m`;
    } else {
      return `${seconds}s`;
    }
  };

  const formatTimeAgo = (timestampMs: number) => {
    const diff = currentTime - timestampMs;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
      return `${minutes}m`;
    } else {
      return `${seconds}s`;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "active":
        return "bg-green-500";
      case "idle":
        return "bg-gray-400";
      case "error":
        return "bg-red-500";
      case "blocked":
        return "bg-yellow-500";
      default:
        return "bg-gray-400";
    }
  };

  const getAgentIcon = (name: string) => {
    if (name.includes("Guardian")) return "🤖";
    if (name.includes("Risk")) return "🔍";
    if (name.includes("Flow")) return "📊";
    if (name.includes("GEX")) return "🎯";
    if (name.includes("Volatility")) return "📈";
    if (name.includes("Earnings")) return "🔔";
    return "🤖";
  };

  const activeAgentsCount = mockHeartbeats.filter(
    (hb) => mockAgents[hb.agentId]?.status === "active"
  ).length;

  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-bold text-foreground">Agent Monitoring System</h2>
        <span className="px-2 py-1 bg-green-500 text-white text-xs font-bold rounded">
          {activeAgentsCount} Active
        </span>
      </div>

      <div className="space-y-2">
        {mockHeartbeats.map((heartbeat) => {
          const agent = mockAgents[heartbeat.agentId];
          if (!agent) return null;

          const isExpanded = expandedAgents.has(heartbeat.agentId);
          const apiLimitPercent = ((heartbeat.apiCallsToday || 0) / 200) * 100;

          return (
            <div
              key={heartbeat._id}
              className="bg-white rounded-lg border border-border shadow-sm overflow-hidden"
            >
              <div
                className="p-3 cursor-pointer hover:bg-muted transition-colors"
                onClick={() => toggleExpanded(heartbeat.agentId)}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 flex-1">
                    <span className="text-lg">{getAgentIcon(agent.name)}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-foreground truncate">
                          {agent.name}
                        </span>
                        <span className="text-xs text-muted-foreground">({heartbeat.frequency})</span>
                      </div>
                    </div>
                    <div className={`w-2 h-2 rounded-full ${getStatusColor(agent.status)}`} />
                    <span className="text-xs font-semibold text-muted-foreground uppercase">
                      {agent.status}
                    </span>
                    {isExpanded ? (
                      <IconChevronDown size={16} className="text-muted-foreground" />
                    ) : (
                      <IconChevronRight size={16} className="text-muted-foreground" />
                    )}
                  </div>
                </div>

                <div className="text-xs text-muted-foreground">
                  Positions: {heartbeat.assignedPositions} • Alerts today: {heartbeat.alertsToday} • Next:{" "}
                  {heartbeat.nextRun ? formatCountdown(heartbeat.nextRun) : "—"}
                </div>

                <div className="mt-2">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-muted-foreground">API Calls</span>
                    <span className="font-semibold">{heartbeat.apiCallsToday || 0}/200</span>
                  </div>
                  <div className="w-full bg-muted rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full transition-all ${
                        apiLimitPercent >= 90
                          ? "bg-red-500"
                          : apiLimitPercent >= 70
                          ? "bg-yellow-500"
                          : "bg-green-500"
                      }`}
                      style={{ width: `${Math.min(apiLimitPercent, 100)}%` }}
                    />
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div className="border-t border-border bg-muted/30 p-3 space-y-2">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <div className="text-muted-foreground">Last Run</div>
                      <div className="font-semibold">
                        {heartbeat.lastRun ? formatTimeAgo(heartbeat.lastRun) + " ago" : "Never"}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">Avg Run Time</div>
                      <div className="font-semibold">
                        {heartbeat.avgRunTime ? (heartbeat.avgRunTime / 1000).toFixed(1) + "s" : "—"}
                      </div>
                    </div>
                  </div>

                  <div className="text-xs text-muted-foreground">
                    Recent activity: Monitoring {heartbeat.assignedPositions} positions, generated{" "}
                    {heartbeat.alertsToday} alerts today
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default AgentStatusPanel;
