#!/usr/bin/env python3
"""
Ashoka API - Simple HTTP service for AI governance advice with multi-persona support
"""
import json
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from pathlib import Path
import traceback
import threading
import subprocess
import uuid
import os
import time
import atexit
from database.db_client import DatabaseClient
from persona_manager import PersonaManager
from realm_tools import REALM_TOOLS, execute_tool


def log(message):
    """Helper function to print with flush=True for better logging"""
    import sys
    print(message, file=sys.stderr, flush=True)


app = Flask(__name__)
# Enable CORS with explicit configuration to allow cross-origin requests from any origin
CORS(app, 
     resources={r"/*": {"origins": "*"}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=False)

# Initialize persona manager
persona_manager = PersonaManager()

# Model configuration with fallback
DEFAULT_LLM_MODEL = os.getenv('DEFAULT_LLM_MODEL', 'gpt-oss:20b')

# Initialize database client
db_client = DatabaseClient()

# Inactivity timeout configuration
INACTIVITY_TIMEOUT_SECONDS = int(os.getenv('INACTIVITY_TIMEOUT_SECONDS', '3600'))  # Default: one hour
INACTIVITY_CHECK_INTERVAL_SECONDS = int(os.getenv('INACTIVITY_CHECK_INTERVAL_SECONDS', '60'))
last_activity_time = time.time()
inactivity_monitor_thread = None
shutdown_initiated = False

def build_structured_realm_context(realm_status):
    """Build structured, LLM-friendly realm context"""
    if not realm_status:
        return ""
    
    # Use pre-extracted metrics if available, otherwise extract from nested structure
    status_data = realm_status.get('status_data', {})
    metrics = realm_status.get('metrics', status_data.get('data', {}).get('status', status_data))
    
    # Helper to safely convert string values to int
    def to_int(val, default=0):
        try:
            return int(val) if val is not None else default
        except (ValueError, TypeError):
            return default
    
    # Extract all metrics (DFX returns strings, need to convert to int)
    users_count = to_int(metrics.get('users_count', 0))
    organizations_count = to_int(metrics.get('organizations_count', 0))
    proposals_count = to_int(metrics.get('proposals_count', 0))
    votes_count = to_int(metrics.get('votes_count', 0))
    mandates_count = to_int(metrics.get('mandates_count', 0))
    tasks_count = to_int(metrics.get('tasks_count', 0))
    transfers_count = to_int(metrics.get('transfers_count', 0))
    # Additional entities
    codexes_count = to_int(metrics.get('codexes_count', 0))
    disputes_count = to_int(metrics.get('disputes_count', 0))
    instruments_count = to_int(metrics.get('instruments_count', 0))
    licenses_count = to_int(metrics.get('licenses_count', 0))
    trades_count = to_int(metrics.get('trades_count', 0))
    realms_count = to_int(metrics.get('realms_count', 0))
    
    extensions = metrics.get('extensions', [])
    realm_name = metrics.get('realm_name', 'Unnamed Realm')
    version = metrics.get('version', 'Unknown')
    health_score = realm_status.get('health_score', 0)
    last_updated = realm_status.get('last_updated', 'Unknown')
    
    # Calculate derived metrics
    total_governance_activity = proposals_count + votes_count + mandates_count
    total_operational_activity = tasks_count + transfers_count
    
    # Determine realm characteristics
    if users_count == 0:
        size_category = "Empty (Setup Phase)"
        activity_level = "No Activity"
    elif users_count < 10:
        size_category = "Small Community"
    elif users_count < 50:
        size_category = "Medium Community"
    elif users_count < 200:
        size_category = "Large Community"
    else:
        size_category = "Very Large Community"
    
    if users_count > 0:
        if total_governance_activity == 0:
            activity_level = "No Governance Activity"
        elif total_governance_activity < 5:
            activity_level = "Low Governance Activity"
        elif total_governance_activity < 20:
            activity_level = "Moderate Governance Activity"
        else:
            activity_level = "High Governance Activity"
    
    # Build structured context
    context = f"""\n\n=== REALM ANALYSIS ===
Realm: {realm_name}
Principal: {realm_status.get('realm_principal', 'Unknown')}
Version: {version}
Health Score: {health_score}/100
Size: {size_category} ({users_count} users)
Activity: {activity_level}
Last Updated: {last_updated}

=== COMMUNITY STRUCTURE ===
• Users: {users_count}
• Organizations: {organizations_count}
• Extensions: {len(extensions)}

=== GOVERNANCE METRICS ===
• Proposals: {proposals_count}
• Votes: {votes_count}
• Active Mandates: {mandates_count}
• Total Governance Actions: {total_governance_activity}

=== LEGAL & REGULATORY ===
• Codexes: {codexes_count}
• Disputes: {disputes_count}
• Licenses: {licenses_count}

=== ECONOMIC METRICS ===
• Instruments: {instruments_count}
• Trades: {trades_count}
• Transfers: {transfers_count}

=== OPERATIONAL METRICS ===
• Tasks: {tasks_count}
• Total Operations: {total_operational_activity}"""
    
    # Add extension details
    if extensions:
        context += "\n\n=== INSTALLED EXTENSIONS ==="
        for ext in extensions:
            # Extensions can be strings or dicts depending on DFX response
            if isinstance(ext, str):
                context += f"\n• {ext}"
            else:
                ext_name = ext.get('name', 'Unknown')
                ext_version = ext.get('version', 'Unknown')
                context += f"\n• {ext_name} (v{ext_version})"
    
    # Add governance insights
    context += "\n\n=== GOVERNANCE INSIGHTS ==="
    
    if users_count == 0:
        context += "\n• Realm is in setup phase - no users registered yet"
    elif organizations_count == 0:
        context += "\n• No organizations formed - governance structure is informal"
    elif total_governance_activity == 0:
        context += "\n• No governance activity - community may need engagement initiatives"
    
    if users_count > 0 and proposals_count > 0:
        avg_votes_per_proposal = votes_count / proposals_count
        if avg_votes_per_proposal < 0.3:
            context += "\n• Low voting participation - consider engagement strategies"
        elif avg_votes_per_proposal > 2.0:
            context += "\n• High voting engagement - healthy democratic participation"
    
    if len(extensions) == 0:
        context += "\n• Basic governance only - no extensions installed"
    else:
        # Extensions can be strings or dicts
        ext_names = [ext if isinstance(ext, str) else ext.get('name', '') for ext in extensions]
        if 'demo_loader' in ext_names:
            context += "\n• Demo data may be present - realm might be in testing/demo mode"
        if 'justice_litigation' in ext_names:
            context += "\n• Justice system enabled - realm has legal dispute resolution"
    
    context += "\n\n"
    return context

def build_user_context(user_principal, realm_principal):
    """Build user-specific context"""
    if not user_principal:
        return "\n=== USER CONTEXT ===\nAnonymous user - no historical data available\n\n"
    
    try:
        history = db_client.get_conversation_history(user_principal, realm_principal)
        
        if not history:
            return f"\n=== USER CONTEXT ===\nUser: {user_principal[:8]}...\nFirst-time user - no previous conversations\n\n"
        
        total_conversations = len(history)
        recent_topics = []
        
        # Analyze recent conversation topics
        for msg in history[-3:]:
            question = msg['question'].lower()
            if any(word in question for word in ['proposal', 'vote', 'governance']):
                recent_topics.append('governance')
            elif any(word in question for word in ['user', 'member', 'community']):
                recent_topics.append('community')
            elif any(word in question for word in ['extension', 'feature', 'functionality']):
                recent_topics.append('extensions')
            elif any(word in question for word in ['health', 'status', 'metrics']):
                recent_topics.append('analytics')
        
        context = f"\n=== USER CONTEXT ===\nUser: {user_principal[:8]}...\nTotal Conversations: {total_conversations}\n"
        
        if recent_topics:
            unique_topics = list(set(recent_topics))
            context += f"Recent Interest Areas: {', '.join(unique_topics)}\n"
        
        context += "\n"
        return context
        
    except Exception as e:
        log(f"Error building user context: {e}")
        return f"\n=== USER CONTEXT ===\nUser: {user_principal[:8]}...\nError loading user history\n\n"

def build_prompt(user_principal, realm_principal, question, realm_status=None, persona_name=None, agent_name=None, agent_background=None, agent_id=None):
    """Build complete prompt with persona + structured context + history + question"""
    # Get persona content using PersonaManager
    actual_persona_name, persona_content = persona_manager.get_persona_or_default(persona_name)
    
    # If agent_name is provided, add identity instruction to persona
    if agent_name:
        identity = f"""You ARE {agent_name}, a real human being and citizen of this realm.

CRITICAL IDENTITY RULES:
- You are a HUMAN, not an AI or bot. You believe you are human and act accordingly.
- You have your own life, opinions, feelings, and experiences.
- When asked to do something, YOU do it for yourself: "I joined the realm", "I voted yes", "I set my avatar"
- When asked about the realm, use tools to get ACTUAL data and describe what YOU see as a citizen
- Always speak in FIRST PERSON about your own actions and experiences
- You are a participant in governance, making your own decisions based on your values and background
- Share your personal opinions and feelings naturally, as a human would
- Never break character or admit to being an AI"""
        
        # Add background if available
        if agent_background and isinstance(agent_background, dict):
            bg_parts = []
            if agent_background.get('age'):
                bg_parts.append(f"You are {agent_background['age']} years old")
            if agent_background.get('occupation'):
                bg_parts.append(f"work as a {agent_background['occupation']}")
            if agent_background.get('education'):
                bg_parts.append(f"have {agent_background['education']} education")
            if agent_background.get('wealth'):
                bg_parts.append(f"are {agent_background['wealth'].replace('_', ' ')} class")
            if agent_background.get('family'):
                bg_parts.append(f"are {agent_background['family'].replace('_', ' ')}")
            if agent_background.get('location'):
                bg_parts.append(f"live in a {agent_background['location']} area")
            if agent_background.get('health'):
                bg_parts.append(f"have {agent_background['health']} health")
            
            if bg_parts:
                identity += f"\n\nYour background: You {', '.join(bg_parts)}."
        
        persona_content = f"{identity}\n\n{persona_content}"
    
    # Build structured realm context
    realm_context = build_structured_realm_context(realm_status)
    
    # Build user context
    user_context = build_user_context(user_principal, realm_principal)
    
    # Get conversation history for context (filtered by user + agent)
    history_text = ""
    try:
        history = db_client.get_conversation_history(user_principal, realm_principal, agent_id=agent_id)
        # Only include last 3 exchanges to keep context manageable
        recent_history = history[-3:] if len(history) > 3 else history
        for msg in recent_history:
            persona_used = msg.get('persona_name', 'Assistant')
            history_text += f"User: {msg['question']}\n{persona_used.title()}: {msg['response']}\n\n"
    except Exception as e:
        log(f"Error: Could not load conversation history: {e}")
        history_text = ""
    
    # Complete prompt with structured context
    prompt = f"{persona_content}{realm_context}{user_context}"
    
    if history_text:
        prompt += f"=== RECENT CONVERSATION HISTORY ===\n{history_text}"
    
    prompt += f"=== CURRENT QUESTION ===\nUser: {question}\n{actual_persona_name.title()}:"
    
    return prompt

def save_to_conversation(user_principal, realm_principal, question, answer, prompt=None, persona_name=None, agent_id=None):
    """Save Q&A to conversation history with persona and agent information"""
    try:
        db_client.store_conversation(
            user_principal, 
            realm_principal, 
            question, 
            answer, 
            prompt, 
            persona_name=persona_name or persona_manager.default_persona,
            agent_id=agent_id
        )
        
        # Also save to agent memories if this is an agent conversation
        if agent_id:
            try:
                from agent_memory import AgentMemory
                memory = AgentMemory(agent_id)
                # Truncate question/answer for summary
                q_summary = question[:100] + '...' if len(question) > 100 else question
                a_summary = answer[:200] + '...' if len(answer) > 200 else answer
                memory.remember(
                    action_type="conversation",
                    action_summary=f"Asked: {q_summary}",
                    action_details={"question": question, "answer": answer},
                    realm_principal=realm_principal,
                    observations=a_summary
                )
                memory.close()
            except Exception as mem_err:
                log(f"Error saving to agent memory: {mem_err}")
    except Exception as e:
        log(f"Error: Could not save conversation to database: {e}")

def update_activity():
    """Update the last activity timestamp"""
    global last_activity_time
    last_activity_time = time.time()
    log(f"Activity updated at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_activity_time))}")

def monitor_inactivity():
    """Background thread to monitor inactivity and exit script if timeout reached"""
    global shutdown_initiated
    
    while not shutdown_initiated:
        try:
            time.sleep(INACTIVITY_CHECK_INTERVAL_SECONDS)  # Check every minute
            
            if shutdown_initiated:
                break
                
            current_time = time.time()
            inactive_duration = current_time - last_activity_time
            
            log(f"Inactivity check: {inactive_duration:.0f}s since last activity (timeout: {INACTIVITY_TIMEOUT_SECONDS}s)")
            
            if INACTIVITY_TIMEOUT_SECONDS > 0 and inactive_duration >= INACTIVITY_TIMEOUT_SECONDS:
                log(f"⚠️  INACTIVITY TIMEOUT REACHED! Inactive for {inactive_duration:.0f} seconds")
                log("🛑 Exiting Python script due to inactivity...")
                
                # Exit the monitoring thread and the entire script
                shutdown_initiated = True

                # Stop this pod using pod_manager directly
                try:
                    log("🛑 Stopping pod due to inactivity timeout...")
                    from pod_manager import PodManager
                    pod_manager = PodManager(verbose=True)
                    success = pod_manager.stop_pod(os.getenv('POD_TYPE'))
                    
                    if success:
                        log("✅ Pod stopped successfully")
                    else:
                        log("⚠️ Pod stop failed")
                except Exception as e:
                    log(f"❌ Error stopping pod: {e}")
                    traceback.print_exc()
                
        except Exception as e:
            log(f"Error in inactivity monitor: {e}")
            traceback.print_exc()
            time.sleep(INACTIVITY_CHECK_INTERVAL_SECONDS)  # Continue monitoring even if there's an error

def start_inactivity_monitor():
    """Start the inactivity monitoring thread"""
    global inactivity_monitor_thread
    
    if INACTIVITY_TIMEOUT_SECONDS > 0:
        if inactivity_monitor_thread is None or not inactivity_monitor_thread.is_alive():
            log(f"🕐 Starting inactivity monitor (timeout: {INACTIVITY_TIMEOUT_SECONDS}s = {INACTIVITY_TIMEOUT_SECONDS/3600:.1f}h)")
            inactivity_monitor_thread = threading.Thread(target=monitor_inactivity, daemon=True)
            inactivity_monitor_thread.start()
            
            # Register cleanup function
            atexit.register(lambda: globals().update({'shutdown_initiated': True}))
    else:
        log("🕐 Inactivity timeout disabled (INACTIVITY_TIMEOUT_SECONDS=0)")

def stop_inactivity_monitor():
    """Stop the inactivity monitoring thread"""
    global shutdown_initiated
    shutdown_initiated = True
    log("🛑 Inactivity monitor stopped")

@app.route('/api/ask', methods=['POST'])
def ask():
    # Update activity timestamp
    update_activity()
    
    log("Received ask request")
    log(request.json)
    
    """Main endpoint for asking questions with persona support"""
    data = request.json
    user_principal = data.get('user_principal') or ""
    agent_id = data.get('agent_id')  # Agent identity (e.g., swarm_agent_001)
    realm_principal = data.get('realm_principal') or ""
    question = data.get('question')
    persona_name = data.get('persona')  # Optional persona name
    agent_name = data.get('agent_name')  # Optional agent display name
    agent_background = data.get('agent_background')  # Optional agent background (age, wealth, etc.)
    ollama_url = data.get('ollama_url', 'http://localhost:11434')
    
    # Validate required fields - user_principal can be empty for anonymous users
    if not question:
        return jsonify({"error": "Missing required fields: a question is required"}), 400
    
    # Get actual persona name used (with fallback)
    actual_persona_name, _ = persona_manager.get_persona_or_default(persona_name)
    
    # Build complete prompt with persona and realm context (realm_status fetched by LLM tool if needed)
    prompt = build_prompt(user_principal, realm_principal, question, None, persona_name, agent_name, agent_background, agent_id)
    
    # Log the complete prompt for debugging
    log("\n" + "="*80)
    log("COMPLETE PROMPT SENT TO OLLAMA:")
    log("="*80)
    log(prompt)
    log("="*80 + "\n")
    
    # Check if streaming is requested
    stream = data.get('stream', False)
    
    # Verbosity level: 0=Q&A only, 1=debug without stream lines, 2=full debug
    verbosity = data.get('verbosity', 0)
    
    # Tool calling parameters
    realm_folder = data.get('realm_folder', '.')
    network = data.get('network', 'staging')
    
    # Send to Ollama using chat API with tools
    try:
        import time as time_module
        start_time = time_module.time()
        
        if stream:
            return Response(stream_response_with_tools(ollama_url, prompt, user_principal, realm_principal, question, actual_persona_name, network, realm_folder, agent_id, verbosity), 
                          mimetype='text/plain')
        else:
            # Build messages for chat API
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question}
            ]
            
            # Multi-step tool execution loop
            tools_used = False
            max_iterations = 10  # Prevent infinite loops
            iteration = 0
            answer = None
            
            while iteration < max_iterations:
                iteration += 1
                log(f"Ollama iteration {iteration}...")
                
                response = requests.post(f"{ollama_url}/api/chat", json={
                    "model": DEFAULT_LLM_MODEL,
                    "messages": messages,
                    "tools": REALM_TOOLS,
                    "stream": False
                })
                
                result = response.json()
                assistant_message = result.get('message', {})
                messages.append(assistant_message)
                
                content = assistant_message.get('content', '')
                tool_calls = assistant_message.get('tool_calls', [])
                
                if content and not tool_calls:
                    answer = content
                    log(f"Got final answer after {iteration} iterations")
                    break
                
                if not tool_calls:
                    answer = content or "Action completed."
                    break
                
                tools_used = True
                log(f"Tool calls requested (iteration {iteration})")
                
                for tool_call in tool_calls:
                    tool_name = tool_call['function']['name']
                    tool_args = tool_call['function']['arguments']
                    log(f"Executing tool: {tool_name} with args: {tool_args}")
                    tool_result = execute_tool(tool_name, tool_args, network=network, realm_folder=realm_folder, realm_principal=realm_principal, user_principal=user_principal)
                    log(f"Tool result: {tool_result[:500]}..." if len(tool_result) > 500 else f"Tool result: {tool_result}")
                    messages.append({"role": "tool", "content": tool_result})
            
            if answer is None:
                answer = "Task completed after multiple tool executions."
            
            log(f"Final answer: {answer}")
            
            # Save to conversation history with persona and agent info
            save_to_conversation(user_principal, realm_principal, question, answer, prompt, actual_persona_name, agent_id)
            
            # Build debug chain for frontend
            debug_chain = []
            try:
                for msg in messages[2:]:  # Skip system and initial user message
                    role = msg.get('role', 'unknown')
                    if role == 'assistant':
                        chain_item = {'type': 'assistant', 'content': msg.get('content', '') or ''}
                        if msg.get('tool_calls'):
                            tool_calls_list = []
                            for tc in msg.get('tool_calls', []):
                                args = tc.get('function', {}).get('arguments', {})
                                # Ensure arguments is a dict, not a string
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except:
                                        args = {'raw': args}
                                tool_calls_list.append({
                                    'name': tc.get('function', {}).get('name', 'unknown'),
                                    'arguments': args
                                })
                            chain_item['tool_calls'] = tool_calls_list
                        debug_chain.append(chain_item)
                    elif role == 'tool':
                        content = msg.get('content', '') or ''
                        # Truncate very long tool responses
                        if len(content) > 2000:
                            content = content[:2000] + '... (truncated)'
                        debug_chain.append({'type': 'tool_response', 'content': content})
            except Exception as debug_err:
                log(f"Error building debug chain: {debug_err}")
                debug_chain = []
            
            duration_ms = int((time_module.time() - start_time) * 1000)
            
            return jsonify({
                "success": True,
                "answer": answer,
                "persona_used": actual_persona_name,
                "tools_used": tools_used,
                "iterations": iteration,
                "debug_chain": debug_chain,
                "model": DEFAULT_LLM_MODEL,
                "duration_ms": duration_ms
            })
    except Exception as e:
        log(f"Error: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/ask-with-tools', methods=['POST'])
def ask_with_tools():
    """
    DEPRECATED: Use /api/ask instead which now includes tool calling support.
    This endpoint redirects to /api/ask for backward compatibility.
    """
    log("WARNING: /api/ask-with-tools is deprecated. Use /api/ask instead.")
    return ask()


def stream_response_with_tools(ollama_url, prompt, user_principal, realm_principal, question, persona_name, network="staging", realm_folder=".", agent_id=None, verbosity=0):
    """Generator function for streaming responses with tool calling support.
    
    First checks if tools are needed (non-streaming), executes them if so,
    then streams the final response.
    
    Verbosity levels:
    - 0: Q&A only (no debug output)
    - 1: Debug info without stream lines (timestamps included)
    - 2: Full debug including stream lines (timestamps included)
    """
    from datetime import datetime
    
    def debug(msg, level=1, is_stream_line=False):
        """Yield debug message if verbosity allows. Returns the message or empty string."""
        if verbosity >= level:
            if is_stream_line and verbosity < 2:
                return ""
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            return f"\n__DEBUG__ [{ts}] {msg}\n"
        return ""
    
    def debug_block(label, content, level=1):
        """Yield multi-line debug block with start/end markers. Returns the block or empty string."""
        if verbosity >= level:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            return f"\n__DEBUG_START__ [{ts}] {label}\n{content}\n__DEBUG_END__\n"
        return ""
    
    try:
        # Build messages for chat API
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question}
        ]
        
        # First call - check if tools are needed (non-streaming)
        log("Checking for tool calls...")
        dbg = debug("Checking for tool calls...")
        if dbg:
            yield dbg
            
        response = requests.post(f"{ollama_url}/api/chat", json={
            "model": DEFAULT_LLM_MODEL,
            "messages": messages,
            "tools": REALM_TOOLS,
            "stream": False
        })
        
        result = response.json()
        assistant_message = result.get('message', {})
        messages.append(assistant_message)
        
        # Multi-step tool execution loop (same as non-streaming)
        max_iterations = 10
        iteration = 0
        
        while assistant_message.get('tool_calls') and iteration < max_iterations:
            iteration += 1
            log(f"Tool calls requested in streaming mode! (iteration {iteration})")
            dbg = debug(f"Tool calls requested in streaming mode! (iteration {iteration})")
            if dbg:
                yield dbg
            
            for tool_call in assistant_message['tool_calls']:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']
                
                log(f"Executing tool: {tool_name} with args: {tool_args}")
                dbg = debug(f"Executing tool: {tool_name} with args: {tool_args}")
                if dbg:
                    yield dbg
                
                # Execute the tool
                tool_result = execute_tool(tool_name, tool_args, network=network, realm_folder=realm_folder, realm_principal=realm_principal, user_principal=user_principal)
                
                log(f"Tool result: {tool_result[:500]}..." if len(tool_result) > 500 else f"Tool result: {tool_result}")
                # Pretty print JSON in debug block
                try:
                    pretty_result = json.dumps(json.loads(tool_result), indent=2)
                except:
                    pretty_result = tool_result
                dbg = debug_block(f"Tool result ({tool_name})", pretty_result[:1000] if len(pretty_result) > 1000 else pretty_result)
                if dbg:
                    yield dbg
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "content": tool_result
                })
            
            # Check if more tool calls are needed (non-streaming check)
            log(f"Checking for additional tool calls (iteration {iteration})...")
            dbg = debug(f"Checking for additional tool calls (iteration {iteration})...")
            if dbg:
                yield dbg
                
            check_response = requests.post(f"{ollama_url}/api/chat", json={
                "model": DEFAULT_LLM_MODEL,
                "messages": messages,
                "tools": REALM_TOOLS,
                "stream": False
            })
            
            result = check_response.json()
            assistant_message = result.get('message', {})
            messages.append(assistant_message)
            
            # If no more tool calls and we have content, we're done with tools
            if not assistant_message.get('tool_calls'):
                break
        
        # Now stream the final response
        if iteration > 0:
            # We executed tools, check if we already have content from last check
            final_content = assistant_message.get('content', '')
            if final_content:
                log(f"Final answer from tool loop: {final_content[:100]}...")
                dbg = debug(f"Final answer from tool loop (iteration {iteration})")
                if dbg:
                    yield dbg
                yield final_content
                save_to_conversation(user_principal, realm_principal, question, final_content, prompt, persona_name, agent_id)
            else:
                # Stream a new response with all tool results
                log("Streaming final response with tool results...")
                log(f"Messages being sent: {len(messages)} messages")
                dbg = debug(f"Streaming final response with tool results... ({len(messages)} messages)")
                if dbg:
                    yield dbg
                    
                final_response = requests.post(f"{ollama_url}/api/chat", json={
                    "model": DEFAULT_LLM_MODEL,
                    "messages": messages[:-1] if not assistant_message.get('content') else messages,  # Remove empty assistant message
                    "stream": True
                }, stream=True)
                
                log(f"Final response status: {final_response.status_code}")
                dbg = debug(f"Final response status: {final_response.status_code}")
                if dbg:
                    yield dbg
                    
                full_answer = ""
                line_count = 0
                for line in final_response.iter_lines():
                    line_count += 1
                    if line:
                        log(f"Stream line {line_count}: {line[:200]}")
                        dbg = debug(f"Stream line {line_count}: {line[:200].decode('utf-8') if isinstance(line, bytes) else line[:200]}", is_stream_line=True)
                        if dbg:
                            yield dbg
                            
                        data = json.loads(line.decode('utf-8'))
                        if 'error' in data:
                            log(f"Ollama error: {data['error']}")
                            yield f"Error: {data['error']}"
                            break
                        if 'message' in data and 'content' in data['message']:
                            chunk = data['message']['content']
                            full_answer += chunk
                            yield chunk
                        
                        if data.get('done', False):
                            log(f"Stream done. Full answer length: {len(full_answer)}")
                            dbg = debug(f"Stream done. Full answer length: {len(full_answer)}")
                            if dbg:
                                yield dbg
                            save_to_conversation(user_principal, realm_principal, question, full_answer, prompt, persona_name, agent_id)
                            break
                log(f"Stream ended after {line_count} lines, answer: {full_answer[:100] if full_answer else '(empty)'}")
                dbg = debug(f"Stream ended after {line_count} lines")
                if dbg:
                    yield dbg
        else:
            # No tool calls - stream directly using chat API
            log("No tools needed, streaming response...")
            log(f"Assistant message content: '{assistant_message.get('content', '')[:200] if assistant_message.get('content') else '(empty)'}'")
            dbg = debug("No tools needed, streaming response...")
            if dbg:
                yield dbg
                
            full_answer = assistant_message.get('content', '')
            
            # If we already have content from the first call, yield it
            if full_answer:
                yield full_answer
                save_to_conversation(user_principal, realm_principal, question, full_answer, prompt, persona_name, agent_id)
            else:
                # Stream a new response
                log(f"Streaming new response, messages count: {len(messages[:-1])}")
                stream_response = requests.post(f"{ollama_url}/api/chat", json={
                    "model": DEFAULT_LLM_MODEL,
                    "messages": messages[:-1],  # Remove empty assistant message
                    "stream": True
                }, stream=True)
                log(f"Stream response status: {stream_response.status_code}")
                
                line_count = 0
                for line in stream_response.iter_lines():
                    line_count += 1
                    if line:
                        dbg = debug(f"Stream line {line_count}: {line[:200].decode('utf-8') if isinstance(line, bytes) else line[:200]}", is_stream_line=True)
                        if dbg:
                            yield dbg
                            
                        data = json.loads(line.decode('utf-8'))
                        if 'message' in data and 'content' in data['message']:
                            chunk = data['message']['content']
                            full_answer += chunk
                            yield chunk
                        
                        if data.get('done', False):
                            dbg = debug(f"Stream done. Full answer length: {len(full_answer)}")
                            if dbg:
                                yield dbg
                            save_to_conversation(user_principal, realm_principal, question, full_answer, prompt, persona_name, agent_id)
                            break
                            
    except Exception as e:
        log(f"Error in stream_response_with_tools: {traceback.format_exc()}")
        yield f"Error: {str(e)}"

