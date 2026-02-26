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
import random
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Human first names for agents
HUMAN_FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Dorothy", "Kevin", "Carol", "Brian", "Amanda", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Ruth",
    "Jose", "Julie", "Adam", "Olivia", "Nathan", "Joyce", "Henry", "Virginia",
    "Douglas", "Victoria", "Zachary", "Kelly", "Peter", "Lauren", "Kyle", "Christina"
]


def generate_human_name(agent_id: str = None) -> str:
    """Generate a consistent human name for an agent."""
    if agent_id:
        # Use agent_id to seed random for consistency
        random.seed(hash(agent_id) % (2**32))
    name = random.choice(HUMAN_FIRST_NAMES)
    if agent_id:
        random.seed()  # Reset seed
    return name


def generate_agent_background(persona: str = None) -> Dict:
    """Generate random background data for an agent based on persona."""
    
    # Base distributions
    ages = list(range(18, 75))
    wealth_levels = ["poor", "lower_middle", "middle", "upper_middle", "wealthy"]
    education_levels = ["none", "primary", "secondary", "vocational", "university", "postgraduate"]
    health_levels = ["poor", "fair", "good", "excellent"]
    occupations = [
        "farmer", "teacher", "engineer", "merchant", "artist", "healthcare_worker",
        "civil_servant", "laborer", "entrepreneur", "retired", "student", "unemployed"
    ]
    family_statuses = ["single", "married", "married_with_children", "divorced", "widowed"]
    locations = ["rural", "suburban", "urban"]
    
    # Persona-influenced distributions
    if persona == "exploiter":
        # Exploiters tend to be younger, more educated, urban
        age = random.choice(range(25, 50))
        wealth = random.choices(wealth_levels, weights=[5, 10, 30, 35, 20])[0]
        education = random.choices(education_levels, weights=[2, 5, 15, 20, 40, 18])[0]
        location = random.choices(locations, weights=[10, 30, 60])[0]
    elif persona == "watchful":
        # Watchful citizens tend to be older, experienced, varied backgrounds
        age = random.choice(range(35, 70))
        wealth = random.choices(wealth_levels, weights=[15, 25, 35, 20, 5])[0]
        education = random.choices(education_levels, weights=[5, 10, 25, 25, 25, 10])[0]
        location = random.choices(locations, weights=[30, 40, 30])[0]
    else:  # compliant or default
        # Compliant citizens - average distribution
        age = random.choice(ages)
        wealth = random.choices(wealth_levels, weights=[15, 25, 35, 20, 5])[0]
        education = random.choices(education_levels, weights=[5, 15, 30, 20, 25, 5])[0]
        location = random.choices(locations, weights=[25, 40, 35])[0]
    
    return {
        "age": age,
        "wealth": wealth,
        "education": education,
        "health": random.choice(health_levels),
        "occupation": random.choice(occupations),
        "family": random.choice(family_statuses),
        "location": location
    }


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
                    # Update last_active, session count, and optionally metadata
                    if metadata:
                        cursor.execute("""
                            UPDATE agent_profiles 
                            SET last_active_at = NOW(), 
                                total_sessions = total_sessions + 1,
                                persona = COALESCE(%s, persona),
                                metadata = %s
                            WHERE agent_id = %s
                            RETURNING *
                        """, (self.persona, json.dumps(metadata), self.agent_id))
                    else:
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
                    # Create new profile with auto-generated background
                    if not metadata:
                        metadata = generate_agent_background(self.persona)
                    # Use human name if no display_name provided
                    if not display_name:
                        # If agent_id is already a human-readable name (not swarm_agent_XXX format), use it directly
                        import re
                        if re.match(r'^swarm_agent_\d+$', self.agent_id):
                            display_name = generate_human_name(self.agent_id)
                        else:
                            display_name = self.agent_id
                    cursor.execute("""
                        INSERT INTO agent_profiles 
                        (agent_id, principal, display_name, persona, last_active_at, total_sessions, metadata)
                        VALUES (%s, %s, %s, %s, NOW(), 1, %s)
                        RETURNING *
                    """, (
                        self.agent_id,
                        self.principal,
                        display_name,
                        self.persona,
                        json.dumps(metadata)
                    ))
                    profile = cursor.fetchone()
                    
                    # Auto-assign telos to new agents (only if they don't already have one)
                    cursor.execute("SELECT id FROM agent_telos WHERE agent_id = %s LIMIT 1", (self.agent_id,))
                    existing_telos = cursor.fetchone()
                    if not existing_telos:
                        # Founders get the Realm Founder telos; everyone else gets the default
                        if self.persona == 'founder':
                            cursor.execute("SELECT id FROM telos_templates WHERE name = 'Realm Founder' LIMIT 1")
                        else:
                            cursor.execute("SELECT id FROM telos_templates WHERE is_default = TRUE LIMIT 1")
                        tpl = cursor.fetchone()
                        if tpl:
                            cursor.execute("""
                                INSERT INTO agent_telos (agent_id, telos_template_id, state, current_step, step_results)
                                VALUES (%s, %s, 'active', 0, '{}')
                            """, (self.agent_id, tpl['id']))
                
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
            return {"total": 0, "action_types": {}, "realms": []}
        
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


