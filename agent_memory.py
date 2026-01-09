#!/usr/bin/env python3
"""
Agent Memory - Persistent memory storage for citizen agents.

Stores agent life stories, actions, and observations in Postgres.
Each agent has a profile and a journal of memories from their sessions.

Database connection is REQUIRED - agents cannot run without memory.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Raised when database connection fails."""
    pass


class AgentMemory:
    """Manages persistent memory for citizen agents. Requires database connection."""
    
    def __init__(self, agent_id: str, principal: str = None, persona: str = None):
        """
        Initialize agent memory. Raises DatabaseConnectionError if DB unavailable.
        
        Args:
            agent_id: Unique agent identifier (dfx identity name)
            principal: IC principal for this agent
            persona: Persona type (compliant, exploiter, watchful)
        
        Raises:
            DatabaseConnectionError: If database connection fails
        """
        self.agent_id = agent_id
        self.principal = principal
        self.persona = persona
        self.connection = None
        self._connect()
    
    def _connect(self):
        """Connect to Postgres database. Raises on failure."""
        try:
            self.connection = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                database=os.getenv('DB_NAME', 'geister_db'),
                user=os.getenv('DB_USER', 'geister_user'),
                password=os.getenv('DB_PASS', 'geister_pass'),
                port=os.getenv('DB_PORT', '5432')
            )
            logger.info(f"Agent memory connected for {self.agent_id}")
        except Exception as e:
            raise DatabaseConnectionError(f"Database connection required but failed: {e}")
    
    # =========================================================================
    # Profile Management
    # =========================================================================
    
    def ensure_profile(self, display_name: str = None, metadata: Dict = None) -> Dict:
        """
        Ensure agent profile exists, create if not.
        
        Returns the profile dict.
        """
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                # Check if profile exists
                cursor.execute(
                    "SELECT * FROM agent_profiles WHERE agent_id = %s",
                    (self.agent_id,)
                )
                profile = cursor.fetchone()
                
                if profile:
                    # Update last_active and session count
                    cursor.execute("""
                        UPDATE agent_profiles 
                        SET last_active_at = NOW(), 
                            total_sessions = total_sessions + 1,
                            persona = COALESCE(%s, persona)
                        WHERE agent_id = %s
                        RETURNING *
                    """, (self.persona, self.agent_id))
                    profile = cursor.fetchone()
                else:
                    # Create new profile
                    cursor.execute("""
                        INSERT INTO agent_profiles 
                        (agent_id, principal, display_name, persona, last_active_at, total_sessions, metadata)
                        VALUES (%s, %s, %s, %s, NOW(), 1, %s)
                        RETURNING *
                    """, (
                        self.agent_id,
                        self.principal,
                        display_name or self.agent_id,
                        self.persona,
                        json.dumps(metadata) if metadata else None
                    ))
                    profile = cursor.fetchone()
                
                self.connection.commit()
                return dict(profile) if profile else {}
                
        except Exception as e:
            logger.error(f"Error ensuring profile: {e}")
            self.connection.rollback()
            raise
    
    def get_profile(self) -> Optional[Dict]:
        """Get agent profile."""
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM agent_profiles WHERE agent_id = %s",
                    (self.agent_id,)
                )
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting profile: {e}")
            raise
    
    # =========================================================================
    # Memory Storage
    # =========================================================================
    
    def remember(
        self,
        action_type: str,
        action_summary: str,
        realm_principal: str = None,
        action_details: Dict = None,
        emotional_state: str = None,
        observations: str = None
    ) -> int:
        """
        Store a memory of an action taken.
        
        Args:
            action_type: Type of action (join, vote, observe, analyze, transfer, etc.)
            action_summary: Brief human-readable summary
            realm_principal: Which realm this happened in
            action_details: Full details as dict (tool calls, results)
            emotional_state: How the agent "felt" (satisfied, suspicious, concerned, etc.)
            observations: What the agent noticed or learned
        
        Returns:
            Memory ID
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO agent_memories 
                    (agent_id, principal, persona, realm_principal, action_type, 
                     action_summary, action_details, emotional_state, observations)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    self.agent_id,
                    self.principal,
                    self.persona,
                    realm_principal,
                    action_type,
                    action_summary,
                    json.dumps(action_details) if action_details else None,
                    emotional_state,
                    observations
                ))
                memory_id = cursor.fetchone()[0]
                self.connection.commit()
                logger.info(f"Stored memory {memory_id}: {action_type}")
                return memory_id
        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            self.connection.rollback()
            raise
    
    def recall(
        self,
        realm_principal: str = None,
        action_type: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Recall memories, optionally filtered by realm or action type.
        
        Returns memories ordered by most recent first.
        """
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                query = "SELECT * FROM agent_memories WHERE agent_id = %s"
                params = [self.agent_id]
                
                if realm_principal:
                    query += " AND realm_principal = %s"
                    params.append(realm_principal)
                
                if action_type:
                    query += " AND action_type = %s"
                    params.append(action_type)
                
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                
                results = []
                for row in cursor.fetchall():
                    memory = dict(row)
                    if memory.get('action_details') and isinstance(memory['action_details'], str):
                        memory['action_details'] = json.loads(memory['action_details'])
                    results.append(memory)
                
                return results
        except Exception as e:
            logger.error(f"Error recalling memories: {e}")
            raise
    
    def recall_recent(self, limit: int = 10) -> List[Dict]:
        """Recall most recent memories."""
        return self.recall(limit=limit)
    
    def recall_for_realm(self, realm_principal: str, limit: int = 20) -> List[Dict]:
        """Recall memories for a specific realm."""
        return self.recall(realm_principal=realm_principal, limit=limit)
    
    # =========================================================================
    # Memory Formatting for LLM Context
    # =========================================================================
    
    def get_life_story_prompt(self, realm_principal: str = None, max_memories: int = 20) -> str:
        """
        Generate a prompt section summarizing the agent's life story.
        
        This is injected into the system prompt so the agent "remembers" past actions.
        """
        profile = self.get_profile()
        memories = self.recall(realm_principal=realm_principal, limit=max_memories)
        
        lines = ["YOUR LIFE STORY:"]
        
        if profile:
            sessions = profile.get('total_sessions', 1)
            created = profile.get('created_at', 'unknown')
            lines.append(f"- You have been active for {sessions} session(s) since {created}")
        
        if memories:
            lines.append(f"- You have {len(memories)} memories from past sessions:")
            lines.append("")
            
            for memory in reversed(memories):  # Oldest first for narrative
                timestamp = memory.get('created_at', '')
                if isinstance(timestamp, datetime):
                    timestamp = timestamp.strftime('%Y-%m-%d %H:%M')
                
                action_type = memory.get('action_type', 'unknown')
                summary = memory.get('action_summary', '')
                emotional = memory.get('emotional_state', '')
                observations = memory.get('observations', '')
                
                entry = f"  [{timestamp}] {action_type.upper()}: {summary}"
                if emotional:
                    entry += f" (felt: {emotional})"
                lines.append(entry)
                
                if observations:
                    lines.append(f"    → Observation: {observations}")
        else:
            lines.append("- This is your first session in this realm.")
        
        return "\n".join(lines)
    
    def get_memory_summary(self, realm_principal: str = None) -> Dict:
        """Get a summary of agent's memories."""
        memories = self.recall(realm_principal=realm_principal, limit=100)
        
        if not memories:
            return {"total": 0, "action_types": {}, "realms": set()}
        
        action_counts = {}
        realms = set()
        
        for m in memories:
            action_type = m.get('action_type', 'unknown')
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
            if m.get('realm_principal'):
                realms.add(m['realm_principal'])
        
        return {
            "total": len(memories),
            "action_types": action_counts,
            "realms": list(realms),
            "first_memory": memories[-1].get('created_at') if memories else None,
            "last_memory": memories[0].get('created_at') if memories else None
        }
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()


