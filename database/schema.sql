CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_principal TEXT NOT NULL,
    agent_id TEXT,                        -- Agent identity (e.g., swarm_agent_001)
    realm_principal TEXT NOT NULL,
    conversation_id TEXT,                 -- Groups messages into a single chat thread (UUID)
    question TEXT NOT NULL,
    response TEXT NOT NULL,
    persona_name TEXT NOT NULL DEFAULT 'ashoka',
    prompt_context TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add conversation_id to existing deployments (no-op if already present)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS conversation_id TEXT;

-- User-scoped assistant (issue #233): the assistant is owned by the USER, and the
-- realm is optional CONTEXT (general mode when absent). `context_realm` supersedes
-- `realm_principal` as the meaningful field; `realm_principal` is kept for
-- backward-compat and is allowed to be empty for context-free (general) chats.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_realm TEXT;
-- Backfill existing rows: their realm IS their context.
UPDATE conversations SET context_realm = realm_principal
    WHERE context_realm IS NULL AND realm_principal IS NOT NULL AND realm_principal <> '';
-- Relax the legacy NOT NULL so general-mode (no realm) rows can be stored.
ALTER TABLE conversations ALTER COLUMN realm_principal DROP NOT NULL;

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_conversations_persona_name ON conversations(persona_name);
CREATE INDEX IF NOT EXISTS idx_conversations_user_realm_persona ON conversations(user_principal, realm_principal, persona_name);
CREATE INDEX IF NOT EXISTS idx_conversations_user_agent ON conversations(user_principal, agent_id);
CREATE INDEX IF NOT EXISTS idx_conversations_conversation_id ON conversations(conversation_id);
-- User-scoped listing/aggregation (realm-independent).
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_principal, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user_context ON conversations(user_principal, context_realm);

GRANT ALL PRIVILEGES ON TABLE conversations TO geister_user;
GRANT USAGE, SELECT ON SEQUENCE conversations_id_seq TO geister_user;

-- Chat sessions: one row per conversation thread (for listing/renaming in the UI)
CREATE TABLE IF NOT EXISTS chat_sessions (
    conversation_id TEXT PRIMARY KEY,     -- UUID shared with conversations.conversation_id
    user_principal TEXT NOT NULL,
    realm_principal TEXT,                 -- Legacy; nullable for general-mode threads (#233)
    context_realm TEXT,                   -- Optional realm CONTEXT; NULL = general mode
    persona_name TEXT DEFAULT 'ashoka',
    title TEXT,                           -- Human-readable thread title (auto from first question)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User-scoped assistant migration (#233): realm becomes optional context.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_realm TEXT;
UPDATE chat_sessions SET context_realm = realm_principal
    WHERE context_realm IS NULL AND realm_principal IS NOT NULL AND realm_principal <> '';
ALTER TABLE chat_sessions ALTER COLUMN realm_principal DROP NOT NULL;

-- Primary listing is BY USER (realm-independent); realm is an optional filter.
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_principal, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_realm ON chat_sessions(user_principal, realm_principal, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_context ON chat_sessions(user_principal, context_realm, updated_at DESC);

GRANT ALL PRIVILEGES ON TABLE chat_sessions TO geister_user;

-- Agent memories table for persistent agent life stories
CREATE TABLE IF NOT EXISTS agent_memories (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,              -- dfx identity name (e.g., swarm_agent_001)
    principal TEXT,                       -- IC principal for this agent
    persona TEXT,                         -- Persona type (compliant, exploiter, watchful)
    realm_principal TEXT,                 -- Which realm this memory is for
    action_type TEXT NOT NULL,            -- join, vote, observe, analyze, etc.
    action_summary TEXT NOT NULL,         -- Brief description of what happened
    action_details JSONB,                 -- Full details (tool calls, results, etc.)
    emotional_state TEXT,                 -- How the agent "felt" about this
    observations TEXT,                    -- What the agent noticed/learned
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent identity table for persistent agent profiles
CREATE TABLE IF NOT EXISTS agent_profiles (
    id SERIAL PRIMARY KEY,
    agent_id TEXT UNIQUE NOT NULL,        -- dfx identity name
    principal TEXT,                       -- IC principal
    display_name TEXT,                    -- Human-readable name
    persona TEXT,                         -- Default persona
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP,
    total_sessions INTEGER DEFAULT 0,
    metadata JSONB                        -- Additional profile data
);

-- Indexes for agent tables
CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_id ON agent_memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_realm ON agent_memories(agent_id, realm_principal);
CREATE INDEX IF NOT EXISTS idx_agent_memories_created_at ON agent_memories(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_profiles_agent_id ON agent_profiles(agent_id);

GRANT ALL PRIVILEGES ON TABLE agent_memories TO geister_user;
GRANT USAGE, SELECT ON SEQUENCE agent_memories_id_seq TO geister_user;
GRANT ALL PRIVILEGES ON TABLE agent_profiles TO geister_user;
GRANT USAGE, SELECT ON SEQUENCE agent_profiles_id_seq TO geister_user;

-- Telos templates (reusable mission definitions)
CREATE TABLE IF NOT EXISTS telos_templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    steps JSONB NOT NULL,              -- Array of step descriptions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent telos assignments
CREATE TABLE IF NOT EXISTS agent_telos (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    telos_template_id INTEGER REFERENCES telos_templates(id) ON DELETE SET NULL,
    custom_telos TEXT,                 -- Free-form telos if not using template
    current_step INTEGER DEFAULT 0,
    step_results JSONB DEFAULT '{}',   -- {"0": {"status": "completed", "result": "..."}, ...}
    state TEXT DEFAULT 'idle',         -- 'idle', 'active', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for telos tables
CREATE INDEX IF NOT EXISTS idx_agent_telos_agent_id ON agent_telos(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_telos_state ON agent_telos(state);

GRANT ALL PRIVILEGES ON TABLE telos_templates TO geister_user;
GRANT USAGE, SELECT ON SEQUENCE telos_templates_id_seq TO geister_user;
GRANT ALL PRIVILEGES ON TABLE agent_telos TO geister_user;
GRANT USAGE, SELECT ON SEQUENCE agent_telos_id_seq TO geister_user;
