#!/usr/bin/env python3
"""
Geister CLI - Unified command-line interface for AI governance agents.

Agent commands:
    geister agent ls                              # List all agents
    geister agent generate 10                     # Generate 10 agent identities
    geister agent ask agent_001 "Join the realm"  # Ask agent a question
    geister agent ask agent_001                   # Start interactive session
    geister agent inspect agent_001               # Show agent data
    geister agent rm agent_001                    # Remove agent
    geister agent rm --all                        # Remove all agents

Infrastructure commands:
    geister pod start main
    geister server start
    geister status
    geister personas
    geister version

Usage:
    # Set environment
    export GEISTER_API_URL=https://geister-api.realmsgos.dev
    export OLLAMA_HOST=https://xxx.proxy.runpod.net
    
    # Talk to an agent
    geister agent ask swarm_agent_001 "Please join the realm"
"""

import os
import sys
from typing import Optional

import typer
from rich.console import Console

# Environment variables configuration - grouped by mode
CLIENT_ENV_VARS = {
    "GEISTER_API_URL": ("Geister API URL", "https://geister-api.realmsgos.dev"),
    "GEISTER_OLLAMA_URL": ("Ollama URL", "https://geister-ollama.realmsgos.dev"),
    "GEISTER_NETWORK": ("Default network", "staging"),
    "GEISTER_MODEL": ("Default LLM model", "gpt-oss:20b"),
    "RUNPOD_API_KEY": ("RunPod API key", None),
}

SERVER_ENV_VARS = {
    "DB_HOST": ("Database host", "localhost"),
    "DB_NAME": ("Database name", "geister_db"),
    "DB_USER": ("Database user", "geister_user"),
    "DB_PASS": ("Database password", None),
    "DB_PORT": ("Database port", "5432"),
    "POD_TYPE": ("Pod type for API auto-shutdown", None),
    "INACTIVITY_TIMEOUT_SECONDS": ("API inactivity timeout (seconds)", "3600"),
}

