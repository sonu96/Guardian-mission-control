-- Migration 003: Agent Debate Tracking and Validation
-- Description: Track inter-agent debates, resolutions, and accuracy stats
-- Dependencies: 002_create_position_tracking.sql

-- Agent debate outcomes (permanent record)
CREATE TABLE IF NOT EXISTS agent_debate_outcomes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  convex_debate_id TEXT NOT NULL UNIQUE, -- Reference to Convex debates table
  position_id UUID REFERENCES position_tracking(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,
  strategy TEXT,

  -- Debate participants
  challenger_agent TEXT NOT NULL,
  defender_agent TEXT NOT NULL,

  -- Recommendations
  challenger_recommendation TEXT NOT NULL,
  challenger_confidence NUMERIC NOT NULL CHECK (challenger_confidence BETWEEN 0 AND 10),
  defender_recommendation TEXT NOT NULL,
  defender_confidence NUMERIC NOT NULL CHECK (defender_confidence BETWEEN 0 AND 10),

  -- Resolution
  resolution_type TEXT CHECK (resolution_type IN (
    'veto',
    'confidence_gap',
    'majority_consensus',
    'human_escalation',
    'timeout'
  )),
  winner_agent TEXT,
  final_action TEXT,

  -- Human decision (if escalated)
  human_decision TEXT,
  decided_by TEXT,
  decided_at TIMESTAMPTZ,

  -- Market context at debate time
  market_context JSONB NOT NULL,

  -- Outcome validation (3-7 days later)
  actual_outcome TEXT CHECK (actual_outcome IN (
    'challenger_correct',
    'defender_correct',
    'both_wrong',
    'inconclusive'
  )),
  outcome_determined_at TIMESTAMPTZ,
  outcome_metrics JSONB,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_agent_debate_outcomes_ticker ON agent_debate_outcomes(ticker);
CREATE INDEX idx_agent_debate_outcomes_challenger ON agent_debate_outcomes(challenger_agent);
CREATE INDEX idx_agent_debate_outcomes_defender ON agent_debate_outcomes(defender_agent);
CREATE INDEX idx_agent_debate_outcomes_created_at ON agent_debate_outcomes(created_at);
CREATE INDEX idx_agent_debate_outcomes_actual_outcome ON agent_debate_outcomes(actual_outcome);

-- Materialized view: Agent accuracy stats
CREATE MATERIALIZED VIEW IF NOT EXISTS agent_accuracy_stats AS
SELECT
  agent_name,
  opponent,
  COUNT(*) as total_debates,
  COUNT(*) FILTER (WHERE won) as wins,
  COUNT(*) FILTER (WHERE NOT won) as losses,
  ROUND(
    COUNT(*) FILTER (WHERE won)::numeric /
    NULLIF(COUNT(*), 0) * 100,
    2
  ) as win_rate_pct,
  AVG(confidence) FILTER (WHERE won) as avg_confidence_when_right,
  AVG(confidence) FILTER (WHERE NOT won) as avg_confidence_when_wrong,
  MAX(created_at) as last_debate_at
FROM (
  -- Challenger wins
  SELECT
    challenger_agent as agent_name,
    defender_agent as opponent,
    actual_outcome = 'challenger_correct' as won,
    challenger_confidence as confidence,
    created_at
  FROM agent_debate_outcomes
  WHERE actual_outcome IS NOT NULL

  UNION ALL

  -- Defender wins
  SELECT
    defender_agent as agent_name,
    challenger_agent as opponent,
    actual_outcome = 'defender_correct' as won,
    defender_confidence as confidence,
    created_at
  FROM agent_debate_outcomes
  WHERE actual_outcome IS NOT NULL
) debates
GROUP BY agent_name, opponent;

-- Indexes on materialized view
CREATE INDEX idx_agent_accuracy_stats_agent ON agent_accuracy_stats(agent_name);
CREATE INDEX idx_agent_accuracy_stats_win_rate ON agent_accuracy_stats(win_rate_pct DESC);

-- Approval requests (human escalation)
CREATE TABLE IF NOT EXISTS approval_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  discord_message_id TEXT UNIQUE,
  discord_channel_id TEXT,

  position_id UUID REFERENCES position_tracking(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,

  agent_id TEXT NOT NULL,
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  confidence NUMERIC CHECK (confidence BETWEEN 0 AND 10),

  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
    'pending',
    'approved',
    'denied',
    'timeout'
  )),

  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  approval_reason TEXT,

  denied_by TEXT,
  denied_at TIMESTAMPTZ,
  denial_reason TEXT,

  timeout_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '1 hour',

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_approval_requests_status ON approval_requests(status);
CREATE INDEX idx_approval_requests_ticker ON approval_requests(ticker);
CREATE INDEX idx_approval_requests_timeout_at ON approval_requests(timeout_at);
CREATE INDEX idx_approval_requests_discord_message_id ON approval_requests(discord_message_id);