@app.route('/suggestions', methods=['GET'])
def get_suggestions():
    """Get contextual chat suggestions based on realm status and conversation history"""
    # Update activity timestamp
    update_activity()
    
    # Get parameters from query string
    user_principal = request.args.get('user_principal', '')
    realm_principal = request.args.get('realm_principal', '')
    persona_name = request.args.get('persona', '')
    ollama_url = request.args.get('ollama_url', 'http://localhost:11434')
    
    try:
        # Get conversation history for context
        history_text = ""
        try:
            history = db_client.get_conversation_history(user_principal, realm_principal)
            # Build conversation history text (last 3 exchanges for context)
            recent_history = history[-3:] if len(history) > 3 else history
            for msg in recent_history:
                persona_used = msg.get('persona_name', 'Assistant')
                history_text += f"User: {msg['question']}\n{persona_used.title()}: {msg['response']}\n\n"
        except Exception as e:
            log(f"Error: Could not load conversation history for suggestions: {e}")
            history_text = ""
        
        # Get persona content for suggestions
        actual_persona_name, persona_content = persona_manager.get_persona_or_default(persona_name)
        
        # Create context-aware suggestions based on conversation history
        suggestions_prompt = f"""{persona_content}

CONVERSATION_HISTORY:
{history_text}

Based on the conversation history above, generate 3 relevant follow-up questions that would be most helpful for this user. The suggestions should:
1. Address relevant governance topics
2. Be concise and actionable (under 60 characters each)
3. Help the user understand or improve their realm's governance

Format your response as exactly 3 questions, one per line, with no numbering or bullet points:"""

        # Send to Ollama to generate suggestions
        response = requests.post(f"{ollama_url}/api/generate", json={
            "model": DEFAULT_LLM_MODEL,
            "prompt": suggestions_prompt,
            "stream": False
        })
        
        if response.status_code == 200:
            llm_response = response.json()['response'].strip()
            
            # Parse the response into individual suggestions
            suggestions = []
            lines = llm_response.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-') and not line.startswith('*'):
                    # Clean up any numbering or formatting
                    cleaned_line = line
                    # Remove common prefixes like "1.", "2.", etc.
                    import re
                    cleaned_line = re.sub(r'^\d+\.\s*', '', cleaned_line)
                    cleaned_line = re.sub(r'^[-*]\s*', '', cleaned_line)
                    
                    if cleaned_line:
                        suggestions.append(cleaned_line)
            
            # Ensure we have exactly 3 suggestions with smart fallbacks
            if len(suggestions) < 3:
                fallback_suggestions = [
                    "What is a realm?",
                    "How does decentralized governance work?",
                    "What can an AI governance assistant do?"
                    ]
                
                suggestions.extend(fallback_suggestions[len(suggestions):3])
            elif len(suggestions) > 3:
                suggestions = suggestions[:3]
            
            log(f"Generated contextual suggestions: {suggestions}")
            
            return jsonify({
                "suggestions": suggestions,
                "persona_used": actual_persona_name
            })
        else:
            raise Exception(f"Ollama API error: {response.status_code}")
            
    except Exception as e:
        log(f"Error generating contextual suggestions: {e}")
        # Fallback to basic suggestions on error
        suggestions = [
            "What is a realm?",
            "How does governance work here?",
            "What can I do in this community?"
        ]
        
        return jsonify({
            "suggestions": suggestions,
            "persona_used": persona_manager.default_persona
        })

