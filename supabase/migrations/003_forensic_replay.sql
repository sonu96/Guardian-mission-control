-- Guardian Mission Control - Forensic Replay Utilities
-- Migration 003: Advanced query helpers and performance optimization
-- Created: 2026-02-13

-- Vector similarity search for Mem0 (required by mem0-client.ts)
CREATE OR REPLACE FUNCTION match_supermemory_knowledge(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.7,
  match_count int DEFAULT 10
)
RETURNS TABLE (
  id uuid,
  category text,
  content text,
  metadata jsonb,
  confidence numeric,
  mcp_exec_id text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    sk.id,
    sk.category,
    sk.content,
    sk.metadata,
    sk.confidence,
    sk.mcp_exec_id,
    1 - (sk.embedding <=> query_embedding) as similarity
  FROM supermemory_knowledge sk
  WHERE 1 - (sk.embedding <=> query_embedding) > match_threshold
  ORDER BY sk.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Advanced forensic query: Full position lifecycle with all analyses
CREATE OR REPLACE FUNCTION get_position_forensics(p_symbol TEXT, p_expiration DATE)
RETURNS TABLE (
  lifecycle_stage text,
  exec_id text,
  analysis_type text,
  market_snapshot jsonb,
  agent_decisions jsonb,
  user_actions jsonb,
  outcome_metrics jsonb,
  created_at timestamptz
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    CASE
      WHEN pt.status = 'WATCHING' THEN 'discovery'
      WHEN pt.status = 'ENTERED' THEN 'active'
      WHEN pt.status = 'CLOSED' THEN 'closed'
    END as lifecycle_stage,
    pt.latest_exec_id,
    'guardian_battle' as analysis_type,
    row_to_json(gs.*)::jsonb as market_snapshot,
    row_to_json(br.*)::jsonb as agent_decisions,
    jsonb_build_object(
      'entry_premium', pt.entry_premium,
      'exit_premium', pt.exit_premium,
      'realized_pnl', pt.realized_pnl
    ) as user_actions,
    jsonb_build_object(
      'price_change_pct', CASE
        WHEN pt.original_price IS NOT NULL AND pt.exit_premium IS NOT NULL
        THEN (pt.exit_premium - pt.original_price) / pt.original_price
        ELSE NULL
      END,
      'days_held', CASE
        WHEN pt.entry_date IS NOT NULL AND pt.exit_date IS NOT NULL
        THEN EXTRACT(day FROM pt.exit_date - pt.entry_date)
        ELSE NULL
      END
    ) as outcome_metrics,
    pt.created_at
  FROM position_tracking pt
  LEFT JOIN battle_results br ON br.exec_id = pt.latest_exec_id
  LEFT JOIN gold_summaries gs ON gs.exec_id = pt.latest_exec_id
  WHERE pt.symbol = p_symbol
    AND pt.expiration = p_expiration
  ORDER BY pt.created_at DESC;
END;
$$;

-- P&L charting helper (aggregates snapshots by time interval)
CREATE OR REPLACE FUNCTION get_position_pnl_chart(
  p_position_id TEXT,
  p_interval TEXT DEFAULT '1 hour'
)
RETURNS TABLE (
  bucket timestamptz,
  avg_price numeric,
  avg_pnl numeric,
  min_pnl numeric,
  max_pnl numeric,
  sample_count bigint
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    time_bucket(p_interval::interval, snapshot_at) as bucket,
    ROUND(AVG(current_price), 2) as avg_price,
    ROUND(AVG(unrealized_pnl), 2) as avg_pnl,
    ROUND(MIN(unrealized_pnl), 2) as min_pnl,
    ROUND(MAX(unrealized_pnl), 2) as max_pnl,
    COUNT(*) as sample_count
  FROM position_snapshots
  WHERE position_id = p_position_id
  GROUP BY bucket
  ORDER BY bucket DESC;
END;
$$;

-- Install TimescaleDB extension for time_bucket (optional, for better charting)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Alternative time_bucket implementation if TimescaleDB not available
CREATE OR REPLACE FUNCTION time_bucket(bucket_width interval, ts timestamptz)
RETURNS timestamptz
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT date_trunc('hour', ts);
$$;

-- Agent win rate trends over time
CREATE OR REPLACE FUNCTION get_agent_win_trends(
  p_agent_name TEXT,
  p_lookback_days INT DEFAULT 30
)
RETURNS TABLE (
  week_start date,
  total_debates bigint,
  wins bigint,
  win_rate_pct numeric,
  avg_confidence numeric
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    DATE_TRUNC('week', created_at)::date as week_start,
    COUNT(*) as total_debates,
    COUNT(*) FILTER (WHERE actual_outcome = 'challenger_correct') as wins,
    ROUND(
      COUNT(*) FILTER (WHERE actual_outcome = 'challenger_correct')::numeric /
      NULLIF(COUNT(*), 0) * 100,
      2
    ) as win_rate_pct,
    ROUND(AVG(challenger_confidence), 2) as avg_confidence
  FROM agent_debate_outcomes
  WHERE challenger_agent = p_agent_name
    AND created_at >= NOW() - (p_lookback_days || ' days')::interval
    AND actual_outcome IS NOT NULL
  GROUP BY week_start
  ORDER BY week_start DESC;
END;
$$;

-- Market context at specific time (reconstructs exact conditions)
CREATE OR REPLACE FUNCTION get_market_context_at(p_timestamp TIMESTAMPTZ)
RETURNS TABLE (
  vix numeric,
  spy_price numeric,
  spy_gex numeric,
  market_phase text,
  put_call_ratio numeric
)
LANGUAGE plpgsql
AS $$
BEGIN
  -- This assumes market_regime data is archived to Supabase
  -- If only in Convex, need to query via API
  RETURN QUERY
  SELECT
    0.0 as vix, -- TODO: Query from archived market_regime
    0.0 as spy_price,
    0.0 as spy_gex,
    'unknown' as market_phase,
    0.0 as put_call_ratio
  LIMIT 1;
END;
$$;

-- Backtest agent decisions (what if we always followed agent X?)
CREATE OR REPLACE FUNCTION backtest_agent_strategy(
  p_agent_name TEXT,
  p_start_date DATE,
  p_end_date DATE
)
RETURNS TABLE (
  total_signals bigint,
  signals_followed bigint,
  correct_calls bigint,
  accuracy_pct numeric,
  hypothetical_pnl numeric,
  best_call jsonb,
  worst_call jsonb
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH agent_calls AS (
    SELECT
      sk.content,
      sk.metadata,
      sk.mcp_exec_id,
      sk.created_at,
      pt.realized_pnl
    FROM supermemory_knowledge sk
    LEFT JOIN position_tracking pt ON pt.first_exec_id = sk.mcp_exec_id
    WHERE sk.agent_id = p_agent_name
      AND sk.created_at::date BETWEEN p_start_date AND p_end_date
      AND sk.category = 'guardian_verdict'
  )
  SELECT
    COUNT(*) as total_signals,
    COUNT(*) FILTER (WHERE realized_pnl IS NOT NULL) as signals_followed,
    COUNT(*) FILTER (WHERE realized_pnl > 0) as correct_calls,
    ROUND(
      COUNT(*) FILTER (WHERE realized_pnl > 0)::numeric /
      NULLIF(COUNT(*) FILTER (WHERE realized_pnl IS NOT NULL), 0) * 100,
      2
    ) as accuracy_pct,
    COALESCE(SUM(realized_pnl), 0) as hypothetical_pnl,
    (
      SELECT row_to_json(ac.*)::jsonb
      FROM agent_calls ac
      WHERE ac.realized_pnl IS NOT NULL
      ORDER BY ac.realized_pnl DESC
      LIMIT 1
    ) as best_call,
    (
      SELECT row_to_json(ac.*)::jsonb
      FROM agent_calls ac
      WHERE ac.realized_pnl IS NOT NULL
      ORDER BY ac.realized_pnl ASC
      LIMIT 1
    ) as worst_call
  FROM agent_calls;
END;
$$;

-- Index optimizations for common queries
CREATE INDEX IF NOT EXISTS idx_battle_results_symbol_expiration
  ON battle_results(symbol, expiration);

CREATE INDEX IF NOT EXISTS idx_position_tracking_all_exec_ids
  ON position_tracking USING GIN (all_exec_ids);

CREATE INDEX IF NOT EXISTS idx_supermemory_created_at
  ON supermemory_knowledge(created_at);

-- Partial indexes for hot queries
CREATE INDEX IF NOT EXISTS idx_position_tracking_active
  ON position_tracking(symbol, expiration)
  WHERE status = 'ENTERED';

CREATE INDEX IF NOT EXISTS idx_agent_debates_unvalidated
  ON agent_debate_outcomes(created_at)
  WHERE actual_outcome IS NULL;

-- Performance monitoring view
CREATE OR REPLACE VIEW query_performance_stats AS
SELECT
  'position_tracking' as table_name,
  (SELECT COUNT(*) FROM position_tracking) as row_count,
  (SELECT COUNT(*) FROM position_tracking WHERE status = 'ENTERED') as active_count,
  (SELECT pg_size_pretty(pg_total_relation_size('position_tracking'))) as total_size
UNION ALL
SELECT
  'position_snapshots' as table_name,
  (SELECT COUNT(*) FROM position_snapshots) as row_count,
  (SELECT COUNT(*) FROM position_snapshots WHERE snapshot_at > NOW() - INTERVAL '7 days') as active_count,
  (SELECT pg_size_pretty(pg_total_relation_size('position_snapshots'))) as total_size
UNION ALL
SELECT
  'supermemory_knowledge' as table_name,
  (SELECT COUNT(*) FROM supermemory_knowledge) as row_count,
  (SELECT COUNT(*) FROM supermemory_knowledge WHERE confidence >= 0.5) as active_count,
  (SELECT pg_size_pretty(pg_total_relation_size('supermemory_knowledge'))) as total_size;

-- Grant permissions (adjust for your setup)
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO authenticated;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;
