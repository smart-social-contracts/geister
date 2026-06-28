import json
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class DatabaseClient:
    def __init__(self):
        self.connection = None
        self.connect()
    
    def connect(self):
        try:
            self.connection = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                database=os.getenv('DB_NAME', 'geister_db'),
                user=os.getenv('DB_USER', 'geister_user'),
                password=os.getenv('DB_PASS', 'geister_pass'),
                port=os.getenv('DB_PORT', '5432')
            )
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
    
    def store_conversation(self, user_principal: str, realm_principal: str, 
                          question: str, response: str, prompt_context: str = None,
                          metadata: Dict = None, persona_name: str = 'ashoka',
                          agent_id: str = None, conversation_id: str = None,
                          context_realm: str = None) -> int:
        # The assistant is user-scoped; the realm is optional CONTEXT (#233).
        # `context_realm` defaults to `realm_principal` for backward-compatible callers.
        if context_realm is None:
            context_realm = realm_principal or None
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO conversations (user_principal, agent_id, realm_principal, context_realm, conversation_id, question, response, persona_name, prompt_context, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_principal, agent_id, realm_principal, context_realm, conversation_id, question, response, persona_name, prompt_context, json.dumps(metadata) if metadata else None))
                
                row_id = cursor.fetchone()[0]
                self.connection.commit()
                logger.info(f"Stored conversation row ID: {row_id} (thread: {conversation_id}) for user: {user_principal[:20]}... agent: {agent_id}")
                return row_id
        except Exception as e:
            logger.error(f"Failed to store conversation: {e}")
            self.connection.rollback()
            raise

    # =========================================================================
    # Chat sessions (multiple conversation threads per user+realm)
    # =========================================================================

    def create_chat_session(self, conversation_id: str, user_principal: str,
                            realm_principal: str, persona_name: str = 'ashoka',
                            title: str = None, context_realm: str = None) -> Dict:
        """Create a new chat session thread. Idempotent on conversation_id.

        The thread is owned by the user; `context_realm` is the optional realm it
        was started in (NULL = general mode). Defaults to `realm_principal`.
        """
        if context_realm is None:
            context_realm = realm_principal or None
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO chat_sessions (conversation_id, user_principal, realm_principal, context_realm, persona_name, title)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id) DO NOTHING
                    RETURNING conversation_id, user_principal, realm_principal, context_realm, persona_name, title, created_at, updated_at
                """, (conversation_id, user_principal, realm_principal, context_realm, persona_name, title))
                row = cursor.fetchone()
                self.connection.commit()
                if row:
                    return dict(row)
                return {"conversation_id": conversation_id}
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            self.connection.rollback()
            raise

    def list_chat_sessions(self, user_principal: str, context_realm: str = None,
                           limit: int = 50) -> List[Dict]:
        """List a user's chat session threads, newest first (#233).

        The assistant is user-scoped, so threads are listed BY USER across all
        realms + the registry. `context_realm` is an OPTIONAL filter:
          - None (default): every thread the user owns (global inbox).
          - a realm id: only threads started in that realm's context.
        Accepts the legacy `realm_principal` value transparently (it matches
        `context_realm` for backfilled rows).
        """
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                conditions = ["cs.user_principal = %s"]
                params: list = [user_principal]
                if context_realm:
                    # Match either the new context_realm or the legacy realm_principal
                    # so callers passing the old field still scope correctly.
                    conditions.append("(cs.context_realm = %s OR cs.realm_principal = %s)")
                    params.extend([context_realm, context_realm])
                params.append(limit)
                cursor.execute(f"""
                    SELECT cs.conversation_id, cs.title, cs.persona_name,
                           cs.context_realm, cs.realm_principal,
                           cs.created_at, cs.updated_at,
                           (SELECT COUNT(*) FROM conversations c
                              WHERE c.conversation_id = cs.conversation_id) AS message_count
                    FROM chat_sessions cs
                    WHERE {' AND '.join(conditions)}
                    ORDER BY cs.updated_at DESC
                    LIMIT %s
                """, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list chat sessions: {e}")
            return []

    def get_session_messages(self, conversation_id: str) -> List[Dict]:
        """Get all messages (question/response pairs) for a single thread, oldest first."""
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT question, response, persona_name, created_at
                    FROM conversations
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC
                """, (conversation_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get session messages: {e}")
            return []

    def rename_chat_session(self, conversation_id: str, title: str) -> bool:
        """Rename a chat session thread."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE chat_sessions SET title = %s, updated_at = NOW()
                    WHERE conversation_id = %s
                """, (title, conversation_id))
                updated = cursor.rowcount > 0
                self.connection.commit()
                return updated
        except Exception as e:
            logger.error(f"Failed to rename chat session: {e}")
            self.connection.rollback()
            return False

    def delete_chat_session(self, conversation_id: str) -> bool:
        """Delete a chat session thread and all of its messages."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("DELETE FROM conversations WHERE conversation_id = %s", (conversation_id,))
                cursor.execute("DELETE FROM chat_sessions WHERE conversation_id = %s", (conversation_id,))
                deleted = cursor.rowcount > 0
                self.connection.commit()
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete chat session: {e}")
            self.connection.rollback()
            return False

    def touch_chat_session(self, conversation_id: str, default_title: str = None) -> None:
        """Bump a session's updated_at, and set its title from the first question if still empty."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE chat_sessions
                    SET updated_at = NOW(),
                        title = COALESCE(NULLIF(title, ''), %s)
                    WHERE conversation_id = %s
                """, (default_title, conversation_id))
                self.connection.commit()
        except Exception as e:
            logger.error(f"Failed to touch chat session: {e}")
            self.connection.rollback()
    
    def get_conversation(self, conversation_id: int) -> Optional[Dict]:
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,))
                result = cursor.fetchone()
                if result:
                    result = dict(result)
                    if result['metadata']:
                        result['metadata'] = json.loads(result['metadata'])
                return result
        except Exception as e:
            logger.error(f"Failed to get conversation: {e}")
            return None
    
    def get_conversations_by_user(self, user_principal: str, limit: int = 10) -> List[Dict]:
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM conversations 
                    WHERE user_principal = %s 
                    ORDER BY created_at DESC 
                    LIMIT %s
                """, (user_principal, limit))
                
                results = []
                for row in cursor.fetchall():
                    result = dict(row)
                    if result['metadata']:
                        result['metadata'] = json.loads(result['metadata'])
                    results.append(result)
                return results
        except Exception as e:
            logger.error(f"Failed to get conversations by user: {e}")
            return []
    
    def get_conversation_history(self, user_principal: str, realm_principal: str = None, persona_name: str = None, agent_id: str = None, conversation_id: str = None, context_realm: str = None) -> List[Dict]:
        """Get conversation history for a user, optionally filtered by realm, persona and thread.

        User-scoped (#233): history is owned by the user. The realm is an OPTIONAL
        filter — when neither `realm_principal` nor `context_realm` is given, history
        aggregates across ALL of the user's realms + general-mode chats.

        When `conversation_id` is provided, history is scoped to that single thread
        (realm-independent), letting a user keep multiple independent conversations.
        """
        # Prefer the explicit context_realm; fall back to the legacy realm_principal.
        realm_filter = context_realm or realm_principal
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                # Build query based on provided filters
                conditions = ["user_principal = %s"]
                params = [user_principal]
                
                if conversation_id:
                    conditions.append("conversation_id = %s")
                    params.append(conversation_id)
                
                if agent_id:
                    conditions.append("agent_id = %s")
                    params.append(agent_id)
                
                if realm_filter:
                    # Match new context_realm or legacy realm_principal column.
                    conditions.append("(context_realm = %s OR realm_principal = %s)")
                    params.extend([realm_filter, realm_filter])
                
                if persona_name:
                    conditions.append("persona_name = %s")
                    params.append(persona_name)
                
                query = f"""
                    SELECT question, response, persona_name FROM conversations 
                    WHERE {' AND '.join(conditions)}
                    ORDER BY created_at ASC
                """
                cursor.execute(query, params)
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []
    
    def health_check(self) -> bool:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    def get_persona_usage_stats(self, realm_principal: str = None, days: int = 30) -> List[Dict]:
        """Get statistics on persona usage over the specified time period"""
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if realm_principal:
                    cursor.execute("""
                        SELECT 
                            persona_name,
                            COUNT(*) as usage_count,
                            COUNT(DISTINCT user_principal) as unique_users,
                            MIN(created_at) as first_used,
                            MAX(created_at) as last_used
                        FROM conversations 
                        WHERE realm_principal = %s 
                        AND created_at >= NOW() - INTERVAL '%s days'
                        GROUP BY persona_name
                        ORDER BY usage_count DESC
                    """, (realm_principal, days))
                else:
                    cursor.execute("""
                        SELECT 
                            persona_name,
                            COUNT(*) as usage_count,
                            COUNT(DISTINCT user_principal) as unique_users,
                            COUNT(DISTINCT realm_principal) as unique_realms,
                            MIN(created_at) as first_used,
                            MAX(created_at) as last_used
                        FROM conversations 
                        WHERE created_at >= NOW() - INTERVAL '%s days'
                        GROUP BY persona_name
                        ORDER BY usage_count DESC
                    """, (days,))
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get persona usage stats: {e}")
            return []

    def get_conversations_by_persona(self, persona_name: str, limit: int = 10) -> List[Dict]:
        """Get recent conversations for a specific persona"""
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM conversations 
                    WHERE persona_name = %s 
                    ORDER BY created_at DESC 
                    LIMIT %s
                """, (persona_name, limit))
                
                results = []
                for row in cursor.fetchall():
                    result = dict(row)
                    if result['metadata']:
                        result['metadata'] = json.loads(result['metadata'])
                    results.append(result)
                return results
        except Exception as e:
            logger.error(f"Failed to get conversations by persona: {e}")
            return []
    
    def close(self):
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")
