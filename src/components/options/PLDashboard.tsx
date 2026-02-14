import React from "react";
import { Id } from "../../../convex/_generated/dataModel";

interface PortfolioSnapshot {
  totalPnL: number;
  totalPnLPercent: number;
  dailyPnL: number;
  openPositions: number;
  closedToday: number;
  accountValue: number;
  buyingPower: number;
  netGreeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
  };
  riskMetrics: {
    portfolioConcentration: number;
    maxDrawdown: number;
    sharpeRatio?: number;
  };
}

interface Position {
  _id: Id<"positions">;
  symbol: string;
  currentPnLPercent?: number;
  status: string;
}

interface PLDashboardProps {
  positions?: Position[];
}

const PLDashboard: React.FC<PLDashboardProps> = ({ positions = [] }) => {
  const mockSnapshot: PortfolioSnapshot = {
    totalPnL: 1247,
    totalPnLPercent: 8.3,
    dailyPnL: 312,
    openPositions: positions.filter(p => p.status !== "closed").length || 7,
    closedToday: positions.filter(p => p.status === "closed").length || 2,
    accountValue: 16500,
    buyingPower: 8200,
    netGreeks: {
      delta: 0.12,
      gamma: -0.08,
      theta: 87,
      vega: -45,
    },
    riskMetrics: {
      portfolioConcentration: 32,
      maxDrawdown: -5.2,
      sharpeRatio: 1.8,
    },
  };

  const snapshot = mockSnapshot;

  const getPnLColor = (value: number) => {
    return value >= 0 ? "text-green-600" : "text-red-600";
  };

  const getHeatMapColor = (pnlPercent: number) => {
    if (pnlPercent >= 15) return "bg-green-600 text-white";
    if (pnlPercent >= 5) return "bg-green-500 text-white";
    if (pnlPercent >= 0) return "bg-green-400 text-gray-900";
    if (pnlPercent >= -5) return "bg-yellow-400 text-gray-900";
    if (pnlPercent >= -10) return "bg-orange-500 text-white";
    return "bg-red-600 text-white";
  };

  const getStatusEmoji = (pnlPercent: number) => {
    if (pnlPercent >= 10) return "🟢";
    if (pnlPercent >= 0) return "🟢";
    if (pnlPercent >= -5) return "🟡";
    return "🔴";
  };

  return (
    <div className="space-y-4 p-4">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-bold text-foreground">Portfolio Overview</h2>
        <span className="text-xs text-muted-foreground">Updated: Just now</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">Total P&L</div>
          <div className={`text-2xl font-bold ${getPnLColor(snapshot.totalPnL)}`}>
            {snapshot.totalPnL >= 0 ? "+" : ""}${snapshot.totalPnL.toLocaleString()}
          </div>
          <div className={`text-sm font-semibold ${getPnLColor(snapshot.totalPnL)}`}>
            ({snapshot.totalPnL >= 0 ? "+" : ""}{snapshot.totalPnLPercent.toFixed(1)}%)
          </div>
        </div>

        <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">Daily P&L</div>
          <div className={`text-2xl font-bold ${getPnLColor(snapshot.dailyPnL)}`}>
            {snapshot.dailyPnL >= 0 ? "+" : ""}${snapshot.dailyPnL.toLocaleString()}
          </div>
          <div className="text-sm text-muted-foreground">
            {snapshot.openPositions} active, {snapshot.closedToday} closed today
          </div>
        </div>

        <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">Account Value</div>
          <div className="text-2xl font-bold text-foreground">
            ${snapshot.accountValue.toLocaleString()}
          </div>
          <div className="text-sm text-muted-foreground">
            Buying Power: ${snapshot.buyingPower.toLocaleString()}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
        <h3 className="text-sm font-bold text-foreground mb-3">Net Portfolio Greeks</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-muted-foreground mb-1">Delta (Δ)</div>
            <div className={`text-xl font-bold font-mono ${getPnLColor(snapshot.netGreeks.delta)}`}>
              {snapshot.netGreeks.delta >= 0 ? "+" : ""}{snapshot.netGreeks.delta.toFixed(2)}
            </div>
            <div className="text-xs text-muted-foreground">Directional exposure</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Gamma (Γ)</div>
            <div className={`text-xl font-bold font-mono ${getPnLColor(snapshot.netGreeks.gamma)}`}>
              {snapshot.netGreeks.gamma >= 0 ? "+" : ""}{snapshot.netGreeks.gamma.toFixed(2)}
            </div>
            <div className="text-xs text-muted-foreground">Delta sensitivity</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Theta (Θ)</div>
            <div className={`text-xl font-bold font-mono ${getPnLColor(snapshot.netGreeks.theta)}`}>
              {snapshot.netGreeks.theta >= 0 ? "+" : ""}${snapshot.netGreeks.theta.toFixed(0)}/day
            </div>
            <div className="text-xs text-muted-foreground">Time decay</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Vega (V)</div>
            <div className={`text-xl font-bold font-mono ${getPnLColor(snapshot.netGreeks.vega)}`}>
              {snapshot.netGreeks.vega >= 0 ? "+" : ""}${snapshot.netGreeks.vega.toFixed(0)}
            </div>
            <div className="text-xs text-muted-foreground">IV sensitivity</div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
        <h3 className="text-sm font-bold text-foreground mb-3">Risk Metrics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-muted-foreground mb-1">Max Concentration</div>
            <div className="text-xl font-bold text-foreground">
              {snapshot.riskMetrics.portfolioConcentration}%
            </div>
            <div className="text-xs text-muted-foreground">Single position limit</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Max Drawdown</div>
            <div className={`text-xl font-bold ${getPnLColor(snapshot.riskMetrics.maxDrawdown)}`}>
              {snapshot.riskMetrics.maxDrawdown.toFixed(1)}%
            </div>
            <div className="text-xs text-muted-foreground">Peak to trough</div>
          </div>
          {snapshot.riskMetrics.sharpeRatio && (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Sharpe Ratio</div>
              <div className="text-xl font-bold text-foreground">
                {snapshot.riskMetrics.sharpeRatio.toFixed(2)}
              </div>
              <div className="text-xs text-muted-foreground">Risk-adjusted return</div>
            </div>
          )}
        </div>
      </div>

      {positions.length > 0 && (
        <div className="bg-white rounded-lg border border-border p-4 shadow-sm">
          <h3 className="text-sm font-bold text-foreground mb-3">Position Heat Map (by P&L %)</h3>
          <div className="overflow-x-auto">
            <div className="flex gap-2 min-w-max">
              {positions.map((position) => (
                <div
                  key={position._id}
                  className={`w-20 h-20 rounded-lg flex flex-col items-center justify-center text-center p-2 ${getHeatMapColor(
                    position.currentPnLPercent || 0
                  )}`}
                >
                  <div className="text-xs font-bold truncate w-full">{position.symbol}</div>
                  <div className="text-lg font-bold">
                    {position.currentPnLPercent !== undefined
                      ? `${position.currentPnLPercent >= 0 ? "+" : ""}${position.currentPnLPercent.toFixed(0)}%`
                      : "—"}
                  </div>
                  <div className="text-base">{getStatusEmoji(position.currentPnLPercent || 0)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PLDashboard;
