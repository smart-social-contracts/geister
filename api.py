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
    print(message, flush=True)


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
ASHOKA_DEFAULT_MODEL = os.getenv('ASHOKA_DEFAULT_MODEL', 'llama3.2:1b')

# Initialize database client
db_client = DatabaseClient()

# Inactivity timeout configuration
INACTIVITY_TIMEOUT_SECONDS = int(os.getenv('INACTIVITY_TIMEOUT_SECONDS', '0'))  # Default: disabled
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
        identity = f"Your name is {agent_name}. When asked about your name or identity, respond as {agent_name}."
        
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
    
    # Tool calling parameters
    realm_folder = data.get('realm_folder', '.')
    network = data.get('network', 'staging')
    
    # Send to Ollama using chat API with tools
    try:
        if stream:
            return Response(stream_response_with_tools(ollama_url, prompt, user_principal, realm_principal, question, actual_persona_name, network, realm_folder, agent_id), 
                          mimetype='text/plain')
        else:
            # Build messages for chat API
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question}
            ]
            
            # First call - may request tool use
            log("Sending to Ollama with tools...")
            response = requests.post(f"{ollama_url}/api/chat", json={
                "model": ASHOKA_DEFAULT_MODEL,
                "messages": messages,
                "tools": REALM_TOOLS,
                "stream": False
            })
            
            result = response.json()
            log(f"Ollama response: {json.dumps(result, indent=2)}")
            
            assistant_message = result.get('message', {})
            messages.append(assistant_message)
            tools_used = False
            
            # Check if tool calls were requested
            if assistant_message.get('tool_calls'):
                tools_used = True
                log("Tool calls requested!")
                
                for tool_call in assistant_message['tool_calls']:
                    tool_name = tool_call['function']['name']
                    tool_args = tool_call['function']['arguments']
                    
                    log(f"Executing tool: {tool_name} with args: {tool_args}")
                    
                    # Execute the tool
                    tool_result = execute_tool(tool_name, tool_args, network=network, realm_folder=realm_folder)
                    
                    log(f"Tool result: {tool_result[:500]}..." if len(tool_result) > 500 else f"Tool result: {tool_result}")
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "content": tool_result
                    })
                
                # Second call - get final response with tool results
                log("Sending tool results back to Ollama...")
                final_response = requests.post(f"{ollama_url}/api/chat", json={
                    "model": ASHOKA_DEFAULT_MODEL,
                    "messages": messages,
                    "stream": False
                })
                
                final_result = final_response.json()
                answer = final_result.get('message', {}).get('content', 'No response')
            else:
                # No tool calls, use direct response
                answer = assistant_message.get('content', 'No response')
            
            log(f"Final answer: {answer}")
            
            # Save to conversation history with persona and agent info
            save_to_conversation(user_principal, realm_principal, question, answer, prompt, actual_persona_name, agent_id)
            
            return jsonify({
                "success": True,
                "answer": answer,
                "persona_used": actual_persona_name,
                "tools_used": tools_used
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


def stream_response_with_tools(ollama_url, prompt, user_principal, realm_principal, question, persona_name, network="staging", realm_folder=".", agent_id=None):
    """Generator function for streaming responses with tool calling support.
    
    First checks if tools are needed (non-streaming), executes them if so,
    then streams the final response.
    """
    try:
        # Build messages for chat API
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question}
        ]
        
        # First call - check if tools are needed (non-streaming)
        log("Checking for tool calls...")
        response = requests.post(f"{ollama_url}/api/chat", json={
            "model": ASHOKA_DEFAULT_MODEL,
            "messages": messages,
            "tools": REALM_TOOLS,
            "stream": False
        })
        
        result = response.json()
        assistant_message = result.get('message', {})
        messages.append(assistant_message)
        
        # Check if tool calls were requested
        if assistant_message.get('tool_calls'):
            log("Tool calls requested in streaming mode!")
            
            for tool_call in assistant_message['tool_calls']:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']
                
                log(f"Executing tool: {tool_name} with args: {tool_args}")
                
                # Execute the tool
                tool_result = execute_tool(tool_name, tool_args, network=network, realm_folder=realm_folder)
                
                log(f"Tool result: {tool_result[:500]}..." if len(tool_result) > 500 else f"Tool result: {tool_result}")
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "content": tool_result
                })
            
            # Stream the final response with tool results
            log("Streaming final response with tool results...")
            final_response = requests.post(f"{ollama_url}/api/chat", json={
                "model": ASHOKA_DEFAULT_MODEL,
                "messages": messages,
                "stream": True
            }, stream=True)
            
            full_answer = ""
            for line in final_response.iter_lines():
                if line:
                    data = json.loads(line.decode('utf-8'))
                    if 'message' in data and 'content' in data['message']:
                        chunk = data['message']['content']
                        full_answer += chunk
                        yield chunk
                    
                    if data.get('done', False):
                        save_to_conversation(user_principal, realm_principal, question, full_answer, prompt, persona_name, agent_id)
                        break
        else:
            # No tool calls - stream directly using chat API
            log("No tools needed, streaming response...")
            full_answer = assistant_message.get('content', '')
            
            # If we already have content from the first call, yield it
            if full_answer:
                yield full_answer
                save_to_conversation(user_principal, realm_principal, question, full_answer, prompt, persona_name, agent_id)
            else:
                # Stream a new response
                stream_response = requests.post(f"{ollama_url}/api/chat", json={
                    "model": ASHOKA_DEFAULT_MODEL,
                    "messages": messages[:-1],  # Remove empty assistant message
                    "stream": True
                }, stream=True)
                
                for line in stream_response.iter_lines():
                    if line:
                        data = json.loads(line.decode('utf-8'))
                        if 'message' in data and 'content' in data['message']:
                            chunk = data['message']['content']
                            full_answer += chunk
                            yield chunk
                        
                        if data.get('done', False):
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
            "model": ASHOKA_DEFAULT_MODEL,
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

@app.route('/', methods=['GET'])
def health():
    # Update activity timestamp
    update_activity()
    
    return jsonify({
        "status": "ok",
        "inactivity_timeout_seconds": INACTIVITY_TIMEOUT_SECONDS,
        "seconds_since_last_activity": int(time.time() - last_activity_time) if INACTIVITY_TIMEOUT_SECONDS > 0 else None
    })

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
        content = persona_manager.load_persona(persona_name)
        if content is None:
            return jsonify({"error": f"Persona '{persona_name}' not found"}), 404
        
        validation = persona_manager.validate_persona(persona_name)
        
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

if __name__ == '__main__':
    # Start inactivity monitoring if enabled
    start_inactivity_monitor()
    
    # Start realm status scheduler if enabled
    start_scheduler()
    
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # Ensure cleanup on exit
        stop_inactivity_monitor()
        stop_scheduler()
