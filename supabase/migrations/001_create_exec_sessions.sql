-- Migration 001: Create MCP Execution Sessions and Cache Tables
-- Description: Foundation for token-efficient Supabase caching workflow
-- Dependencies: pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Execution sessions (Phase 0 cache foundation)
CREATE TABLE IF NOT EXISTS exec_sessions (
  exec_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_type TEXT NOT NULL CHECK (session_type IN ('guardian', 'monitor', 'entered', 'adhoc')),
  symbol TEXT NOT NULL,
  expiration DATE,
  account_size NUMERIC,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'expired')),
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast lookups
CREATE INDEX idx_exec_sessions_symbol ON exec_sessions(symbol);
CREATE INDEX idx_exec_sessions_status ON exec_sessions(status);
CREATE INDEX idx_exec_sessions_expires_at ON exec_sessions(expires_at);

-- Chain snapshots (full option chain data)
CREATE TABLE IF NOT EXISTS chain_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  expiration_filter TEXT,
  underlying_price NUMERIC NOT NULL,
  total_contracts INT,
  expirations TEXT[],
  chain_data JSONB NOT NULL,
  volatility_analysis JSONB,
  market_structure JSONB,
  dealer_positioning JSONB,
  fetch_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chain_snapshots_exec_id ON chain_snapshots(exec_id);
CREATE INDEX idx_chain_snapshots_symbol ON chain_snapshots(symbol);

-- Gold summaries (96% token reduction - 47 key fields)
CREATE TABLE IF NOT EXISTS gold_summaries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  underlying_price NUMERIC NOT NULL,
  atm_iv NUMERIC,
  iv_rank NUMERIC,
  iv_percentile NUMERIC,
  total_gex NUMERIC,
  gex_regime TEXT,
  pc_volume_ratio NUMERIC,
  pc_oi_ratio NUMERIC,
  max_pain_strike NUMERIC,
  max_pain_distance_pct NUMERIC,
  expected_move_1std NUMERIC,
  expected_move_2std NUMERIC,
  rsi_value NUMERIC,
  rsi_direction TEXT,
  macd_value NUMERIC,
  macd_signal NUMERIC,
  macd_histogram NUMERIC,
  adx_value NUMERIC,
  adx_trend TEXT,
  bollinger_upper NUMERIC,
  bollinger_lower NUMERIC,
  bollinger_squeeze BOOLEAN,
  sma_20 NUMERIC,
  sma_50 NUMERIC,
  ema_20 NUMERIC,
  cvd_1d_trend TEXT,
  cvd_5d_trend TEXT,
  dark_pool_buy_pct NUMERIC,
  dark_pool_sentiment TEXT,
  net_premium_call NUMERIC,
  net_premium_put NUMERIC,
  net_premium_bias TEXT,
  floor_volume_total INT,
  floor_volume_call_pct NUMERIC,
  sweep_count INT,
  block_trade_count INT,
  earnings_date DATE,
  earnings_risk TEXT,
  days_to_earnings INT,
  vix_level NUMERIC,
  market_regime TEXT,
  trade_suitability_score NUMERIC,
  key_support_levels NUMERIC[],
  key_resistance_levels NUMERIC[],
  recommended_strategies TEXT[],
  risk_warnings TEXT[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_gold_summaries_exec_id ON gold_summaries(exec_id);
CREATE INDEX idx_gold_summaries_symbol ON gold_summaries(symbol);

-- UW Flow Alerts cache
CREATE TABLE IF NOT EXISTS uw_flow_alerts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  total_alerts INT,
  sweep_count INT,
  block_count INT,
  call_premium NUMERIC,
  put_premium NUMERIC,
  directional_bias TEXT,
  lookback_days INT,
  all_alerts JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uw_flow_alerts_exec_id ON uw_flow_alerts(exec_id);

-- UW Dark Pool cache
CREATE TABLE IF NOT EXISTS uw_darkpool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  total_volume BIGINT,
  buy_volume_pct NUMERIC,
  sell_volume_pct NUMERIC,
  dark_pool_bias TEXT,
  block_trade_count INT,
  significant_levels JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uw_darkpool_exec_id ON uw_darkpool(exec_id);

-- UW Realized Volatility cache
CREATE TABLE IF NOT EXISTS uw_realized_volatility (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  implied_volatility NUMERIC,
  realized_volatility NUMERIC,
  iv_rank NUMERIC,
  iv_percentile NUMERIC,
  iv_rv_ratio NUMERIC,
  premium_status TEXT CHECK (premium_status IN ('RICH', 'FAIR', 'CHEAP')),
  timeframe TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uw_realized_volatility_exec_id ON uw_realized_volatility(exec_id);

-- UW Net Premium cache
CREATE TABLE IF NOT EXISTS uw_net_premium (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  call_premium NUMERIC,
  put_premium NUMERIC,
  net_premium NUMERIC,
  directional_bias TEXT,
  buying_pressure_pct NUMERIC,
  history_included BOOLEAN DEFAULT false,
  historical_data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uw_net_premium_exec_id ON uw_net_premium(exec_id);

-- UW Greeks by Strike cache
CREATE TABLE IF NOT EXISTS uw_greeks_by_strike (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  expiry DATE NOT NULL,
  total_gex NUMERIC,
  gex_regime TEXT,
  gex_flip_level NUMERIC,
  key_gex_strikes JSONB,
  charm NUMERIC,
  vanna NUMERIC,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uw_greeks_by_strike_exec_id ON uw_greeks_by_strike(exec_id);

-- Batch Technicals cache
CREATE TABLE IF NOT EXISTS batch_technicals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  rsi_data JSONB,
  macd_data JSONB,
  adx_data JSONB,
  bollinger_data JSONB,
  sma_data JSONB,
  trajectory_days INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_batch_technicals_exec_id ON batch_technicals(exec_id);

-- Battle results (Guardian outcomes)
CREATE TABLE IF NOT EXISTS battle_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  exec_id UUID NOT NULL REFERENCES exec_sessions(exec_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  expiration DATE NOT NULL,
  winning_agent TEXT NOT NULL,
  winning_strategy TEXT NOT NULL,
  winning_proposal JSONB NOT NULL,
  all_proposals JSONB NOT NULL,
  user_approved BOOLEAN DEFAULT false,
  approved_at TIMESTAMPTZ,
  executed BOOLEAN DEFAULT false,
  executed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_battle_results_exec_id ON battle_results(exec_id);
CREATE INDEX idx_battle_results_symbol ON battle_results(symbol);

-- Auto-cleanup expired sessions (runs daily)
CREATE OR REPLACE FUNCTION cleanup_expired_exec_sessions()
RETURNS void AS $$
BEGIN
  UPDATE exec_sessions
  SET status = 'expired'
  WHERE expires_at < NOW() AND status = 'active';

  -- Cascade delete will clean up all related tables
  DELETE FROM exec_sessions
  WHERE status = 'expired'
  AND expires_at < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;

-- Comments
COMMENT ON TABLE exec_sessions IS 'MCP execution session tracking with 24h TTL';
COMMENT ON TABLE gold_summaries IS '47-field compact summaries for 96% token reduction';
COMMENT ON TABLE chain_snapshots IS 'Full option chain data with analytics';
COMMENT ON FUNCTION cleanup_expired_exec_sessions IS 'Daily cleanup of expired sessions';