def get_agent_id_by_display_name(display_name: str) -> Optional[str]:
    """Look up agent_id by display_name (case-insensitive)."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'geister_db'),
            user=os.getenv('DB_USER', 'geister_user'),
            password=os.getenv('DB_PASS', 'geister_pass'),
            port=os.getenv('DB_PORT', '5432')
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT agent_id FROM agent_profiles WHERE LOWER(display_name) = LOWER(%s)",
                (display_name,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception:
        return None
    finally:
        if conn:
            conn.close()


def list_all_agents() -> List[Dict]:
    """List all agent profiles with their telos state."""
    conn = None
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
                SELECT p.agent_id, p.principal, p.display_name, p.persona, 
                       p.total_sessions, p.created_at, p.last_active_at,
                       p.metadata,
                       t.state as telos_state, t.current_step, t.custom_telos,
                       tt.name as telos_name, tt.steps as telos_steps
                FROM agent_profiles p
                LEFT JOIN agent_telos t ON p.agent_id = t.agent_id
                LEFT JOIN telos_templates tt ON t.telos_template_id = tt.id
                ORDER BY p.last_active_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        raise DatabaseConnectionError(f"Database connection required: {e}")
    finally:
        if conn:
            conn.close()


# =============================================================================
# Telos Management Functions
# =============================================================================

def _get_db_connection():
    """Get a database connection."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        database=os.getenv('DB_NAME', 'geister_db'),
        user=os.getenv('DB_USER', 'geister_user'),
        password=os.getenv('DB_PASS', 'geister_pass'),
        port=os.getenv('DB_PORT', '5432')
    )


def _ensure_is_default_column():
    """Ensure is_default column exists in telos_templates."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE telos_templates 
                ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE
            """)
            conn.commit()
    except Exception:
        pass  # Column may already exist
    finally:
        if conn:
            conn.close()

# Run migration on module load
try:
    _ensure_is_default_column()
except:
    pass


def _seed_default_telos_template():
    """Seed the default Citizen Onboarding template if it doesn't exist."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Check if default template exists
            cursor.execute("SELECT id FROM telos_templates WHERE name = 'Citizen Onboarding'")
            if cursor.fetchone() is None:
                # Create the default template
                steps = [
                    'Find a realm you like',
                    'Join the realm',
                    'Set your avatar',
                    'Use db_get with entity_type Invoice to list your pending invoices',
                    'Use pay_invoice for each pending invoice (pass invoice_id, amount, and the vault canister ID as recipient)',
                    'Vote on proposals',
                    'Create a proposal'
                ]
                cursor.execute("""
                    INSERT INTO telos_templates (name, description, steps, is_default)
                    VALUES (%s, %s, %s, TRUE)
                """, ('Citizen Onboarding', 'Steps for new citizens to get started', json.dumps(steps)))
                conn.commit()
    except Exception:
        pass  # Template may already exist or DB not ready
    finally:
        if conn:
            conn.close()

def _seed_founder_telos_template():
    """Seed the Realm Founder template if it doesn't exist."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id FROM telos_templates WHERE name = 'Realm Founder'")
            if cursor.fetchone() is None:
                steps = [
                    'Use registry_redeem_voucher to redeem voucher code BETA50 with your principal to get credits',
                    'Use registry_get_credits to check your credit balance and confirm you have at least 5 credits',
                    'Use registry_deploy_realm to deploy a new realm with a creative name',
                    'Use registry_deploy_status with wait=true to wait for deployment to complete',
                    'Join the newly created realm as admin using join_realm with profile=admin'
                ]
                cursor.execute("""
                    INSERT INTO telos_templates (name, description, steps)
                    VALUES (%s, %s, %s)
                """, ('Realm Founder', 'Redeem credits, deploy a new realm, and join it as admin', json.dumps(steps)))
                conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