-- Auto-update timestamps
CREATE TRIGGER agent_debate_outcomes_updated_at
  BEFORE UPDATE ON agent_debate_outcomes
  FOR EACH ROW
  EXECUTE FUNCTION update_position_tracking_timestamp();

CREATE TRIGGER approval_requests_updated_at
  BEFORE UPDATE ON approval_requests
  FOR EACH ROW
  EXECUTE FUNCTION update_position_tracking_timestamp();

-- Function to refresh agent accuracy stats (called nightly)
CREATE OR REPLACE FUNCTION refresh_agent_accuracy_stats()
RETURNS void AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY agent_accuracy_stats;
END;
$$ LANGUAGE plpgsql;

-- Function to validate debate outcomes (runs 3-7 days after debate)
CREATE OR REPLACE FUNCTION validate_debate_outcome(
  p_debate_id UUID,
  p_current_price NUMERIC
)
RETURNS TEXT AS $$
DECLARE
  v_debate RECORD;
  v_price_change_pct NUMERIC;
  v_outcome TEXT;
BEGIN
  SELECT * INTO v_debate
  FROM agent_debate_outcomes
  WHERE id = p_debate_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Debate not found: %', p_debate_id;
  END IF;

  -- Calculate price change since debate
  v_price_change_pct := (
    (p_current_price - (v_debate.market_context->>'price')::numeric) /
    NULLIF((v_debate.market_context->>'price')::numeric, 0)
  ) * 100;

  -- Determine outcome based on price movement
  IF v_price_change_pct < -5 THEN
    -- Price dropped >5% → EXIT was correct
    IF v_debate.challenger_recommendation LIKE '%EXIT%' THEN
      v_outcome := 'challenger_correct';
    ELSIF v_debate.defender_recommendation LIKE '%HOLD%' OR v_debate.defender_recommendation LIKE '%BUY%' THEN
      v_outcome := 'defender_correct';
    ELSE
      v_outcome := 'inconclusive';
    END IF;
  ELSIF v_price_change_pct > 3 THEN
    -- Price up >3% → HOLD/BUY was correct
    IF v_debate.challenger_recommendation LIKE '%HOLD%' OR v_debate.challenger_recommendation LIKE '%BUY%' THEN
      v_outcome := 'challenger_correct';
    ELSIF v_debate.defender_recommendation LIKE '%EXIT%' THEN
      v_outcome := 'defender_correct';
    ELSE
      v_outcome := 'inconclusive';
    END IF;
  ELSE
    v_outcome := 'both_wrong';
  END IF;

  -- Update debate with outcome
  UPDATE agent_debate_outcomes
  SET
    actual_outcome = v_outcome,
    outcome_determined_at = NOW(),
    outcome_metrics = jsonb_build_object(
      'price_change_pct', v_price_change_pct,
      'days_since_debate', EXTRACT(DAY FROM NOW() - created_at),
      'validation_price', p_current_price
    )
  WHERE id = p_debate_id;

  RETURN v_outcome;
END;
$$ LANGUAGE plpgsql;

-- Function to timeout pending approvals
CREATE OR REPLACE FUNCTION timeout_pending_approvals()
RETURNS void AS $$
BEGIN
  UPDATE approval_requests
  SET status = 'timeout'
  WHERE status = 'pending'
  AND timeout_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres, anon, authenticated, service_role;

-- Comments
COMMENT ON TABLE agent_debate_outcomes IS 'Permanent record of agent debates with outcome validation';
COMMENT ON MATERIALIZED VIEW agent_accuracy_stats IS 'Agent win/loss records updated nightly';
COMMENT ON TABLE approval_requests IS 'Human escalation requests with 1-hour timeout';
COMMENT ON FUNCTION validate_debate_outcome IS 'Validates debate outcome 3-7 days later';
COMMENT ON FUNCTION refresh_agent_accuracy_stats IS 'Refreshes materialized view (call nightly)';
COMMENT ON FUNCTION timeout_pending_approvals IS 'Auto-timeout approvals after 1 hour';
