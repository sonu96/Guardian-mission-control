import React from "react";
import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Id } from "../../../convex/_generated/dataModel";
import { IconAlertTriangle, IconCheck, IconX } from "@tabler/icons-react";

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

interface PositionCardProps {
  position: Position;
  isSelected: boolean;
  onClick: () => void;
  getAgentName: (id: string) => string;
  formatRelativeTime: (timestamp: number) => string;
  columnId: string;
  compact?: boolean;
  isOverlay?: boolean;
}

const PositionCard: React.FC<PositionCardProps> = ({
  position,
  isSelected,
  onClick,
  getAgentName,
  formatRelativeTime,
  columnId,
  compact = false,
  isOverlay = false,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    isDragging,
  } = useDraggable({
    id: position._id,
    data: { position },
  });

  const style = transform
    ? {
        transform: CSS.Translate.toString(transform),
      }
    : undefined;

  const daysToExpiration = Math.ceil((new Date(position.expiration).getTime() - Date.now()) / (1000 * 60 * 60 * 24));

  const formatStrikes = () => {
    const { longPut, shortPut, shortCall, longCall } = position.strikes;
    if (position.strategy === "iron_condor") {
      return `${longPut}/${shortPut}/${shortCall}/${longCall}`;
    } else if (position.strategy === "bull_put_spread") {
      return `${longPut}/${shortPut}`;
    } else if (position.strategy === "bear_call_spread") {
      return `${shortCall}/${longCall}`;
    } else if (position.strategy === "long_call") {
      return `${longCall}C`;
    } else if (position.strategy === "long_put") {
      return `${longPut}P`;
    }
    return "";
  };

  const getStatusColor = () => {
    switch (position.status) {
      case "monitoring":
        return "bg-green-500";
      case "warning":
        return "bg-yellow-500";
      case "critical":
        return "bg-red-500";
      case "closed":
        return "bg-gray-400";
      default:
        return "bg-gray-400";
    }
  };

  const getStatusIcon = () => {
    switch (position.status) {
      case "monitoring":
        return <IconCheck size={16} className="text-green-500" />;
      case "warning":
        return <IconAlertTriangle size={16} className="text-yellow-500" />;
      case "critical":
        return <IconX size={16} className="text-red-500" />;
      default:
        return null;
    }
  };

  const getPnLColor = () => {
    if (!position.currentPnL) return "text-muted-foreground";
    return position.currentPnL >= 0 ? "text-green-600" : "text-red-600";
  };

  const formatStrategyName = () => {
    return position.strategy
      .split("_")
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  const maxProfitPercent = Math.min(Math.abs(position.currentPnLPercent || 0), 100);

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        borderLeft: isSelected || isOverlay ? undefined : `4px solid ${getStatusColor()}`,
      }}
      className={`min-w-0 bg-white rounded-lg p-3 sm:p-4 shadow-sm flex flex-col gap-2 border transition-all cursor-pointer select-none ${
        isDragging ? "dragging-card" : "hover:-translate-y-0.5 hover:shadow-md"
      } ${
        isSelected
          ? "ring-2 ring-[var(--accent-blue)] border-transparent"
          : "border-border"
      } ${columnId === "closed" ? "opacity-60" : ""} ${isOverlay ? "drag-overlay" : ""}`}
      onClick={onClick}
      {...listeners}
      {...attributes}
    >
      <div className="flex justify-between items-start">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-foreground truncate">
              {position.symbol}
            </h3>
            {getStatusIcon()}
          </div>
          <p className="text-xs text-muted-foreground truncate">
            {formatStrategyName()}
          </p>
        </div>
        <div className={`w-3 h-3 rounded-full ${getStatusColor()} flex-shrink-0`} />
      </div>

      <div className="text-xs text-muted-foreground">
        <span className="font-mono">{formatStrikes()}</span>
        <span className="mx-1">•</span>
        <span>{new Date(position.expiration).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
        <span className="mx-1">•</span>
        <span className={daysToExpiration <= 7 ? "text-red-600 font-semibold" : ""}>
          {daysToExpiration} DTE
        </span>
      </div>

      {!compact && (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <div className="text-muted-foreground">Entry</div>
              <div className="font-semibold">${position.entryPrice.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Current</div>
              <div className="font-semibold">
                {position.currentPrice ? `$${position.currentPrice.toFixed(2)}` : "—"}
              </div>
            </div>
          </div>

          {position.currentPnL !== undefined && (
            <div className="space-y-1">
              <div className="flex justify-between items-center">
                <span className={`text-sm font-bold ${getPnLColor()}`}>
                  {position.currentPnL >= 0 ? "+" : ""}${position.currentPnL.toFixed(0)}
                </span>
                <span className={`text-xs font-semibold ${getPnLColor()}`}>
                  ({position.currentPnL >= 0 ? "+" : ""}{position.currentPnLPercent?.toFixed(1)}%)
                </span>
              </div>
              <div className="w-full bg-muted rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full transition-all ${
                    position.currentPnL >= 0 ? "bg-green-500" : "bg-red-500"
                  }`}
                  style={{ width: `${maxProfitPercent}%` }}
                />
              </div>
              <div className="text-xs text-muted-foreground">
                {maxProfitPercent.toFixed(0)}% of max profit
              </div>
            </div>
          )}

          {position.greeks && (
            <div className="grid grid-cols-4 gap-1 text-xs border-t border-border pt-2">
              <div>
                <div className="text-muted-foreground text-[10px]">Δ</div>
                <div className="font-mono font-semibold">{position.greeks.delta.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-muted-foreground text-[10px]">Γ</div>
                <div className="font-mono font-semibold">{position.greeks.gamma.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-muted-foreground text-[10px]">Θ</div>
                <div className="font-mono font-semibold text-green-600">
                  +${Math.abs(position.greeks.theta).toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-muted-foreground text-[10px]">V</div>
                <div className="font-mono font-semibold">{position.greeks.vega.toFixed(0)}</div>
              </div>
            </div>
          )}
        </>
      )}

      <div className="flex justify-between items-center text-xs text-muted-foreground border-t border-border pt-2 mt-1">
        {position.assignedAgentId && (
          <div className="flex items-center gap-1">
            <span>👤</span>
            <span className="font-semibold">
              {getAgentName(position.assignedAgentId as string)}
            </span>
          </div>
        )}
        <span>{formatRelativeTime(position.lastUpdate)}</span>
      </div>
    </div>
  );
};

export default PositionCard;