# Initialize typer app and console
app = typer.Typer(
    name="geister",
    help="Geister - AI Governance Agents for Realms. Use 'geister status' to see environment variables.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()

# Sub-applications
agent_app = typer.Typer(help="Agent management and interaction")
pod_app = typer.Typer(help="RunPod instance management")
server_app = typer.Typer(help="Server commands (requires PostgreSQL)")

app.add_typer(agent_app, name="agent")
app.add_typer(pod_app, name="pod")
app.add_typer(server_app, name="server")


# =============================================================================
# Configuration
# =============================================================================

CONFIG_DIR = os.path.expanduser("~/.geister")
CONFIG_FILE = os.path.join(CONFIG_DIR, "mode")

DEFAULT_NETWORK = os.getenv("GEISTER_NETWORK", "staging")
DEFAULT_MODEL = os.getenv("GEISTER_MODEL", "gpt-oss:20b")
DEFAULT_REALM_FOLDER = "."

# Mode configurations (only affects API URL, not Ollama)
MODES = {
    "remote": {
        "GEISTER_API_URL": "https://geister-api.realmsgos.dev",
    },
    "local": {
        "GEISTER_API_URL": "http://localhost:5000",
    },
}


def get_current_mode() -> str:
    """Get current mode from config file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return f.read().strip()
    except:
        pass
    return "remote"


def set_mode(mode: str):
    """Save mode to config file."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        f.write(mode)


def get_api_url() -> str:
    """Get API URL based on current mode (env var takes precedence)."""
    env_url = os.getenv("GEISTER_API_URL")
    if env_url:
        return env_url
    mode = get_current_mode()
    return MODES.get(mode, MODES["remote"])["GEISTER_API_URL"]


def get_current_user_principal() -> str:
    """Get the current user's dfx identity principal."""
    import subprocess
    try:
        result = subprocess.run(
            ["dfx", "identity", "get-principal"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def resolve_agent_id(agent_ref: str) -> str:
    """Resolve agent reference to full agent ID.
    
    Accepts either:
    - Full agent ID: "swarm_agent_001"
    - Index number: "1" or "001"
    
    Returns the full agent ID (e.g., "swarm_agent_001").
    """
    # If it's already a full agent ID, return as-is
    if agent_ref.startswith("swarm_agent_"):
        return agent_ref
    
    # Try to parse as index
    try:
        index = int(agent_ref)
        return f"swarm_agent_{index:03d}"
    except ValueError:
        pass
    
    # Return as-is if we can't resolve it
    return agent_ref


# =============================================================================
# Agent Commands
# =============================================================================

@agent_app.command("ls")
def agent_ls():
    """List all agents with their profiles."""
    try:
        from agent_memory import list_all_agents
        from agent_swarm import cmd_list
        
        # Show dfx identities
        console.print("\n[bold]DFX Agent Identities:[/bold]")
        cmd_list()
        
        # Show database profiles
        agents = list_all_agents()
        
        if agents:
            console.print("\n[bold]Agent Profiles (Database):[/bold]")
            console.print("=" * 60)
            for agent in agents:
                name = agent.get('display_name') or agent['agent_id']
                persona = agent.get('persona') or 'default'
                sessions = agent.get('total_sessions', 0)
                console.print(f"  🤖 [bold]{name}[/bold] ({agent['agent_id']})")
                console.print(f"     Persona: {persona} | Sessions: {sessions}")
            console.print()
    except Exception as e:
        console.print(f"[yellow]Could not list agents: {e}[/yellow]")


@agent_app.command("generate")
def agent_generate(
    count: int = typer.Argument(..., help="Number of agent identities to generate"),
    start: int = typer.Option(1, "--start", "-s", help="Starting index"),
):
    """Generate agent identities (dfx identities for the swarm)."""
    from agent_swarm import cmd_generate
    cmd_generate(count, start)


@agent_app.command("rm")
def agent_rm(
    agent_ref: Optional[str] = typer.Argument(None, help="Agent ID or index (e.g., swarm_agent_001 or 1)"),
    all_agents: bool = typer.Option(False, "--all", "-a", help="Remove all agents"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
):
    """Remove agent identity and data."""
    if all_agents:
        if not confirm:
            console.print("[yellow]This will delete ALL agent identities.[/yellow]")
            console.print("Run with --confirm to actually delete.")
            return
        from agent_swarm import cmd_cleanup
        cmd_cleanup(confirm=True)
    elif agent_ref:
        agent_id = resolve_agent_id(agent_ref)
        if not confirm:
            console.print(f"[yellow]This will delete agent '{agent_id}'.[/yellow]")
            console.print("Run with --confirm to actually delete.")
            return
        # Delete specific agent
        import subprocess
        try:
            result = subprocess.run(
                ["dfx", "identity", "remove", agent_id],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                console.print(f"[green]✅ Removed agent identity: {agent_id}[/green]")
            else:
                console.print(f"[red]Failed to remove: {result.stderr}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    else:
        console.print("[red]Specify an agent ID/index or use --all[/red]")
        raise typer.Exit(1)


@agent_app.command("ask")
def agent_ask(
    agent_ref: str = typer.Argument(..., help="Agent ID or index (e.g., swarm_agent_001 or 1)"),
    question: Optional[str] = typer.Argument(None, help="Question to ask (omit for interactive mode)"),
    persona: Optional[str] = typer.Option(None, "--persona", "-p", help="Persona type"),
    realm: Optional[str] = typer.Option(None, "--realm", "-r", help="Realm principal ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Display name for the agent"),
    api_url: Optional[str] = typer.Option(None, "--api-url", "-u", help="Geister API URL"),
    ollama_url: Optional[str] = typer.Option(None, "--ollama-url", help="Ollama URL"),
):
    """Ask an agent a question or start interactive chat session."""
    import requests
    
    # Resolve agent reference to full ID
    agent_id = resolve_agent_id(agent_ref)
    
    # Resolve URLs (uses mode config if env var not set)
    resolved_api_url = api_url or get_api_url()
    if not resolved_api_url.startswith("http"):
        resolved_api_url = f"https://{resolved_api_url}"
    resolved_ollama_url = ollama_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    # Load agent profile
    memory = None
    display_name = name
    agent_background = None
    try:
        from agent_memory import AgentMemory
        memory = AgentMemory(agent_id, persona=persona)
        
        profile = memory.get_profile()
        if profile:
            if not name:
                display_name = profile.get('display_name') or agent_id
            if not persona:
                persona = profile.get('persona')
            agent_background = profile.get('metadata')
        
        if name or not profile:
            profile = memory.ensure_profile(display_name=name)
            if name:
                display_name = name
            if not agent_background:
                agent_background = profile.get('metadata')
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not load agent memory: {e}[/yellow]")
    
    def send_question(q: str) -> str:
        """Send a question to the agent and return the response."""
        user_principal = get_current_user_principal()
        payload = {
            "question": q,
            "user_principal": user_principal,
            "agent_id": agent_id,
            "realm_principal": realm or "",
            "persona": persona or "",
            "agent_name": display_name or "",
            "agent_background": agent_background,
            "ollama_url": resolved_ollama_url,
            "stream": True
        }
        
        full_response = ""
        try:
            url = f"{resolved_api_url}/api/ask"
            with requests.post(url, json=payload, stream=True, timeout=300) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        print(chunk, end="", flush=True)
                        full_response += chunk
            print()
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Error: {e}[/red]")
        
        return full_response
    
    # Interactive mode if no question provided
    if question is None:
        console.print(f"\n[bold green]🤖 Agent Session: {display_name or agent_id}[/bold green]")
        console.print(f"[dim]Persona: {persona or 'default'} | Agent ID: {agent_id}[/dim]")
        console.print("[dim]Type 'exit' or Ctrl+C to end session[/dim]\n")
        
        try:
            while True:
                try:
                    user_input = input("You: ").strip()
                    if user_input.lower() in ('exit', 'quit', 'q'):
                        break
                    if not user_input:
                        continue
                    
                    console.print("[bold green]Agent:[/bold green] ", end="")
                    response = send_question(user_input)
                    
                    # Save to memory
                    if memory and response:
                        try:
                            memory.remember(
                                action_type="conversation",
                                action_summary=f"Asked: {user_input[:100]}...",
                                action_details={"question": user_input, "answer": response},
                                realm_principal=realm
                            )
                        except:
                            pass
                    print()
                    
                except EOFError:
                    break
        except KeyboardInterrupt:
            console.print("\n[yellow]Session ended[/yellow]")
    else:
        # Single question mode
        console.print(f"[dim]🤖 Agent: {display_name or agent_id} ({persona or 'default'})[/dim]")
        console.print(f"[dim]Asking: {question}[/dim]\n")
        console.print("[bold green]Agent:[/bold green] ", end="")
        response = send_question(question)
        
        # Save to memory
        if memory and response:
            try:
                memory.remember(
                    action_type="conversation",
                    action_summary=f"Asked: {question[:100]}...",
                    action_details={"question": question, "answer": response},
                    realm_principal=realm
                )
                console.print("[dim]💾 Saved to agent memory[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not save to memory: {e}[/yellow]")


@agent_app.command("inspect")
def agent_inspect(
    agent_ref: str = typer.Argument(..., help="Agent ID or index (e.g., swarm_agent_001 or 1)"),
):
    """Show all data for an agent (profile, memories, conversations)."""
    try:
        from agent_memory import AgentMemory
        from database.db_client import DatabaseClient
        
        # Resolve agent reference to full ID
        agent_id = resolve_agent_id(agent_ref)
        
        memory = AgentMemory(agent_id)
        db_client = DatabaseClient()
        
        console.print(f"\n[bold]Agent: {agent_id}[/bold]")
        console.print("=" * 60)
        
        # Profile
        profile = memory.get_profile()
        if profile:
            console.print("\n[bold cyan]Profile:[/bold cyan]")
            console.print(f"  Display Name: {profile.get('display_name', 'N/A')}")
            console.print(f"  Persona: {profile.get('persona', 'N/A')}")
            console.print(f"  Principal: {profile.get('principal', 'N/A')}")
            console.print(f"  Total Sessions: {profile.get('total_sessions', 0)}")
            if profile.get('metadata'):
                console.print(f"  Background: {profile.get('metadata')}")
        else:
            console.print("\n[dim]No profile found[/dim]")
        
        # Memories
        memories = memory.get_memories(limit=10)
        if memories:
            console.print(f"\n[bold cyan]Recent Memories ({len(memories)}):[/bold cyan]")
            for mem in memories:
                console.print(f"  [{mem.get('action_type')}] {mem.get('action_summary')}")
                if mem.get('observations'):
                    console.print(f"    → {mem.get('observations')[:100]}...")
        else:
            console.print("\n[dim]No memories found[/dim]")
        
        # Conversations (from database)
        try:
            conversations = db_client.get_conversations_by_user(agent_id, limit=5)
            if conversations:
                console.print(f"\n[bold cyan]Recent Conversations ({len(conversations)}):[/bold cyan]")
                for conv in conversations:
                    q = conv.get('question', '')[:60]
                    console.print(f"  Q: {q}...")
        except:
            pass
        
        console.print()
        
    except Exception as e:
        console.print(f"[red]Error inspecting agent: {e}[/red]")
        raise typer.Exit(1)


# =============================================================================
# Pod Commands
# =============================================================================

@pod_app.command("start")
def pod_start(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    deploy_new: bool = typer.Option(False, "--deploy-new", help="Deploy new pod if needed"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    max_gpu_price: Optional[float] = typer.Option(None, "--max-gpu-price", help="Maximum GPU price per hour"),
):
    """Start a RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose, max_gpu_price=max_gpu_price)
    success = manager.start_pod(pod_type, deploy_new)
    raise typer.Exit(0 if success else 1)


@pod_app.command("stop")
def pod_stop(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Stop a RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.stop_pod(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("status")
def pod_status(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Check RunPod instance status."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.status_pod(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("restart")
def pod_restart(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    deploy_new: bool = typer.Option(False, "--deploy-new", help="Deploy new pod if needed"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Restart a RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.restart_pod(pod_type, deploy_new)
    raise typer.Exit(0 if success else 1)


@pod_app.command("deploy")
def pod_deploy(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    max_gpu_price: Optional[float] = typer.Option(None, "--max-gpu-price", help="Maximum GPU price per hour"),
    gpu_count: int = typer.Option(1, "--gpu-count", help="Number of GPUs"),
):
    """Deploy a new RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose, max_gpu_price=max_gpu_price, gpu_count=gpu_count)
    success = manager.deploy_pod(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("terminate")
def pod_terminate(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Terminate a RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.terminate_pod(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("health")
def pod_health(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Check API health on a RunPod instance."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.health_check_api(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("sync")
def pod_sync(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Sync local code to pod via SSH (fast deployment, no Docker rebuild)."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.sync_pod(pod_type)
    raise typer.Exit(0 if success else 1)


@pod_app.command("restart-api")
def pod_restart_api(
    pod_type: str = typer.Argument("main", help="Pod type (main or branch)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Restart Flask API on pod (no Docker rebuild)."""
    from pod_manager import PodManager
    manager = PodManager(verbose=verbose)
    success = manager.restart_api(pod_type)
    raise typer.Exit(0 if success else 1)


# =============================================================================
# Server Commands (require PostgreSQL)
# =============================================================================

@server_app.command("start")
def server_start(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(5000, "--port", "-p", help="Port to bind to"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
):
    """Start the Geister API server (requires PostgreSQL)."""
    console.print(f"[bold blue]🚀 Starting Geister API server on {host}:{port}[/bold blue]")
    console.print("[dim]Note: This requires PostgreSQL database to be running[/dim]")
    
    from api import app as flask_app
    flask_app.run(host=host, port=port, debug=debug)


@server_app.command("status")
def server_status():
    """Check if the local Geister server is running."""
    import requests
    
    port = 5000
    url = f"http://localhost:{port}/health"
    
    console.print(f"[bold]Checking local server at localhost:{port}...[/bold]")
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            console.print(f"[green]✅ Server is running[/green]")
            try:
                data = response.json()
                console.print(f"   Status: {data.get('status', 'ok')}")
            except:
                pass
        else:
            console.print(f"[yellow]⚠️ Server responded with status {response.status_code}[/yellow]")
    except requests.exceptions.ConnectionError:
        console.print(f"[red]❌ Server is not running on localhost:{port}[/red]")
        console.print(f"[dim]   Start it with: geister server start[/dim]")
    except Exception as e:
        console.print(f"[red]❌ Error checking server: {e}[/red]")


# =============================================================================
# Personas Command
# =============================================================================

@app.command("personas")
def list_personas():
    """List all available personas."""
    from citizen_personas import get_personas
    
    personas = get_personas()
    console.print("\n[bold]Available Personas:[/bold]")
    console.print("=" * 50)
    
    for name, p in sorted(personas.items()):
        console.print(f"\n{p.emoji} [bold cyan]{p.name}[/bold cyan]")
        console.print(f"   {p.description}")
        console.print(f"   [dim]Motivation: {p.motivation}[/dim]")


# =============================================================================
# Status Command
# =============================================================================

def _check_api_connection(url: str, timeout: int = 5) -> tuple:
    """Check if Geister API is reachable. Returns (is_ok, message)."""
    import requests
    try:
        if not url.startswith("http"):
            url = f"https://{url}"
        response = requests.get(url.rstrip('/'), timeout=timeout)
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("status") == "ok":
                    return True, "✅ connected"
            except:
                pass
            return True, "✅ reachable"
        return False, f"⚠️ status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "❌ not reachable"
    except requests.exceptions.Timeout:
        return False, "❌ timeout"
    except Exception as e:
        return False, f"❌ {str(e)[:20]}"


def _make_env_table(title: str, env_vars: dict):
    """Create a table for environment variables."""
    from rich.table import Table
    
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Variable", style="bold")
    table.add_column("Description")
    table.add_column("Current Value", style="green")
    table.add_column("Default", style="dim")
    
    for var_name, (description, default) in env_vars.items():
        current = os.getenv(var_name)
        
        if var_name in ("DB_PASS", "RUNPOD_API_KEY") and current:
            display_value = current[:4] + "***" + current[-4:] if len(current) > 8 else "***"
        else:
            display_value = current or "[dim]not set[/dim]"
        
        if current:
            display_value = f"[green]{display_value}[/green]"
        else:
            display_value = f"[dim]{default or 'not set'}[/dim]"
        
        table.add_row(var_name, description, display_value, str(default) if default else "-")
    
    return table


@app.command("status")
def status(
    check: bool = typer.Option(False, "--check", "-c", help="Check connectivity to API and Ollama"),
):
    """Show current configuration and optionally check connectivity."""
    import requests
    
    console.print()
    console.print(_make_env_table("Client Mode", CLIENT_ENV_VARS))
    console.print()
    console.print(_make_env_table("Server Mode", SERVER_ENV_VARS))
    
    # Show current mode
    current_mode = get_current_mode()
    console.print(f"[bold]Mode:[/bold] {current_mode}")
    
    if check:
        console.print()
        console.print("[bold]Connection Status:[/bold]")
        
        api_url = get_api_url()
        ok, msg = _check_api_connection(api_url)
        color = "green" if ok else "red"
        console.print(f"  Geister API ({api_url}): [{color}]{msg}[/{color}]")
        
        ollama_url = os.getenv("GEISTER_OLLAMA_URL", "https://geister-ollama.realmsgos.dev")
        try:
            if not ollama_url.startswith("http"):
                ollama_url = f"https://{ollama_url}"
            response = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                console.print(f"  Ollama ({ollama_url}): [green]✅ connected ({len(models)} models)[/green]")
            else:
                console.print(f"  Ollama ({ollama_url}): [yellow]⚠️ status {response.status_code}[/yellow]")
        except requests.exceptions.ConnectionError:
            console.print(f"  Ollama ({ollama_url}): [red]❌ not reachable[/red]")
        except Exception as e:
            console.print(f"  Ollama ({ollama_url}): [red]❌ {str(e)[:30]}[/red]")
    else:
        console.print()
        console.print("[dim]Tip: Use --check to verify connectivity to API and Ollama[/dim]")
    
    console.print()


# =============================================================================
# Mode Command
# =============================================================================

@app.command("mode")
def mode_cmd(
    mode: Optional[str] = typer.Argument(None, help="Mode to set: 'local' or 'remote'"),
):
    """Switch between local and remote mode.
    
    Local mode: API at http://localhost:5000
    Remote mode: API at https://geister-api.realmsgos.dev (default)
    
    Note: This only affects GEISTER_API_URL. Configure OLLAMA_HOST separately.
    """
    if mode is None:
        # Show current mode
        current = get_current_mode()
        api_url = get_api_url()
        console.print(f"\n[bold]Current mode:[/bold] {current}")
        console.print(f"[dim]API URL: {api_url}[/dim]\n")
        console.print("[dim]Usage: geister mode local|remote[/dim]")
        return
    
    mode = mode.lower()
    if mode not in MODES:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        console.print("Valid modes: local, remote")
        raise typer.Exit(1)
    
    set_mode(mode)
    api_url = MODES[mode]["GEISTER_API_URL"]
    console.print(f"[green]✅ Switched to {mode} mode[/green]")
    console.print(f"[dim]API URL: {api_url}[/dim]")
    
    if mode == "local":
        console.print("\n[dim]Make sure to:[/dim]")
        console.print("[dim]  1. Start PostgreSQL (docker or local)[/dim]")
        console.print("[dim]  2. Run: geister server start[/dim]")
        console.print("[dim]  3. Configure OLLAMA_HOST if using local Ollama[/dim]")


# =============================================================================
# Version Command
# =============================================================================

@app.command("version")
def version():
    """Show version information."""
    console.print("[bold]Geister[/bold] - AI Governance Agents")
    console.print("Version: 0.1.0")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
