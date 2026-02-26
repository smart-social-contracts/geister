#!/usr/bin/env python3
"""
Telos Executor - Autonomous background execution of agent telos steps.

This module runs a background thread that:
1. Polls for agents with state='active'
2. Executes their current telos step via the LLM
3. Records results and advances progress
"""
import os
import json
import time
import subprocess
import threading
import traceback
import requests
from typing import Optional, Dict, List, Any
from datetime import datetime

# Import from local modules
from agent_memory import (
    list_all_agents, get_agent_telos, update_agent_telos_progress,
    update_agent_telos_state, get_telos_template, AgentMemory
)
from realm_tools import REALM_TOOLS, execute_tool

# Configuration
EXECUTOR_INTERVAL_SECONDS = 0  # No delay between execution cycles
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
DEFAULT_MODEL = os.getenv('LLM_MODEL', 'gpt-oss:20b')
DEFAULT_NETWORK = os.getenv('NETWORK', 'staging')
OLLAMA_READY_TIMEOUT = int(os.getenv('OLLAMA_READY_TIMEOUT', '120'))  # seconds

# Global state
_executor_thread: Optional[threading.Thread] = None
_executor_running = False
_execution_log: List[Dict] = []  # Keep last N executions in memory
MAX_LOG_ENTRIES = 100


def log(message: str):
    """Log with timestamp."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = f"[TELOS {timestamp}] {message}"
    print(msg, flush=True)
    # Also write to file for debugging
    try:
        with open('/app/geister/logs/telos_executor.log', 'a') as f:
            f.write(msg + '\n')
    except:
        pass


def add_execution_log(agent_id: str, step: int, step_text: str, result: str, success: bool):
    """Add an entry to the execution log."""
    global _execution_log
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "step": step,
        "step_text": step_text,
        "result": result[:500] if result else "",  # Truncate long results
        "success": success
    }
    _execution_log.insert(0, entry)
    # Keep only last N entries
    if len(_execution_log) > MAX_LOG_ENTRIES:
        _execution_log = _execution_log[:MAX_LOG_ENTRIES]


def get_execution_log(limit: int = 50) -> List[Dict]:
    """Get recent execution log entries."""
    return _execution_log[:limit]


def wait_for_ollama(timeout: int = None) -> bool:
    """Block until Ollama is reachable. Returns True if ready, False on timeout."""
    timeout = timeout or OLLAMA_READY_TIMEOUT
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(OLLAMA_URL, timeout=5)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    log(f"Ollama not ready after {timeout}s")
    return False


def ensure_dfx_identity(identity_name: str) -> bool:
    """Create a dfx identity if it doesn't already exist. Returns True if usable."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "get-principal", "--identity", identity_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True
        # Identity doesn't exist — create it
        log(f"  Creating dfx identity '{identity_name}'...")
        create = subprocess.run(
            ["dfx", "identity", "new", identity_name, "--storage-mode=plaintext"],
            capture_output=True, text=True, timeout=10
        )
        return create.returncode == 0
    except Exception as e:
        log(f"  Warning: could not ensure dfx identity '{identity_name}': {e}")
        return False


