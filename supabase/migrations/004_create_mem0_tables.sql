-- Migration 004: Mem0 Integration Tables
-- Description: Vector storage for agent working memory and learned patterns
-- Dependencies: 003_create_agent_debates.sql, pgvector extension

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Mem0 short-term working memory (24-hour TTL)
CREATE TABLE IF NOT EXISTS mem0_vectors (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL, -- Session ID for guardian battles
  content TEXT NOT NULL,
  embedding VECTOR(1536), -- OpenAI ada-002 dimension
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast vector search
CREATE INDEX idx_mem0_vectors_user_id ON mem0_vectors(user_id);
CREATE INDEX idx_mem0_vectors_embedding ON mem0_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_mem0_vectors_created_at ON mem0_vectors(created_at);

-- Supermemory long-term knowledge graph (permanent)
CREATE TABLE IF NOT EXISTS supermemory_knowledge (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  category TEXT NOT NULL CHECK (category IN (
    'user_preference',
    'agent_accuracy_pattern',
    'institutional_signal',
    'guardian_verdict',
    'market_pattern'
  )),
  content TEXT NOT NULL,
  embedding VECTOR(1536),
  metadata JSONB DEFAULT '{}'::jsonb,
  confidence NUMERIC CHECK (confidence BETWEEN 0 AND 1),

  -- CRITICAL: Link to exact market snapshot
  mcp_exec_id TEXT, -- Links to exec_sessions.exec_id for forensic replay

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_supermemory_knowledge_category ON supermemory_knowledge(category);
CREATE INDEX idx_supermemory_knowledge_embedding ON supermemory_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_supermemory_knowledge_mcp_exec_id ON supermemory_knowledge(mcp_exec_id);
CREATE INDEX idx_supermemory_knowledge_confidence ON supermemory_knowledge(confidence DESC);

-- Generated columns for easier querying
ALTER TABLE supermemory_knowledge
  ADD COLUMN IF NOT EXISTS symbol TEXT GENERATED ALWAYS AS (metadata->>'symbol') STORED,
  ADD COLUMN IF NOT EXISTS source TEXT GENERATED ALWAYS AS (metadata->>'source') STORED,
  ADD COLUMN IF NOT EXISTS agent_id TEXT GENERATED ALWAYS AS (metadata->>'agent') STORED;

CREATE INDEX idx_supermemory_knowledge_symbol ON supermemory_knowledge(symbol) WHERE symbol IS NOT NULL;
CREATE INDEX idx_supermemory_knowledge_agent_id ON supermemory_knowledge(agent_id) WHERE agent_id IS NOT NULL;

-- Auto-update timestamps
CREATE TRIGGER mem0_vectors_updated_at
  BEFORE UPDATE ON mem0_vectors
  FOR EACH ROW
  EXECUTE FUNCTION update_position_tracking_timestamp();

CREATE TRIGGER supermemory_knowledge_updated_at
  BEFORE UPDATE ON supermemory_knowledge
  FOR EACH ROW
  EXECUTE FUNCTION update_position_tracking_timestamp();

-- Auto-cleanup function for expired mem0 sessions
CREATE OR REPLACE FUNCTION cleanup_expired_mem0_sessions()
RETURNS void AS $$
BEGIN
  DELETE FROM mem0_vectors
  WHERE created_at < NOW() - INTERVAL '24 hours';
END;
$$ LANGUAGE plpgsql;

-- Function to consolidate session memories to supermemory
CREATE OR REPLACE FUNCTION consolidate_session_to_supermemory(
  p_session_id TEXT,
  p_exec_id TEXT DEFAULT NULL
)
RETURNS INT AS $$
DECLARE
  v_consolidated_count INT := 0;
  v_memory RECORD;
BEGIN
  FOR v_memory IN
    SELECT * FROM mem0_vectors
    WHERE user_id = p_session_id
  LOOP
    -- Pattern 1: User Feedback → User Preference
    IF v_memory.content ~* '(approved|rejected)' THEN
      INSERT INTO supermemory_knowledge (
        category,
        content,
        embedding,
        metadata,
        confidence,
        mcp_exec_id
      ) VALUES (
        'user_preference',
        v_memory.content,
        v_memory.embedding,
        v_memory.metadata || jsonb_build_object('session_id', p_session_id),
        1.0,
        p_exec_id
      );
      v_consolidated_count := v_consolidated_count + 1;
    END IF;

    -- Pattern 2: Guardian Verdict
    IF v_memory.metadata->>'agent' = 'options-judge' THEN
      INSERT INTO supermemory_knowledge (
        category,
        content,
        embedding,
        metadata,
        confidence,
        mcp_exec_id
      ) VALUES (
        'guardian_verdict',
        v_memory.content,
        v_memory.embedding,
        v_memory.metadata || jsonb_build_object('session_id', p_session_id),
        COALESCE((v_memory.metadata->>'winner_score')::numeric / 10, 0.5),
        p_exec_id
      );
      v_consolidated_count := v_consolidated_count + 1;
    END IF;

    -- Pattern 3: Institutional Signal
    IF v_memory.metadata->>'finding_type' = 'institutional_signal' THEN
      INSERT INTO supermemory_knowledge (
        category,
        content,
        embedding,
        metadata,
        confidence,
        mcp_exec_id
      ) VALUES (
        'institutional_signal',
        v_memory.content,
        v_memory.embedding,
        v_memory.metadata || jsonb_build_object('session_id', p_session_id),
        0.8,
        p_exec_id
      );
      v_consolidated_count := v_consolidated_count + 1;
    END IF;
  END LOOP;

  -- Cleanup session memories after consolidation
  DELETE FROM mem0_vectors WHERE user_id = p_session_id;

  RETURN v_consolidated_count;
END;
$$ LANGUAGE plpgsql;

-- Function to decay confidence of incorrect predictions
CREATE OR REPLACE FUNCTION decay_incorrect_predictions()
RETURNS void AS $$
BEGIN
  -- Decay confidence for patterns that led to wrong agent predictions
  UPDATE supermemory_knowledge sk
  SET confidence = GREATEST(0, confidence - 0.05)
  WHERE category = 'agent_accuracy_pattern'
  AND EXISTS (
    SELECT 1 FROM agent_debate_outcomes ado
    WHERE ado.actual_outcome = 'both_wrong'
    AND ado.created_at > sk.created_at
    AND ado.created_at < sk.created_at + INTERVAL '7 days'
    -- Match agent pattern to debate
    AND (
      ado.challenger_agent = sk.agent_id OR
      ado.defender_agent = sk.agent_id
    )
  );
END;
$$ LANGUAGE plpgsql;

-- Function to archive low-confidence knowledge
CREATE OR REPLACE FUNCTION archive_low_confidence_knowledge()
RETURNS void AS $$
BEGIN
  -- Move low-confidence (<0.2) knowledge to archive table
  -- This is a placeholder - implement archive table if needed
  DELETE FROM supermemory_knowledge
  WHERE confidence < 0.2
  AND created_at < NOW() - INTERVAL '90 days';
END;
$$ LANGUAGE plpgsql;

-- Function to search supermemory by semantic similarity
CREATE OR REPLACE FUNCTION search_supermemory(
  p_query_embedding VECTOR(1536),
  p_category TEXT DEFAULT NULL,
  p_min_confidence NUMERIC DEFAULT 0.3,
  p_limit INT DEFAULT 10
)
RETURNS TABLE(
  id UUID,
  content TEXT,
  similarity NUMERIC,
  metadata JSONB,
  confidence NUMERIC,
  mcp_exec_id TEXT
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    sk.id,
    sk.content,
    1 - (sk.embedding <=> p_query_embedding) AS similarity,
    sk.metadata,
    sk.confidence,
    sk.mcp_exec_id
  FROM supermemory_knowledge sk
  WHERE
    (p_category IS NULL OR sk.category = p_category)
    AND sk.confidence >= p_min_confidence
  ORDER BY sk.embedding <=> p_query_embedding
  LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres, anon, authenticated, service_role;

-- Comments
COMMENT ON TABLE mem0_vectors IS 'Short-term working memory for guardian battles (24h TTL)';
COMMENT ON TABLE supermemory_knowledge IS 'Long-term learned patterns with forensic replay capability';
COMMENT ON COLUMN supermemory_knowledge.mcp_exec_id IS 'CRITICAL: Links to exact market snapshot for forensic analysis';
COMMENT ON FUNCTION cleanup_expired_mem0_sessions IS 'Daily cleanup of 24h+ old session memories';
COMMENT ON FUNCTION consolidate_session_to_supermemory IS 'Converts session memories to permanent knowledge';
COMMENT ON FUNCTION decay_incorrect_predictions IS 'Reduces confidence for patterns that led to wrong predictions';
COMMENT ON FUNCTION search_supermemory IS 'Semantic search with confidence filtering';