# =============================================================================
# Convenience Functions
# =============================================================================

def get_agent_memory(agent_id: str, principal: str = None, persona: str = None) -> AgentMemory:
    """Get an AgentMemory instance for the given agent. Raises if DB unavailable."""
    return AgentMemory(agent_id, principal, persona)


def list_all_agents() -> List[Dict]:
    """List all agent profiles."""
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'geister_db'),
            user=os.getenv('DB_USER', 'geister_user'),
            password=os.getenv('DB_PASS', 'geister_pass'),
            port=os.getenv('DB_PORT', '5432')
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT agent_id, principal, display_name, persona, 
                       total_sessions, created_at, last_active_at
                FROM agent_profiles 
                ORDER BY last_active_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        raise DatabaseConnectionError(f"Database connection required: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    print("Agent Memory System")
    print("=" * 50)
    
    try:
        memory = AgentMemory("test_agent_001", principal="test-principal", persona="compliant")
        print("✓ Connected to database")
        
        profile = memory.ensure_profile(display_name="Test Agent")
        print(f"Profile: {profile.get('agent_id')} (sessions: {profile.get('total_sessions')})")
        
        memory_id = memory.remember(
            action_type="test",
            action_summary="Testing the memory system",
            emotional_state="curious",
            observations="The system seems to work!"
        )
        print(f"Stored memory ID: {memory_id}")
        
        memories = memory.recall_recent(5)
        print(f"Recent memories: {len(memories)}")
        
        story = memory.get_life_story_prompt()
        print(f"\nLife Story:\n{story}")
        
        memory.close()
        
    except DatabaseConnectionError as e:
        print(f"✗ {e}")
        print("\nDatabase is REQUIRED. Please ensure Postgres is running.")
        exit(1)