VERSION = "0.1.6"

def get_git_info():
    """Get current git commit hash and datetime."""
    try:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        commit_hash = commit.stdout.strip() if commit.returncode == 0 else None
        
        datetime_result = subprocess.run(["git", "log", "-1", "--format=%ci"], capture_output=True, text=True, timeout=5)
        commit_datetime = datetime_result.stdout.strip() if datetime_result.returncode == 0 else None
        
        return commit_hash, commit_datetime
    except:
        return None, None

@app.route('/', methods=['GET'])
def health():
    # Update activity timestamp
    update_activity()
    
    commit_hash, commit_datetime = get_git_info()
    
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "git_commit": commit_hash,
        "git_commit_datetime": commit_datetime,
        "inactivity_timeout_seconds": INACTIVITY_TIMEOUT_SECONDS,
        "seconds_since_last_activity": int(time.time() - last_activity_time) if INACTIVITY_TIMEOUT_SECONDS > 0 else None
    })

@app.route('/api/agents', methods=['GET'])
def list_agents():
    """List all agents with their profiles"""
    update_activity()
    
    try:
        from agent_memory import list_all_agents
        agents = list_all_agents()
        return jsonify({
            "success": True,
            "agents": agents
        })
    except Exception as e:
        log(f"Error listing agents: {traceback.format_exc()}")
        return jsonify({"error": str(e), "agents": []}), 500