def execute_telos_step(agent_id: str, step_text: str, agent_data: Dict) -> Dict[str, Any]:
    """
    Execute a single telos step for an agent.
    
    Returns dict with 'success', 'result', and optionally 'error'.
    """
    try:
        # Get agent profile info
        display_name = agent_data.get('display_name', agent_id)
        persona = agent_data.get('persona', 'compliant')
        
        # Ensure dfx identity exists for this agent (auto-create if missing)
        ensure_dfx_identity(agent_id)
        
        # Get agent's principal and realm context for tool calls
        agent_principal = agent_data.get('principal', '')
        metadata = agent_data.get('metadata') or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        realm_principal = metadata.get('realm_id', '')
        realm_name = metadata.get('realm_name', '')
        
        # Build the prompt for this step
        realm_context = f"\nYou are operating in the realm \"{realm_name}\" (canister ID: {realm_principal})." if realm_principal else ""
        system_prompt = f"""You are {display_name}, a {persona} AI agent in the Realms ecosystem.
Your principal ID is: {agent_principal}{realm_context}

You have a mission (telos) to complete. Your current step is:
"{step_text}"

IMPORTANT RULES:
- You MUST call the appropriate tool function to complete this step. DO NOT just describe what you would do.
- Use your principal ID ({agent_principal}) when tools require a principal_id parameter.
- After the tool returns a result, summarize what happened in 1-2 sentences.
- If the tool returns an error, explain the error briefly.
- NEVER respond with just text. Always call a tool first.
- When interacting with a specific realm, you MUST pass the realm_id parameter (the canister ID from list_realms results) to every tool call. Without realm_id, your calls may go to the wrong realm. Always call list_realms first to get the correct canister IDs, then pass the chosen realm's id as realm_id in subsequent calls."""

        user_message = f"Execute this step NOW by calling the appropriate tool function. Your principal is {agent_principal}. Step: {step_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # Call Ollama with tools
        max_iterations = 8
        iteration = 0
        final_answer = None
        tools_called = []
        accumulated_content = []  # Capture content even from tool-call iterations
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                response = requests.post(f"{OLLAMA_URL}/api/chat", json={
                    "model": DEFAULT_MODEL,
                    "messages": messages,
                    "tools": REALM_TOOLS,
                    "stream": False
                }, timeout=(10, 120))
            except requests.exceptions.ConnectionError:
                return {"success": False, "error": f"Cannot reach Ollama at {OLLAMA_URL}. The LLM backend appears to be offline."}
            except requests.exceptions.Timeout:
                return {"success": False, "error": f"Ollama at {OLLAMA_URL} timed out. The LLM backend may be overloaded."}
            
            if response.status_code != 200:
                return {"success": False, "error": f"Cannot reach Ollama at {OLLAMA_URL} (HTTP {response.status_code}). The LLM backend appears to be offline or unavailable."}
            
            try:
                result = response.json()
            except ValueError:
                return {"success": False, "error": f"Invalid response from Ollama at {OLLAMA_URL}. The LLM backend may be misconfigured."}
            assistant_message = result.get('message', {})
            messages.append(assistant_message)
            
            content = assistant_message.get('content', '')
            tool_calls = assistant_message.get('tool_calls', [])
            
            # Always accumulate text content (LLM may return text + tool calls)
            if content and content.strip():
                accumulated_content.append(content.strip())
            
            # If no tool calls on first iteration, the LLM is just chatting
            # Retry with a stronger nudge
            if not tool_calls and iteration == 1 and not tools_called:
                log(f"  [{display_name}] No tool call on first try, nudging...")
                messages.append({
                    "role": "user",
                    "content": f"You MUST call a tool function now. Do not describe what to do - actually call the tool. Your principal_id is {agent_principal}. Call the tool for: {step_text}"
                })
                continue
            
            # If we already called tools and now have a text response, we're done
            if content and not tool_calls and tools_called:
                final_answer = content
                break
            
            # If still no tool calls after nudging, fail the step
            if not tool_calls:
                if not tools_called:
                    log(f"  [{display_name}] FAILED: No tools were called for this step")
                    return {"success": False, "error": "LLM did not call any tools for this step", "result": content}
                final_answer = content or "Step completed."
                break
            
            # Execute tool calls
            for tool_call in tool_calls:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']
                
                log(f"  [{display_name}] Tool: {tool_name}({json.dumps(tool_args)[:100]})")
                tools_called.append(tool_name)
                
                tool_result = execute_tool(
                    tool_name, 
                    tool_args, 
                    network=DEFAULT_NETWORK,
                    realm_folder='.',
                    realm_principal=realm_principal,
                    user_principal=agent_principal,
                    user_identity=agent_id  # Use agent's dfx identity for calls
                )
                
                log(f"  [{display_name}] Result: {tool_result[:150]}")
                
                # Check if the tool returned an error
                try:
                    parsed_result = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                    if isinstance(parsed_result, dict) and parsed_result.get('error'):
                        log(f"  [{display_name}] Tool returned error: {parsed_result['error'][:150]}")
                except (json.JSONDecodeError, TypeError):
                    parsed_result = None
                
                messages.append({
                    "role": "tool",
                    "content": tool_result
                })
        
        # If final_answer is still None (LLM kept calling tools for all iterations),
        # make one final call WITHOUT tools to force a text summary
        if final_answer is None:
            log(f"  [{display_name}] Max iterations reached, requesting summary...")
            summary_prompts = [
                "Summarise what you just did and what happened. List the tools you called, their results, and any errors. Do NOT call any more tools — respond with plain text only.",
                "RESPOND WITH TEXT ONLY. No tool calls. Summarise the actions and results from above."
            ]
            for attempt, prompt in enumerate(summary_prompts):
                if final_answer:
                    break
                messages.append({"role": "user", "content": prompt})
                try:
                    summary_resp = requests.post(f"{OLLAMA_URL}/api/chat", json={
                        "model": DEFAULT_MODEL,
                        "messages": messages,
                        "stream": False
                        # No tools key — forces text response
                    }, timeout=(10, 60))
                    if summary_resp.status_code == 200:
                        summary_msg = summary_resp.json().get('message', {})
                        summary_text = (summary_msg.get('content') or '').strip()
                        has_tool_calls = bool(summary_msg.get('tool_calls'))
                        log(f"  [{display_name}] Summary attempt {attempt+1}: "
                            f"text={len(summary_text)} chars, tool_calls={has_tool_calls}")
                        if summary_text:
                            final_answer = summary_text
                            messages.append(summary_msg)
                    else:
                        log(f"  [{display_name}] Summary attempt {attempt+1}: HTTP {summary_resp.status_code}")
                except Exception as summary_err:
                    log(f"  [{display_name}] Summary attempt {attempt+1} failed: {summary_err}")

            # Fallback if summary calls also failed
            if not final_answer:
                log(f"  [{display_name}] All summary attempts failed, using fallback")
                if accumulated_content:
                    final_answer = "\n".join(accumulated_content)
                else:
                    final_answer = f"Step completed ({len(tools_called)} tool calls executed)."
        
        # Build debug chain from messages for memory storage
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
                    if len(content) > 2000:
                        content = content[:2000] + '... (truncated)'
                    debug_chain.append({'type': 'tool_response', 'content': content})
        except Exception as debug_err:
            log(f"  Warning: Could not build debug chain: {debug_err}")
            debug_chain = []
        
        # Save to agent memory with full conversation chain
        try:
            memory = AgentMemory(agent_id, persona=agent_data.get('persona'))
            memory.remember(
                action_type="telos_step",
                action_summary=f"Completed: {step_text}",
                action_details={
                    "step": step_text, 
                    "result": final_answer,
                    "debug_chain": debug_chain
                },
                observations=final_answer[:200] if final_answer else ""
            )
            memory.close()
        except Exception as mem_err:
            log(f"  Warning: Could not save memory: {mem_err}")
        
        # Only fail if the LLM produced no meaningful final answer AND a tool
        # had an error.  If the LLM recovered (produced a summary despite
        # earlier tool errors), treat the step as successful.
        if not final_answer or not final_answer.strip():
            tool_had_error = False
            for msg in messages:
                if msg.get('role') == 'tool':
                    try:
                        parsed = json.loads(msg['content']) if isinstance(msg['content'], str) else msg['content']
                        if isinstance(parsed, dict) and parsed.get('error'):
                            tool_had_error = True
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
            if tool_had_error:
                log(f"  [{display_name}] Step failed: no final answer and tool returned error")
                return {"success": False, "error": "Tool execution returned an error", "result": ""}
        
        return {"success": True, "result": final_answer}
        
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def process_active_agents():
    """Process all agents with active telos state."""
    try:
        agents = list_all_agents()
        active_agents = [a for a in agents if a.get('telos_state') == 'active']
        
        if not active_agents:
            return
        
        log(f"Processing {len(active_agents)} active agents...")
        
        for agent in active_agents:
            agent_id = agent['agent_id']
            display_name = agent.get('display_name', agent_id)
            
            try:
                # Gate on Ollama readiness before executing
                if not wait_for_ollama():
                    log(f"  [{display_name}] Skipping — Ollama unavailable")
                    continue

                # Get full telos info
                telos = get_agent_telos(agent_id)
                if not telos:
                    log(f"  [{display_name}] No telos assigned, skipping")
                    continue
                
                # Get steps
                steps = []
                if telos.get('telos_template_id'):
                    template = get_telos_template(telos['telos_template_id'])
                    if template:
                        steps = template.get('steps', [])
                elif telos.get('custom_telos'):
                    steps = [s.strip() for s in telos['custom_telos'].split('\n') if s.strip()]
                
                if not steps:
                    log(f"  [{display_name}] No steps found, skipping")
                    continue
                
                current_step = telos.get('current_step', 0)
                
                # Check if already completed
                if current_step >= len(steps):
                    log(f"  [{display_name}] All steps completed, marking as completed")
                    update_agent_telos_state(agent_id, 'completed')
                    continue
                
                step_text = steps[current_step]
                log(f"  [{display_name}] Executing step {current_step + 1}/{len(steps)}: {step_text}")
                
                # Execute the step
                result = execute_telos_step(agent_id, step_text, agent)
                
                # Record result
                step_result = {
                    "status": "completed" if result['success'] else "failed",
                    "result": result.get('result') or result.get('error', ''),
                    "timestamp": datetime.now().isoformat()
                }
                
                # Update progress
                if result['success']:
                    new_step = current_step + 1
                    update_agent_telos_progress(agent_id, new_step, {str(current_step): step_result})
                    
                    # Check if all done
                    if new_step >= len(steps):
                        log(f"  [{display_name}] ✓ Completed all steps!")
                        update_agent_telos_state(agent_id, 'completed')
                    else:
                        log(f"  [{display_name}] ✓ Step completed, advancing to {new_step + 1}")
                else:
                    # Record failure but don't advance
                    update_agent_telos_progress(agent_id, current_step, {str(current_step): step_result})
                    log(f"  [{display_name}] ✗ Step failed: {result.get('error', 'Unknown error')}")
                
                # Add to execution log
                add_execution_log(
                    agent_id, 
                    current_step, 
                    step_text, 
                    result.get('result') or result.get('error', ''),
                    result['success']
                )
                
            except Exception as agent_err:
                log(f"  [{display_name}] Error: {agent_err}")
                traceback.print_exc()
        
        log("Processing complete")
        
    except Exception as e:
        log(f"Error in process_active_agents: {e}")
        traceback.print_exc()


