import React, { useState } from "react";
import { useQuery, useMutation } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { Id } from "../../../convex/_generated/dataModel";
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconInfoCircle,
  IconX,
  IconCheck,
  IconSettings,
} from "@tabler/icons-react";

interface Alert {
  _id: Id<"alerts">;
  positionId: Id<"positions">;
  agentId: Id<"agents">;
  severity: "info" | "warning" | "critical";
  type: "price_movement" | "greek_threshold" | "earnings_risk" | "flow_divergence" | "technical_signal";
  title: string;
  message: string;
  actionRequired?: string;
  discordSent: boolean;
  discordMessageId?: string;
  acknowledged: boolean;
  _creationTime: number;
  expiresAt?: number;
}

interface Position {
  _id: Id<"positions">;
  symbol: string;
  strategy: string;
}

interface Agent {
  _id: Id<"agents">;
  name: string;
}

interface AlertSystemProps {
  className?: string;
  onViewPosition?: (positionId: Id<"positions">) => void;
}

const AlertSystem: React.FC<AlertSystemProps> = ({ className = "", onViewPosition }) => {
  // In production, these would use useQuery to fetch from Convex
  // const alerts = useQuery(api.queries.listAlerts, { acknowledged: false });
  // const positions = useQuery(api.queries.listPositions);
  // const agents = useQuery(api.queries.listAgents);
  // const acknowledgeAlert = useMutation(api.alerts.acknowledge);
  // const dismissAlert = useMutation(api.alerts.dismiss);

  const [showSettings, setShowSettings] = useState(false);

  // Mock data
  const mockPositions: Record<string, Position> = {
    p1: { _id: "p1" as Id<"positions">, symbol: "ASTS", strategy: "iron_condor" },
    p2: { _id: "p2" as Id<"positions">, symbol: "NVDA", strategy: "bull_put_spread" },
    p3: { _id: "p3" as Id<"positions">, symbol: "AAPL", strategy: "long_call" },
  };

  const mockAgents: Record<string, Agent> = {
    a1: { _id: "a1" as Id<"agents">, name: "Guardian" },
    a2: { _id: "a2" as Id<"agents">, name: "GEX Monitor" },
    a3: { _id: "a3" as Id<"agents">, name: "Flow Monitor" },
  };

  const mockAlerts: Alert[] = [
    {
      _id: "al1" as Id<"alerts">,
      positionId: "p1" as Id<"positions">,
      agentId: "a1" as Id<"agents">,
      severity: "critical",
      type: "price_movement",
      title: "ASTS: Price approaching short strike",
      message: "Position: 50/55/65/70 IC • Spot: $64.80 (65 strike)",
      actionRequired: "Consider rolling up or closing",
      discordSent: true,
      acknowledged: false,
      _creationTime: Date.now() - 120000,
    },
    {
      _id: "al2" as Id<"alerts">,
      positionId: "p2" as Id<"positions">,
      agentId: "a2" as Id<"agents">,
      severity: "warning",
      type: "greek_threshold",
      title: "NVDA: High gamma exposure detected",
      message: "GEX: -$2.1M (negative regime) • Price: $142.35",
      actionRequired: "Monitor for volatility expansion",
      discordSent: false,
      acknowledged: false,
      _creationTime: Date.now() - 1080000,
    },
    {
      _id: "al3" as Id<"alerts">,
      positionId: "p3" as Id<"positions">,
      agentId: "a3" as Id<"agents">,
      severity: "info",
      type: "flow_divergence",
      title: "AAPL: Bullish flow detected",
      message: "Net Premium: +$2.3M calls (7-day) • P/C Ratio: 0.18",
      actionRequired: "Monitor for directional move",
      discordSent: false,
      acknowledged: false,
      _creationTime: Date.now() - 3600000,
    },
  ];

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case "critical":
        return <IconAlertCircle size={20} className="text-red-500" />;
      case "warning":
        return <IconAlertTriangle size={20} className="text-yellow-500" />;
      case "info":
        return <IconInfoCircle size={20} className="text-blue-500" />;
      default:
        return null;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical":
        return "border-l-red-500 bg-red-50";
      case "warning":
        return "border-l-yellow-500 bg-yellow-50";
      case "info":
        return "border-l-blue-500 bg-blue-50";
      default:
        return "border-l-gray-500 bg-gray-50";
    }
  };

  const formatTimeAgo = (timestamp: number) => {
    const diff = Date.now() - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return "Just now";
  };

  const handleAcknowledge = (alertId: Id<"alerts">) => {
    // In production: acknowledgeAlert({ alertId })
    console.log("Acknowledging alert:", alertId);
  };

  const handleDismiss = (alertId: Id<"alerts">) => {
    // In production: dismissAlert({ alertId })
    console.log("Dismissing alert:", alertId);
  };

  const handleClearAll = () => {
    // In production: clear all acknowledged alerts
    console.log("Clearing all acknowledged alerts");
  };

  const activeAlerts = mockAlerts.filter((a) => !a.acknowledged);

  return (
    <div className={`space-y-3 ${className}`}>
      {/* Header */}
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-bold text-foreground">
          Alerts{" "}
          {activeAlerts.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              ({activeAlerts.length} active)
            </span>
          )}
        </h2>
        <div className="flex gap-2">
          {activeAlerts.length > 0 && (
            <button
              onClick={handleClearAll}
              className="text-xs px-2 py-1 bg-muted hover:bg-muted/80 rounded transition-colors"
            >
              Clear All
            </button>
          )}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="p-1 hover:bg-muted rounded transition-colors"
            title="Alert settings"
          >
            <IconSettings size={16} className="text-muted-foreground" />
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="bg-muted rounded-lg border border-border p-3 space-y-2">
          <div className="text-sm font-semibold">Alert Settings</div>
          <div className="space-y-2 text-xs">
            <label className="flex items-center gap-2">
              <input type="checkbox" defaultChecked className="rounded" />
              <span>Send critical alerts to Discord</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" defaultChecked className="rounded" />
              <span>Desktop notifications</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="rounded" />
              <span>Email notifications</span>
            </label>
          </div>
        </div>
      )}

      {/* Alert List */}
      {activeAlerts.length === 0 ? (
        <div className="bg-white rounded-lg border border-border p-8 text-center">
          <IconCheck size={48} className="mx-auto text-green-500 mb-2" />
          <div className="text-sm text-muted-foreground">No active alerts</div>
        </div>
      ) : (
        <div className="space-y-3">
          {activeAlerts.map((alert) => {
            const position = mockPositions[alert.positionId];
            const agent = mockAgents[alert.agentId];

            return (
              <div
                key={alert._id}
                className={`bg-white rounded-lg border-l-4 border-r border-t border-b shadow-sm overflow-hidden ${getSeverityColor(
                  alert.severity
                )}`}
              >
                <div className="p-4 space-y-3">
                  {/* Alert Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-start gap-2 flex-1">
                      {getSeverityIcon(alert.severity)}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold uppercase text-muted-foreground">
                            {alert.severity}
                          </span>
                          <span className="text-xs text-muted-foreground">•</span>
                          <span className="text-xs text-muted-foreground">
                            {formatTimeAgo(alert._creationTime)}
                          </span>
                        </div>
                        <h3 className="text-sm font-bold text-foreground">{alert.title}</h3>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDismiss(alert._id)}
                      className="p-1 hover:bg-muted rounded transition-colors"
                      title="Dismiss alert"
                    >
                      <IconX size={14} className="text-muted-foreground" />
                    </button>
                  </div>

                  {/* Alert Body */}
                  <div className="text-sm text-foreground">{alert.message}</div>

                  {/* Action Required */}
                  {alert.actionRequired && (
                    <div className="bg-white/50 rounded px-3 py-2 text-xs">
                      <div className="font-semibold text-muted-foreground mb-1">Action Required</div>
                      <div className="text-foreground">{alert.actionRequired}</div>
                    </div>
                  )}

                  {/* Footer */}
                  <div className="flex justify-between items-center text-xs text-muted-foreground pt-2 border-t border-border">
                    <div>
                      Triggered by: <span className="font-semibold">{agent?.name || "Unknown"}</span>
                      {alert.discordSent && (
                        <span className="ml-2 text-blue-500">• Sent to Discord</span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2 pt-1">
                    {onViewPosition && (
                      <button
                        onClick={() => onViewPosition(alert.positionId)}
                        className="text-xs px-3 py-1.5 bg-[var(--accent-blue)] text-white rounded hover:opacity-90 transition-opacity"
                      >
                        View Position
                      </button>
                    )}
                    <button
                      onClick={() => handleAcknowledge(alert._id)}
                      className="text-xs px-3 py-1.5 bg-muted hover:bg-muted/80 rounded transition-colors"
                    >
                      Acknowledge
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default AlertSystem;