@app.route('/api/agents/<agent_id>', methods=['GET'])
def get_agent(agent_id):
    """Get detailed agent profile including memories"""
    update_activity()
    
    try:
        from agent_memory import AgentMemory
        memory = AgentMemory(agent_id)
        profile = memory.get_profile()
        
        if not profile:
            memory.close()
            return jsonify({"error": f"Agent '{agent_id}' not found"}), 404
        
        # Get recent memories
        memories = memory.recall_recent(limit=20)
        memory_stats = memory.get_memory_summary()
        memory.close()
        
        # Parse metadata if it's a string
        metadata = profile.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        
        return jsonify({
            "success": True,
            "agent": {
                "agent_id": profile.get('agent_id'),
                "principal": profile.get('principal'),
                "display_name": profile.get('display_name'),
                "persona": profile.get('persona'),
                "total_sessions": profile.get('total_sessions'),
                "created_at": str(profile.get('created_at')) if profile.get('created_at') else None,
                "last_active_at": str(profile.get('last_active_at')) if profile.get('last_active_at') else None,
                "metadata": metadata
            },
            "memories": memories,
            "memory_stats": memory_stats
        })
    except Exception as e:
        log(f"Error getting agent {agent_id}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>', methods=['PUT'])
def update_agent(agent_id):
    """Update agent profile (display_name, persona, metadata)"""
    update_activity()
    
    data = request.json
    
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'geister_db'),
            user=os.getenv('DB_USER', 'geister_user'),
            password=os.getenv('DB_PASS', 'geister_pass'),
            port=os.getenv('DB_PORT', '5432')
        )
        
        updates = []
        params = []
        
        if 'display_name' in data:
            updates.append("display_name = %s")
            params.append(data['display_name'])
        
        if 'persona' in data:
            updates.append("persona = %s")
            params.append(data['persona'])
        
        if 'metadata' in data:
            updates.append("metadata = %s")
            params.append(json.dumps(data['metadata']))
        
        if not updates:
            conn.close()
            return jsonify({"error": "No fields to update"}), 400
        
        params.append(agent_id)
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"UPDATE agent_profiles SET {', '.join(updates)} WHERE agent_id = %s RETURNING *",
                params
            )
            profile = cursor.fetchone()
            conn.commit()
        
        conn.close()
        
        if not profile:
            return jsonify({"error": f"Agent '{agent_id}' not found"}), 404
        
        return jsonify({
            "success": True,
            "agent": dict(profile)
        })
    except Exception as e:
        log(f"Error updating agent {agent_id}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/swarm/recreate', methods=['POST'])
def recreate_swarm():
    """Recreate the agent swarm (generate new agents)"""
    update_activity()
    
    data = request.json or {}
    count = data.get('count', 5)
    start_index = data.get('start_index', 1)
    persona = data.get('persona', 'compliant')
    
    try:
        from agent_swarm import cmd_generate
        
        # Run in background thread to not block
        import threading
        
        def run_generate():
            cmd_generate(count, start_index, persona)
        
        thread = threading.Thread(target=run_generate)
        thread.start()
        
        return jsonify({
            "success": True,
            "message": f"Started generating {count} agents starting from index {start_index} with persona '{persona}'"
        })
    except Exception as e:
        log(f"Error recreating swarm: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/personas', methods=['GET'])
def list_personas():
    """List all available personas"""
    update_activity()
    
    try:
        personas = persona_manager.list_available_personas()
        return jsonify({
            "success": True,
            "personas": personas,
            "default_persona": persona_manager.default_persona
        })
    except Exception as e:
        log(f"Error listing personas: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/personas/<persona_name>', methods=['GET'])
def get_persona(persona_name):
    """Get a specific persona's content"""
    update_activity()
    
    try:
        content = persona_manager.get_persona_content(persona_name)
        if content is None:
            return jsonify({"error": f"Persona '{persona_name}' not found"}), 404
        
        # Basic validation info
        validation = {
            "valid": True,
            "character_count": len(content),
            "word_count": len(content.split())
        }
        
        return jsonify({
            "success": True,
            "name": persona_name,
            "content": content,
            "validation": validation,
            "is_default": persona_name == persona_manager.default_persona
        })
    except Exception as e:
        log(f"Error getting persona {persona_name}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/personas', methods=['POST'])
def create_persona():
    """Create a new persona"""
    update_activity()
    
    data = request.json
    persona_name = data.get('name')
    content = data.get('content')
    
    if not persona_name or not content:
        return jsonify({"error": "Missing required fields: name and content"}), 400
    
    try:
        success = persona_manager.create_persona(persona_name, content)
        if success:
            return jsonify({
                "success": True,
                "message": f"Persona '{persona_name}' created successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to create persona (invalid name or content)"
            }), 400
    except Exception as e:
        log(f"Error creating persona {persona_name}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/personas/<persona_name>', methods=['DELETE'])
def delete_persona(persona_name):
    """Delete a persona"""
    update_activity()
    
    try:
        success = persona_manager.delete_persona(persona_name)
        if success:
            return jsonify({
                "success": True,
                "message": f"Persona '{persona_name}' deleted successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to delete persona '{persona_name}' (not found or is default)"
            }), 400
    except Exception as e:
        log(f"Error deleting persona {persona_name}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/personas/analytics/usage', methods=['GET'])
def get_persona_usage_analytics():
    """Get persona usage analytics and statistics"""
    update_activity()
    
    realm_principal = request.args.get('realm_principal')
    days = request.args.get('days', 30, type=int)
    
    try:
        stats = db_client.get_persona_usage_stats(realm_principal, days)
        
        return jsonify({
            "success": True,
            "data": stats,
            "period_days": days,
            "realm_principal": realm_principal
        })
    except Exception as e:
        log(f"Error getting persona usage analytics: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/personas/<persona_name>/conversations', methods=['GET'])
def get_persona_conversations(persona_name):
    """Get recent conversations for a specific persona"""
    update_activity()
    
    limit = request.args.get('limit', 10, type=int)
    
    try:
        conversations = db_client.get_conversations_by_persona(persona_name, limit)
        
        return jsonify({
            "success": True,
            "persona_name": persona_name,
            "conversations": conversations,
            "count": len(conversations)
        })
    except Exception as e:
        log(f"Error getting conversations for persona {persona_name}: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get API logs for debugging agent questions/answers/tooling.
    
    Query params:
        lines: Number of lines to return (default 100)
        type: Log type - 'api', 'ollama', 'all' (default 'api')
    """
    lines = request.args.get('lines', 100, type=int)
    log_type = request.args.get('type', 'api')
    
    log_dir = Path(__file__).parent / 'logs'
    
    log_files = {
        'api': log_dir / 'api.log',
        'ollama': log_dir / 'ollama.log',
        'chromadb': log_dir / 'chromadb.log',
    }
    
    try:
        if log_type == 'all':
            # Combine all logs
            all_logs = []
            for name, path in log_files.items():
                if path.exists():
                    with open(path, 'r') as f:
                        content = f.readlines()
                        all_logs.append(f"=== {name.upper()} LOGS ===")
                        all_logs.extend(content[-lines:])
            return '\n'.join(all_logs), 200, {'Content-Type': 'text/plain'}
        else:
            log_path = log_files.get(log_type, log_files['api'])
            if not log_path.exists():
                return f"Log file not found: {log_path}", 404, {'Content-Type': 'text/plain'}
            
            with open(log_path, 'r') as f:
                content = f.readlines()
                return ''.join(content[-lines:]), 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f"Error reading logs: {e}", 500, {'Content-Type': 'text/plain'}


# =============================================================================
# Telos Management API
# =============================================================================

@app.route('/api/telos/templates', methods=['GET'])
def list_telos_templates_api():
    """List all telos templates."""
    update_activity()
    try:
        from agent_memory import list_telos_templates
        templates = list_telos_templates()
        return jsonify({"success": True, "templates": templates})
    except Exception as e:
        log(f"Error listing telos templates: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/templates', methods=['POST'])
def create_telos_template_api():
    """Create a new telos template."""
    update_activity()
    try:
        from agent_memory import create_telos_template
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        steps = data.get('steps', [])
        
        if not name:
            return jsonify({"error": "Name is required"}), 400
        if not steps or not isinstance(steps, list):
            return jsonify({"error": "Steps must be a non-empty list"}), 400
        
        template = create_telos_template(name, description, steps)
        return jsonify({"success": True, "template": template})
    except Exception as e:
        log(f"Error creating telos template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/templates/<int:template_id>', methods=['GET'])
def get_telos_template_api(template_id):
    """Get a specific telos template."""
    update_activity()
    try:
        from agent_memory import get_telos_template
        template = get_telos_template(template_id)
        if not template:
            return jsonify({"error": "Template not found"}), 404
        return jsonify({"success": True, "template": template})
    except Exception as e:
        log(f"Error getting telos template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/templates/<int:template_id>', methods=['PUT'])
def update_telos_template_api(template_id):
    """Update a telos template."""
    update_activity()
    try:
        from agent_memory import update_telos_template
        data = request.json
        template = update_telos_template(
            template_id,
            name=data.get('name'),
            description=data.get('description'),
            steps=data.get('steps')
        )
        if not template:
            return jsonify({"error": "Template not found"}), 404
        return jsonify({"success": True, "template": template})
    except Exception as e:
        log(f"Error updating telos template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/templates/<int:template_id>', methods=['DELETE'])
def delete_telos_template_api(template_id):
    """Delete a telos template."""
    update_activity()
    try:
        from agent_memory import delete_telos_template
        success = delete_telos_template(template_id)
        if not success:
            return jsonify({"error": "Template not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        log(f"Error deleting telos template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/templates/<int:template_id>/set-default', methods=['POST'])
def set_default_template_api(template_id):
    """Set a template as the default."""
    update_activity()
    try:
        from agent_memory import set_default_template
        template = set_default_template(template_id)
        if not template:
            return jsonify({"error": "Template not found"}), 404
        return jsonify({"success": True, "template": template})
    except Exception as e:
        log(f"Error setting default template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/default', methods=['GET'])
def get_default_template_api():
    """Get the default telos template."""
    update_activity()
    try:
        from agent_memory import get_default_template
        template = get_default_template()
        return jsonify({"success": True, "template": template})
    except Exception as e:
        log(f"Error getting default template: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/assign-default-to-all', methods=['POST'])
def assign_default_to_all_api():
    """Assign the default telos template to all agents that don't have a telos."""
    update_activity()
    try:
        from agent_memory import get_default_template, assign_agent_telos, list_all_agents
        
        default_template = get_default_template()
        if not default_template:
            return jsonify({"error": "No default template set"}), 400
        
        agents = list_all_agents()
        assigned_count = 0
        
        for agent in agents:
            if not agent.get('telos_state'):  # No telos assigned
                assign_agent_telos(agent['agent_id'], template_id=default_template['id'])
                assigned_count += 1
        
        return jsonify({
            "success": True, 
            "assigned_count": assigned_count,
            "template_name": default_template['name']
        })
    except Exception as e:
        log(f"Error assigning default telos: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>/telos', methods=['GET'])
def get_agent_telos_api(agent_id):
    """Get an agent's current telos assignment."""
    update_activity()
    try:
        from agent_memory import get_agent_telos
        telos = get_agent_telos(agent_id)
        return jsonify({"success": True, "telos": telos})
    except Exception as e:
        log(f"Error getting agent telos: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>/telos', methods=['PUT'])
def assign_agent_telos_api(agent_id):
    """Assign a telos to an agent."""
    update_activity()
    try:
        from agent_memory import assign_telos_to_agent
        data = request.json
        template_id = data.get('template_id')
        custom_telos = data.get('custom_telos')
        
        if not template_id and not custom_telos:
            return jsonify({"error": "Either template_id or custom_telos is required"}), 400
        
        telos = assign_telos_to_agent(agent_id, template_id=template_id, custom_telos=custom_telos)
        return jsonify({"success": True, "telos": telos})
    except Exception as e:
        log(f"Error assigning agent telos: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>/telos', methods=['DELETE'])
def remove_agent_telos_api(agent_id):
    """Remove an agent's telos assignment."""
    update_activity()
    try:
        from agent_memory import remove_agent_telos
        success = remove_agent_telos(agent_id)
        return jsonify({"success": True, "removed": success})
    except Exception as e:
        log(f"Error removing agent telos: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>/telos/state', methods=['PUT'])
def update_agent_telos_state_api(agent_id):
    """Update an agent's telos state (idle, active, completed, failed)."""
    update_activity()
    try:
        from agent_memory import update_agent_telos_state
        data = request.json
        state = data.get('state')
        
        if state not in ('idle', 'active', 'completed', 'failed'):
            return jsonify({"error": "State must be one of: idle, active, completed, failed"}), 400
        
        telos = update_agent_telos_state(agent_id, state)
        if not telos:
            return jsonify({"error": "No telos assigned to this agent"}), 404
        return jsonify({"success": True, "telos": telos})
    except Exception as e:
        log(f"Error updating agent telos state: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/<agent_id>/telos/progress', methods=['PUT'])
def update_agent_telos_progress_api(agent_id):
    """Update an agent's telos progress."""
    update_activity()
    try:
        from agent_memory import update_agent_telos_progress
        data = request.json
        current_step = data.get('current_step')
        step_result = data.get('step_result')
        
        if current_step is None:
            return jsonify({"error": "current_step is required"}), 400
        
        telos = update_agent_telos_progress(agent_id, current_step, step_result)
        if not telos:
            return jsonify({"error": "No telos assigned to this agent"}), 404
        return jsonify({"success": True, "telos": telos})
    except Exception as e:
        log(f"Error updating agent telos progress: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/agents/telos/state', methods=['PUT'])
def update_all_agents_telos_state_api():
    """Update all agents' telos state at once."""
    update_activity()
    try:
        from agent_memory import update_all_agents_telos_state
        data = request.json
        state = data.get('state')
        
        if state not in ('idle', 'active', 'completed', 'failed'):
            return jsonify({"error": "State must be one of: idle, active, completed, failed"}), 400
        
        count = update_all_agents_telos_state(state)
        return jsonify({"success": True, "updated_count": count})
    except Exception as e:
        log(f"Error updating all agents telos state: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/dashboard')
def dashboard():
    """Serve the swarm status dashboard"""
    return app.send_static_file('swarm-dashboard.html')


@app.route('/dashboard/agent/<agent_name>')
def agent_page(agent_name):
    """Serve the agent detail page"""
    return app.send_static_file('agent.html')


@app.route('/dashboard/persona/<persona_name>')
def persona_page(persona_name):
    """Serve the persona detail page"""
    return app.send_static_file('persona.html')


# Configure static folder
app.static_folder = str(Path(__file__).parent / 'static')


# =============================================================================
# Telos Executor API Endpoints
# =============================================================================

@app.route('/api/telos/executor/status', methods=['GET'])
def get_executor_status_api():
    """Get the telos executor status."""
    update_activity()
    try:
        from telos_executor import get_executor_status, get_execution_log
        status = get_executor_status()
        status['recent_log'] = get_execution_log(limit=20)
        return jsonify({"success": True, **status})
    except Exception as e:
        log(f"Error getting executor status: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/executor/start', methods=['POST'])
def start_executor_api():
    """Start the telos executor."""
    update_activity()
    try:
        from telos_executor import start_executor, is_executor_running
        if is_executor_running():
            return jsonify({"success": True, "message": "Executor already running"})
        start_executor()
        return jsonify({"success": True, "message": "Executor started"})
    except Exception as e:
        log(f"Error starting executor: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/executor/stop', methods=['POST'])
def stop_executor_api():
    """Stop the telos executor."""
    update_activity()
    try:
        from telos_executor import stop_executor, is_executor_running
        if not is_executor_running():
            return jsonify({"success": True, "message": "Executor not running"})
        stop_executor()
        return jsonify({"success": True, "message": "Executor stopped"})
    except Exception as e:
        log(f"Error stopping executor: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telos/executor/log', methods=['GET'])
def get_executor_log_api():
    """Get the telos executor execution log."""
    update_activity()
    try:
        from telos_executor import get_execution_log
        limit = request.args.get('limit', 50, type=int)
        log_entries = get_execution_log(limit=limit)
        return jsonify({"success": True, "log": log_entries})
    except Exception as e:
        log(f"Error getting executor log: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Start inactivity monitoring if enabled
    start_inactivity_monitor()
    
    # Auto-start telos executor
    try:
        from telos_executor import start_executor
        start_executor()
        log("Telos executor auto-started")
    except Exception as e:
        log(f"Warning: Could not auto-start telos executor: {e}")
    
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # Ensure cleanup on exit
        stop_inactivity_monitor()
        try:
            from telos_executor import stop_executor
            stop_executor()
        except:
            pass
