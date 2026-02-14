-- Guardian Mission Control - MCP Integration
-- Migration 002: Links to massive-options-mcp Supabase cache
-- Created: 2026-02-13

-- NOTE: This assumes massive-options-mcp tables already exist in the same Supabase project
-- If using separate Supabase projects, use foreign data wrappers (FDW)

-- Battle results (Guardian /guardian skill outcomes)
CREATE TABLE battle_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- CRITICAL: Links to exact market snapshot from MCP cache
  exec_id TEXT NOT NULL, -- FK to exec_sessions.exec_id

  symbol TEXT NOT NULL,
  expiration DATE NOT NULL,

  -- Winner details
  winning_agent TEXT NOT NULL,
  winning_strategy TEXT NOT NULL,
  winning_proposal JSONB NOT NULL, -- Full proposal details

  -- All agent proposals for comparison
  all_proposals JSONB NOT NULL, -- Array of all 6 agent proposals

  -- User decision
  user_approved BOOLEAN DEFAULT false,
  executed BOOLEAN DEFAULT false,

  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_battle_results_exec_id ON battle_results(exec_id);
CREATE INDEX idx_battle_results_symbol ON battle_results(symbol);
CREATE INDEX idx_battle_results_winning_agent ON battle_results(winning_agent);

-- Add foreign key constraint if massive-options-mcp tables exist in same DB
-- If separate Supabase projects, remove this and use FDW
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'exec_sessions'
  ) THEN
    ALTER TABLE battle_results
      ADD CONSTRAINT fk_battle_results_exec_id
      FOREIGN KEY (exec_id)
      REFERENCES exec_sessions(exec_id)
      ON DELETE CASCADE;
  END IF;
END $$;

-- Add mcp_exec_id FK to supermemory_knowledge (if not using FDW)
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'exec_sessions'
  ) THEN
    ALTER TABLE supermemory_knowledge
      ADD CONSTRAINT fk_supermemory_mcp_exec_id
      FOREIGN KEY (mcp_exec_id)
      REFERENCES exec_sessions(exec_id)
      ON DELETE SET NULL;
  END IF;
END $$;

