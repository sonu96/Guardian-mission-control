-- Migration 002: Position Lifecycle Tracking
-- Description: Track option positions from analysis through entry to exit
-- Dependencies: 001_create_exec_sessions.sql

-- Position tracking (full lifecycle)
CREATE TABLE IF NOT EXISTS position_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  symbol TEXT NOT NULL,
  expiration DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'WATCHING' CHECK (status IN ('WATCHING', 'ENTERED', 'CLOSED', 'ROLLED')),

  -- Execution ID tracking
  first_exec_id UUID REFERENCES exec_sessions(exec_id) ON DELETE SET NULL,
  latest_exec_id UUID REFERENCES exec_sessions(exec_id) ON DELETE SET NULL,
  all_exec_ids UUID[] DEFAULT ARRAY[]::UUID[],
  analysis_count INT DEFAULT 0,

  -- Original analysis data
  original_price NUMERIC,
  original_strategy TEXT,
  original_analysis_date TIMESTAMPTZ,

  -- Latest market data
  latest_price NUMERIC,
  latest_dte INT,
  latest_update TIMESTAMPTZ,

  -- Entry details (populated when status = 'ENTERED')
  entry_date TIMESTAMPTZ,
  entry_premium NUMERIC,
  entry_legs JSONB,

  -- Current P&L (updated by monitors)
  current_premium NUMERIC,
  current_pnl NUMERIC,
  current_pnl_pct NUMERIC,

  -- Exit details (populated when status = 'CLOSED')
  exit_date TIMESTAMPTZ,
  exit_premium NUMERIC,
  exit_reason TEXT,
  realized_pnl NUMERIC,
  realized_pnl_pct NUMERIC,
  days_held INT,

  -- Roll tracking
  rolled_from_id UUID REFERENCES position_tracking(id) ON DELETE SET NULL,
  rolled_to_id UUID REFERENCES position_tracking(id) ON DELETE SET NULL,

  -- Alert triggers
  price_trigger_below NUMERIC,
  price_trigger_above NUMERIC,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Unique constraint: one active position per symbol+expiration
  CONSTRAINT unique_active_position UNIQUE(symbol, expiration, status) DEFERRABLE INITIALLY DEFERRED
);

-- Indexes
CREATE INDEX idx_position_tracking_symbol ON position_tracking(symbol);
CREATE INDEX idx_position_tracking_status ON position_tracking(status);
CREATE INDEX idx_position_tracking_expiration ON position_tracking(expiration);
CREATE INDEX idx_position_tracking_first_exec_id ON position_tracking(first_exec_id);
CREATE INDEX idx_position_tracking_latest_exec_id ON position_tracking(latest_exec_id);

-- Position snapshots (5-min heartbeat data)
-- Partitioned by month for performance
CREATE TABLE IF NOT EXISTS position_snapshots (
  id UUID DEFAULT uuid_generate_v4(),
  position_id TEXT NOT NULL, -- Convex position ID
  ticker TEXT NOT NULL,
  strategy TEXT NOT NULL,
  current_price NUMERIC,
  unrealized_pnl NUMERIC,
  delta NUMERIC,
  gamma NUMERIC,
  theta NUMERIC,
  vega NUMERIC,
  underlying_price NUMERIC,
  days_to_expiration INT,
  iv_rank NUMERIC,
  snapshot_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (snapshot_at);

-- Create partitions for current and next 3 months
CREATE TABLE position_snapshots_2026_02 PARTITION OF position_snapshots
  FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

CREATE TABLE position_snapshots_2026_03 PARTITION OF position_snapshots
  FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE position_snapshots_2026_04 PARTITION OF position_snapshots
  FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- Indexes on partitioned table
CREATE INDEX idx_position_snapshots_position_id ON position_snapshots(position_id);
CREATE INDEX idx_position_snapshots_ticker ON position_snapshots(ticker);
CREATE INDEX idx_position_snapshots_snapshot_at ON position_snapshots(snapshot_at);

-- Auto-update timestamp
CREATE OR REPLACE FUNCTION update_position_tracking_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER position_tracking_updated_at
  BEFORE UPDATE ON position_tracking
  FOR EACH ROW
  EXECUTE FUNCTION update_position_tracking_timestamp();

-- Function to link new exec_id to position
CREATE OR REPLACE FUNCTION link_exec_to_position(
  p_symbol TEXT,
  p_expiration DATE,
  p_exec_id UUID
)
RETURNS UUID AS $$
DECLARE
  v_position_id UUID;
BEGIN
  -- Find or create position
  INSERT INTO position_tracking (symbol, expiration, first_exec_id, latest_exec_id, all_exec_ids, analysis_count)
  VALUES (p_symbol, p_expiration, p_exec_id, p_exec_id, ARRAY[p_exec_id], 1)
  ON CONFLICT (symbol, expiration, status)
  DO UPDATE SET
    latest_exec_id = p_exec_id,
    all_exec_ids = array_append(position_tracking.all_exec_ids, p_exec_id),
    analysis_count = position_tracking.analysis_count + 1,
    latest_update = NOW()
  RETURNING id INTO v_position_id;

  RETURN v_position_id;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate P&L metrics
CREATE OR REPLACE FUNCTION calculate_position_pnl(
  p_position_id UUID,
  p_current_premium NUMERIC
)
RETURNS TABLE(pnl NUMERIC, pnl_pct NUMERIC) AS $$
DECLARE
  v_entry_premium NUMERIC;
BEGIN
  SELECT entry_premium INTO v_entry_premium
  FROM position_tracking
  WHERE id = p_position_id;

  IF v_entry_premium IS NULL THEN
    RETURN QUERY SELECT NULL::NUMERIC, NULL::NUMERIC;
  END IF;

  RETURN QUERY SELECT
    (p_current_premium - v_entry_premium) AS pnl,
    ((p_current_premium - v_entry_premium) / NULLIF(v_entry_premium, 0) * 100) AS pnl_pct;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;

-- Comments
COMMENT ON TABLE position_tracking IS 'Full lifecycle tracking from analysis to close';
COMMENT ON TABLE position_snapshots IS 'Historical P&L snapshots (partitioned by month)';
COMMENT ON FUNCTION link_exec_to_position IS 'Links new analysis to existing position';
COMMENT ON FUNCTION calculate_position_pnl IS 'Calculate P&L metrics for a position';