def executor_loop():
    """Main executor loop running in background thread."""
    global _executor_running
    
    log("Executor started")
    
    while _executor_running:
        try:
            process_active_agents()
        except Exception as e:
            log(f"Error in executor loop: {e}")
        
        # Brief yield to allow quick shutdown
        if not _executor_running:
            break
        time.sleep(0.1)
    
    log("Executor stopped")


def start_executor():
    """Start the telos executor background thread."""
    global _executor_thread, _executor_running
    
    if _executor_running:
        log("Executor already running")
        return False
    
    _executor_running = True
    _executor_thread = threading.Thread(target=executor_loop, daemon=True)
    _executor_thread.start()
    log("Executor started (no delay between cycles)")
    return True


def stop_executor():
    """Stop the telos executor background thread."""
    global _executor_running
    
    if not _executor_running:
        log("Executor not running")
        return False
    
    _executor_running = False
    log("Executor stop requested")
    return True


def is_executor_running() -> bool:
    """Check if executor is currently running."""
    return _executor_running


def get_executor_status() -> Dict:
    """Get current executor status."""
    return {
        "running": _executor_running,
        "interval_seconds": EXECUTOR_INTERVAL_SECONDS,
        "recent_executions": len(_execution_log),
        "model": DEFAULT_MODEL,
        "network": DEFAULT_NETWORK
    }


if __name__ == "__main__":
    # Test run
    print("Starting telos executor test...")
    start_executor()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_executor()
        print("Stopped")
