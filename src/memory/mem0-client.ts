/**
 * Mem0 Client - Agent Working Memory Integration
 *
 * Provides two layers of memory:
 * 1. Short-term: Session-based working memory (24h TTL)
 * 2. Long-term: Supermemory knowledge graph (permanent)
 *
 * Usage:
 * - Guardian battles: Agents share findings via session memory
 * - Learning: Consolidate session outcomes to long-term knowledge
 * - Forensic replay: Query historical decisions with mcp_exec_id
 */

import MemoryClient from "mem0ai";
import { createClient, SupabaseClient } from "@supabase/supabase-js";

export interface Mem0Config {
  apiKey: string;
  supabaseUrl: string;
  supabaseKey: string;
  organizationId?: string;
}

export interface Memory {
  id: string;
  content: string;
  metadata: Record<string, any>;
  embedding?: number[];
  created_at: string;
  updated_at: string;
}

export interface SearchOptions {
  limit?: number;
  threshold?: number;
}

export interface Knowledge {
  category: "user_preference" | "pattern" | "guardian_verdict" | "institutional_signal" | "agent_accuracy_pattern";
  content: string;
  metadata: Record<string, any>;
  confidence: number;
  mcp_exec_id?: string;
}

export class Mem0Integration {
  private mem0Client: MemoryClient;
  private supabase: SupabaseClient;

  constructor(config: Mem0Config) {
    this.mem0Client = new MemoryClient({
      apiKey: config.apiKey,
      organizationId: config.organizationId,
    });

    this.supabase = createClient(config.supabaseUrl, config.supabaseKey);
  }

  // ===== SHORT-TERM WORKING MEMORY (24h TTL) =====

  /**
   * Add memory to session (Guardian battle agent sharing)
   */
  async add(sessionId: string, content: string, metadata: Record<string, any> = {}): Promise<void> {
    await this.mem0Client.add({
      messages: [{ role: "user", content }],
      userId: sessionId,
      metadata,
    });
  }

  /**
   * Search session memories (agents query each other's findings)
   */
  async search(query: string, sessionId: string, options: SearchOptions = {}): Promise<Memory[]> {
    const results = await this.mem0Client.search(query, {
      userId: sessionId,
      limit: options.limit || 10,
    });

    return results.map(r => ({
      id: r.id,
      content: r.memory,
      metadata: r.metadata || {},
      created_at: r.created_at || new Date().toISOString(),
      updated_at: r.updated_at || new Date().toISOString(),
    }));
  }

  /**
   * Get all memories for a session (Judge needs all agent proposals)
   */
  async getAll(sessionId: string): Promise<Memory[]> {
    const results = await this.mem0Client.getAll({
      userId: sessionId,
    });

    return results.map(r => ({
      id: r.id,
      content: r.memory,
      metadata: r.metadata || {},
      created_at: r.created_at || new Date().toISOString(),
      updated_at: r.updated_at || new Date().toISOString(),
    }));
  }

  /**
   * Delete session memories (after consolidation)
   */
  async delete(sessionId: string): Promise<void> {
    const memories = await this.getAll(sessionId);

    for (const memory of memories) {
      await this.mem0Client.delete(memory.id);
    }
  }

  // ===== LONG-TERM KNOWLEDGE (Supermemory) =====

  /**
   * Add knowledge to permanent storage
   */
  async addKnowledge(knowledge: Knowledge): Promise<void> {
    // Generate embedding for semantic search
    const embedding = await this.generateEmbedding(knowledge.content);

    const { error } = await this.supabase
      .from("supermemory_knowledge")
      .insert({
        category: knowledge.category,
        content: knowledge.content,
        embedding,
        metadata: knowledge.metadata,
        confidence: knowledge.confidence,
        mcp_exec_id: knowledge.mcp_exec_id,
      });

    if (error) {
      throw new Error(`Failed to add knowledge: ${error.message}`);
    }
  }

  /**
   * Search long-term knowledge (semantic search)
   */
  async searchKnowledge(query: string, options: SearchOptions = {}): Promise<Knowledge[]> {
    const queryEmbedding = await this.generateEmbedding(query);

    const { data, error } = await this.supabase.rpc("match_supermemory_knowledge", {
      query_embedding: queryEmbedding,
      match_threshold: options.threshold || 0.7,
      match_count: options.limit || 10,
    });

    if (error) {
      throw new Error(`Knowledge search failed: ${error.message}`);
    }

    return data.map((d: any) => ({
      category: d.category,
      content: d.content,
      metadata: d.metadata,
      confidence: d.confidence,
      mcp_exec_id: d.mcp_exec_id,
    }));
  }