-- Forensic replay helper function
CREATE OR REPLACE FUNCTION get_battle_context(p_exec_id TEXT)
RETURNS TABLE (
  battle_summary JSONB,
  market_snapshot JSONB,
  flow_data JSONB,
  technicals JSONB
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    row_to_json(br.*)::jsonb as battle_summary,
    row_to_json(gs.*)::jsonb as market_snapshot,
    row_to_json(uwf.*)::jsonb as flow_data,
    row_to_json(uwdp.*)::jsonb as technicals
  FROM battle_results br
  LEFT JOIN gold_summaries gs ON gs.exec_id = br.exec_id
  LEFT JOIN uw_flow_alerts uwf ON uwf.exec_id = br.exec_id
  LEFT JOIN uw_darkpool uwdp ON uwdp.exec_id = br.exec_id
  WHERE br.exec_id = p_exec_id;
END;
$$;

-- Forensic query: "Why did vega-master recommend this?"
CREATE OR REPLACE FUNCTION agent_decision_context(
  p_agent_name TEXT,
  p_symbol TEXT,
  p_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
  knowledge_content TEXT,
  exec_id TEXT,
  confidence NUMERIC,
  market_snapshot JSONB
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    sk.content,
    sk.mcp_exec_id,
    sk.confidence,
    row_to_json(gs.*)::jsonb as market_snapshot
  FROM supermemory_knowledge sk
  LEFT JOIN gold_summaries gs ON gs.exec_id = sk.mcp_exec_id
  WHERE sk.agent_id = p_agent_name
    AND sk.symbol = p_symbol
    AND sk.created_at::date = p_date
  ORDER BY sk.created_at DESC
  LIMIT 1;
END;
$$;

-- Validate debate outcomes (3-7 days later)
CREATE OR REPLACE FUNCTION validate_debate_outcomes()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  debate_rec RECORD;
  current_price NUMERIC;
  price_change NUMERIC;
  outcome TEXT;
BEGIN
  -- Find unvalidated debates from 3-7 days ago
  FOR debate_rec IN
    SELECT *
    FROM agent_debate_outcomes
    WHERE actual_outcome IS NULL
      AND created_at BETWEEN NOW() - INTERVAL '7 days' AND NOW() - INTERVAL '3 days'
  LOOP
    -- Get current price from gold_summaries or real-time API
    -- This is a placeholder - implement actual price fetching
    SELECT underlying_price INTO current_price
    FROM gold_summaries
    WHERE symbol = debate_rec.ticker
    ORDER BY fetch_timestamp DESC
    LIMIT 1;

    IF current_price IS NOT NULL THEN
      price_change := (current_price - (debate_rec.market_context->>'price')::numeric) /
                     (debate_rec.market_context->>'price')::numeric;

      -- Determine outcome
      IF price_change < -0.05 THEN
        -- Price dropped >5%
        IF debate_rec.challenger_recommendation = 'EXIT' THEN
          outcome := 'challenger_correct';
        ELSE
          outcome := 'defender_correct';
        END IF;
      ELSIF price_change > 0.03 THEN
        -- Price up >3%
        IF debate_rec.challenger_recommendation = 'HOLD' THEN
          outcome := 'challenger_correct';
        ELSE
          outcome := 'defender_correct';
        END IF;
      ELSE
        outcome := 'both_wrong';
      END IF;

      -- Update debate outcome
      UPDATE agent_debate_outcomes
      SET
        actual_outcome = outcome,
        outcome_determined_at = NOW(),
        outcome_metrics = jsonb_build_object(
          'price_change_pct', price_change,
          'days_since_debate', EXTRACT(day FROM NOW() - created_at),
          'validation_price', current_price
        )
      WHERE id = debate_rec.id;

      -- Refresh agent accuracy stats
      PERFORM refresh_agent_accuracy_stats();
    END IF;
  END LOOP;
END;
$$;

-- Consolidate Mem0 session memories to long-term knowledge
CREATE OR REPLACE FUNCTION consolidate_session_memories(p_session_id TEXT, p_exec_id TEXT)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  memory_rec RECORD;
  category TEXT;
  confidence_val NUMERIC;
BEGIN
  FOR memory_rec IN
    SELECT *
    FROM mem0_vectors
    WHERE user_id = p_session_id
  LOOP
    -- Determine category based on content patterns
    IF memory_rec.content ILIKE '%approved%' OR memory_rec.content ILIKE '%rejected%' THEN
      category := 'user_preference';
      confidence_val := 1.0;
    ELSIF memory_rec.content ILIKE '%Winner:%' AND memory_rec.metadata->>'agent' = 'options-judge' THEN
      category := 'guardian_verdict';
      confidence_val := (memory_rec.metadata->>'winner_score')::numeric / 10.0;
    ELSIF memory_rec.metadata->>'finding_type' = 'institutional_signal' THEN
      category := 'institutional_signal';
      confidence_val := 0.8;
    ELSE
      category := 'pattern';
      confidence_val := 0.5;
    END IF;

    -- Insert into supermemory_knowledge
    INSERT INTO supermemory_knowledge (
      category,
      content,
      embedding,
      metadata,
      confidence,
      mcp_exec_id
    )
    VALUES (
      category,
      memory_rec.content,
      memory_rec.embedding,
      memory_rec.metadata || jsonb_build_object('session_id', p_session_id),
      confidence_val,
      p_exec_id
    );
  END LOOP;

  -- Delete session memories after consolidation
  DELETE FROM mem0_vectors WHERE user_id = p_session_id;
END;
$$;

-- Nightly cleanup jobs
CREATE OR REPLACE FUNCTION nightly_cleanup()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  -- Cleanup expired mem0 vectors (24h TTL)
  PERFORM cleanup_expired_mem0_vectors();

  -- Validate debate outcomes (3-7 days later)
  PERFORM validate_debate_outcomes();

  -- Decay confidence for low-performing patterns
  PERFORM decay_knowledge_confidence();

  -- Archive low-confidence knowledge (<0.2) after 90 days
  INSERT INTO supermemory_archive
  SELECT *
  FROM supermemory_knowledge
  WHERE confidence < 0.2
    AND updated_at < NOW() - INTERVAL '90 days';

  DELETE FROM supermemory_knowledge
  WHERE confidence < 0.2
    AND updated_at < NOW() - INTERVAL '90 days';
END;
$$;

-- Archive table for low-confidence knowledge
CREATE TABLE IF NOT EXISTS supermemory_archive (
  LIKE supermemory_knowledge INCLUDING ALL
);