# Seed templates on module load
try:
    _seed_default_telos_template()
    _seed_founder_telos_template()
except:
    pass


def list_telos_templates() -> List[Dict]:
    """List all telos templates."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, name, description, steps, is_default, created_at, updated_at
                FROM telos_templates
                ORDER BY is_default DESC, name
            """)
            return [dict(row) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()


def get_telos_template(template_id: int) -> Optional[Dict]:
    """Get a specific telos template."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM telos_templates WHERE id = %s",
                (template_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        if conn:
            conn.close()


def create_telos_template(name: str, description: str, steps: List[str]) -> Dict:
    """Create a new telos template."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                INSERT INTO telos_templates (name, description, steps)
                VALUES (%s, %s, %s)
                RETURNING *
            """, (name, description, json.dumps(steps)))
            result = cursor.fetchone()
            conn.commit()
            return dict(result)
    finally:
        if conn:
            conn.close()


def update_telos_template(template_id: int, name: str = None, description: str = None, steps: List[str] = None) -> Optional[Dict]:
    """Update a telos template."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            updates = []
            values = []
            if name is not None:
                updates.append("name = %s")
                values.append(name)
            if description is not None:
                updates.append("description = %s")
                values.append(description)
            if steps is not None:
                updates.append("steps = %s")
                values.append(json.dumps(steps))
            
            if not updates:
                return get_telos_template(template_id)
            
            updates.append("updated_at = NOW()")
            values.append(template_id)
            
            cursor.execute(f"""
                UPDATE telos_templates SET {', '.join(updates)}
                WHERE id = %s RETURNING *
            """, values)
            result = cursor.fetchone()
            conn.commit()
            return dict(result) if result else None
    finally:
        if conn:
            conn.close()


def set_default_template(template_id: int) -> Optional[Dict]:
    """Set a template as the default (only one can be default)."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Clear existing default
            cursor.execute("UPDATE telos_templates SET is_default = FALSE WHERE is_default = TRUE")
            # Set new default
            cursor.execute(
                "UPDATE telos_templates SET is_default = TRUE WHERE id = %s RETURNING *",
                (template_id,)
            )
            result = cursor.fetchone()
            conn.commit()
            return dict(result) if result else None
    finally:
        if conn:
            conn.close()


def get_default_template() -> Optional[Dict]:
    """Get the default telos template."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM telos_templates WHERE is_default = TRUE LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        if conn:
            conn.close()


def delete_telos_template(template_id: int) -> bool:
    """Delete a telos template."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM telos_templates WHERE id = %s", (template_id,))
            conn.commit()
            return cursor.rowcount > 0
    finally:
        if conn:
            conn.close()


def get_agent_telos(agent_id: str) -> Optional[Dict]:
    """Get an agent's current telos assignment."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT t.*, tt.name as template_name, tt.description as template_description, tt.steps as template_steps
                FROM agent_telos t
                LEFT JOIN telos_templates tt ON t.telos_template_id = tt.id
                WHERE t.agent_id = %s
                ORDER BY t.created_at DESC LIMIT 1
            """, (agent_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        if conn:
            conn.close()


def assign_telos_to_agent(agent_id: str, template_id: int = None, custom_telos: str = None) -> Dict:
    """Assign a telos to an agent (template or custom)."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Remove any existing telos for this agent
            cursor.execute("DELETE FROM agent_telos WHERE agent_id = %s", (agent_id,))
            
            # Create new assignment
            cursor.execute("""
                INSERT INTO agent_telos (agent_id, telos_template_id, custom_telos, state)
                VALUES (%s, %s, %s, 'idle')
                RETURNING *
            """, (agent_id, template_id, custom_telos))
            result = cursor.fetchone()
            conn.commit()
            return dict(result)
    finally:
        if conn:
            conn.close()


def update_agent_telos_state(agent_id: str, state: str) -> Optional[Dict]:
    """Update an agent's telos state (idle, active, completed, failed)."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            updates = ["state = %s", "updated_at = NOW()"]
            values = [state]
            
            if state == 'active':
                updates.append("started_at = COALESCE(started_at, NOW())")
            elif state in ('completed', 'failed'):
                updates.append("completed_at = NOW()")
            
            values.append(agent_id)
            cursor.execute(f"""
                UPDATE agent_telos SET {', '.join(updates)}
                WHERE agent_id = %s RETURNING *
            """, values)
            result = cursor.fetchone()
            conn.commit()
            return dict(result) if result else None
    finally:
        if conn:
            conn.close()


def update_all_agents_telos_state(state: str) -> int:
    """Update all agents' telos state. Returns count of updated agents.
    
    If state is 'active', also assigns default telos to agents without one.
    """
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            # If activating, first assign default telos to agents without one
            if state == 'active':
                default_template = get_default_template()
                if default_template:
                    template_id = default_template['id']
                    # Get all agents without a telos
                    cursor.execute("""
                        SELECT agent_id FROM agent_profiles 
                        WHERE agent_id NOT IN (SELECT agent_id FROM agent_telos)
                    """)
                    agents_without_telos = cursor.fetchall()
                    
                    for (agent_id,) in agents_without_telos:
                        cursor.execute("""
                            INSERT INTO agent_telos (agent_id, telos_template_id, state, current_step, step_results, started_at)
                            VALUES (%s, %s, 'active', 0, '{}', NOW())
                        """, (agent_id, template_id))
            
            # Now update all existing telos records
            updates = ["state = %s", "updated_at = NOW()"]
            values = [state]
            
            if state == 'active':
                updates.append("started_at = COALESCE(started_at, NOW())")
            elif state in ('completed', 'failed'):
                updates.append("completed_at = NOW()")
            
            cursor.execute(f"UPDATE agent_telos SET {', '.join(updates)}", values)
            conn.commit()
            return cursor.rowcount
    finally:
        if conn:
            conn.close()


def update_agent_telos_progress(agent_id: str, current_step: int, step_result: Dict = None) -> Optional[Dict]:
    """Update an agent's telos progress."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if step_result:
                cursor.execute("""
                    UPDATE agent_telos 
                    SET current_step = %s, 
                        step_results = step_results || %s,
                        updated_at = NOW()
                    WHERE agent_id = %s RETURNING *
                """, (current_step, json.dumps({str(current_step): step_result}), agent_id))
            else:
                cursor.execute("""
                    UPDATE agent_telos SET current_step = %s, updated_at = NOW()
                    WHERE agent_id = %s RETURNING *
                """, (current_step, agent_id))
            result = cursor.fetchone()
            conn.commit()
            return dict(result) if result else None
    finally:
        if conn:
            conn.close()


def remove_agent_telos(agent_id: str) -> bool:
    """Remove an agent's telos assignment."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agent_telos WHERE agent_id = %s", (agent_id,))
            conn.commit()
            return cursor.rowcount > 0
    finally:
        if conn:
            conn.close()


def delete_agent(agent_id: str) -> bool:
    """Delete an agent and all associated data (telos, memories)."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agent_telos WHERE agent_id = %s", (agent_id,))
            cursor.execute("DELETE FROM agent_memories WHERE agent_id = %s", (agent_id,))
            cursor.execute("DELETE FROM agent_profiles WHERE agent_id = %s", (agent_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    finally:
        if conn:
            conn.close()


def get_all_events(
    agent_id: str = None,
    persona: str = None,
    action_type: str = None,
    telos_name: str = None,
    since: str = None,
    search: str = None,
    success_filter: str = None,
    limit: int = 100
) -> List[Dict]:
    """Get events across all agents for the monitor page.
    
    Args:
        agent_id: Filter by specific agent
        persona: Filter by persona type
        action_type: Filter by event type (telos_step, session, join, vote, etc.)
        telos_name: Filter by telos template name
        since: ISO timestamp - only return events after this time
        search: Free-text search on action_summary
        success_filter: 'success', 'error', or None for all
        limit: Max events to return
    """
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            conditions = []
            params = []

            if agent_id:
                conditions.append("m.agent_id = %s")
                params.append(agent_id)

            if persona:
                conditions.append("m.persona = %s")
                params.append(persona)

            if action_type:
                conditions.append("m.action_type = %s")
                params.append(action_type)

            if telos_name:
                conditions.append("tt.name = %s")
                params.append(telos_name)

            if since:
                conditions.append("m.created_at > %s")
                params.append(since)

            if search:
                conditions.append("(m.action_summary ILIKE %s OR m.observations ILIKE %s)")
                params.extend([f"%{search}%", f"%{search}%"])

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            params.append(limit)
            cursor.execute(f"""
                SELECT m.id, m.agent_id, m.principal, COALESCE(m.persona, p.persona) as persona, m.realm_principal,
                       m.action_type, m.action_summary, m.action_details,
                       m.emotional_state, m.observations, m.created_at,
                       p.display_name,
                       tt.name as telos_name,
                       at.current_step as telos_current_step,
                       at.state as telos_state
                FROM agent_memories m
                LEFT JOIN agent_profiles p ON m.agent_id = p.agent_id
                LEFT JOIN agent_telos at ON m.agent_id = at.agent_id
                LEFT JOIN telos_templates tt ON at.telos_template_id = tt.id
                {where_clause}
                ORDER BY m.created_at DESC
                LIMIT %s
            """, params)

            results = []
            for row in cursor.fetchall():
                event = dict(row)
                # Parse action_details if string
                if event.get('action_details') and isinstance(event['action_details'], str):
                    try:
                        event['action_details'] = json.loads(event['action_details'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Determine success from action_details or action_type
                details = event.get('action_details') or {}
                if isinstance(details, dict):
                    result_text = details.get('result', '')
                    error_text = details.get('error', '')
                    debug_chain = details.get('debug_chain', [])
                    # Check for errors in debug chain
                    has_error = bool(error_text)
                    if not has_error and isinstance(debug_chain, list):
                        for item in debug_chain:
                            if isinstance(item, dict) and 'error' in str(item.get('content', '')).lower():
                                has_error = True
                                break
                    event['success'] = not has_error
                else:
                    event['success'] = True
                # Serialize datetime
                if event.get('created_at'):
                    event['created_at'] = event['created_at'].isoformat()
                results.append(event)

            # Apply success filter after computing success
            if success_filter == 'success':
                results = [e for e in results if e.get('success')]
            elif success_filter == 'error':
                results = [e for e in results if not e.get('success')]

            return results
    finally:
        if conn:
            conn.close()


def get_event_filter_options() -> Dict:
    """Get available filter options for the monitor page."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT action_type FROM agent_memories ORDER BY action_type")
            action_types = [row[0] for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT persona FROM agent_memories WHERE persona IS NOT NULL ORDER BY persona")
            personas = [row[0] for row in cursor.fetchall()]

            cursor.execute("""
                SELECT DISTINCT p.agent_id, p.display_name
                FROM agent_profiles p
                ORDER BY p.display_name
            """)
            agents = [{"agent_id": row[0], "display_name": row[1]} for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT name FROM telos_templates ORDER BY name")
            telos_names = [row[0] for row in cursor.fetchall()]

            return {
                "action_types": action_types,
                "personas": personas,
                "agents": agents,
                "telos_names": telos_names
            }
    finally:
        if conn:
            conn.close()


def delete_all_agents() -> int:
    """Delete all agents and all associated data. Returns count of deleted agents."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agent_telos")
            cursor.execute("DELETE FROM agent_memories")
            cursor.execute("DELETE FROM agent_profiles")
            count = cursor.rowcount
            conn.commit()
            return count
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