  /**
   * Get user preferences for a symbol
   */
  async getUserPreferences(symbol: string): Promise<Knowledge[]> {
    const { data, error } = await this.supabase
      .from("supermemory_knowledge")
      .select("*")
      .eq("category", "user_preference")
      .eq("symbol", symbol)
      .order("created_at", { ascending: false })
      .limit(5);

    if (error) {
      throw new Error(`Failed to get preferences: ${error.message}`);
    }

    return data.map((d: any) => ({
      category: d.category,
      content: d.content,
      metadata: d.metadata,
      confidence: d.confidence,
      mcp_exec_id: d.mcp_exec_id,
    }));
  }

  /**
   * Get learned patterns matching criteria
   */
  async getPatterns(criteria: Record<string, any>): Promise<Knowledge[]> {
    let query = this.supabase
      .from("supermemory_knowledge")
      .select("*")
      .eq("category", "pattern");

    // Filter by metadata criteria
    for (const [key, value] of Object.entries(criteria)) {
      query = query.filter(`metadata->>${key}`, "eq", value);
    }

    const { data, error } = await query
      .order("confidence", { ascending: false })
      .limit(10);

    if (error) {
      throw new Error(`Failed to get patterns: ${error.message}`);
    }

    return data.map((d: any) => ({
      category: d.category,
      content: d.content,
      metadata: d.metadata,
      confidence: d.confidence,
      mcp_exec_id: d.mcp_exec_id,
    }));
  }

  /**
   * Consolidate session memories to long-term knowledge
   */
  async consolidateSession(sessionId: string, execId: string): Promise<void> {
    const { error } = await this.supabase.rpc("consolidate_session_memories", {
      p_session_id: sessionId,
      p_exec_id: execId,
    });

    if (error) {
      throw new Error(`Consolidation failed: ${error.message}`);
    }
  }

  /**
   * Get forensic context for an agent decision
   */
  async getAgentDecisionContext(
    agentName: string,
    symbol: string,
    date: Date = new Date()
  ): Promise<any> {
    const { data, error } = await this.supabase.rpc("agent_decision_context", {
      p_agent_name: agentName,
      p_symbol: symbol,
      p_date: date.toISOString().split("T")[0],
    });

    if (error) {
      throw new Error(`Failed to get context: ${error.message}`);
    }

    return data[0] || null;
  }

  /**
   * Get battle context (all data from a Guardian battle)
   */
  async getBattleContext(execId: string): Promise<any> {
    const { data, error } = await this.supabase.rpc("get_battle_context", {
      p_exec_id: execId,
    });

    if (error) {
      throw new Error(`Failed to get battle context: ${error.message}`);
    }

    return data[0] || null;
  }

  // ===== PRIVATE HELPERS =====

  private async generateEmbedding(text: string): Promise<number[]> {
    // TODO: Use OpenAI embeddings API
    // For now, return mock embedding
    // In production, replace with:
    // const response = await openai.embeddings.create({
    //   model: "text-embedding-3-small",
    //   input: text,
    // });
    // return response.data[0].embedding;

    return new Array(1536).fill(0).map(() => Math.random());
  }
}

// ===== SINGLETON INSTANCE =====

let mem0Instance: Mem0Integration | null = null;

export function getMem0Client(): Mem0Integration {
  if (!mem0Instance) {
    const config: Mem0Config = {
      apiKey: process.env.MEM0_API_KEY || "",
      supabaseUrl: process.env.SUPABASE_URL || "",
      supabaseKey: process.env.SUPABASE_SERVICE_KEY || "",
      organizationId: process.env.MEM0_ORG_ID,
    };

    mem0Instance = new Mem0Integration(config);
  }

  return mem0Instance;
}

// ===== HELPER FUNCTIONS FOR SQL =====

/**
 * Create SQL function for vector similarity search
 * Run this in Supabase SQL editor:
 */
export const VECTOR_SEARCH_FUNCTION = `
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
`;
