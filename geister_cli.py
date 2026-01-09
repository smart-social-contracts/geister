#!/usr/bin/env python3
"""
Geister CLI - Unified command-line interface for AI governance agents.

Client commands (connect to remote API):
    geister ask "What proposals need attention?"
    geister swarm run --persona compliant
    geister agent citizen --name "Alice"
    geister pod start main
    geister status

Server commands (require local PostgreSQL + Flask):
    geister server start
    geister server status

Usage:
    # Client mode - connect to remote Geister API
    export GEISTER_API_URL=https://geister-api.realmsgos.dev
    export OLLAMA_HOST=https://xxx.proxy.runpod.net
    geister ask "hello"
    
    # Server mode - run local API server
    geister server start
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
)
console = Console()

# Sub-applications
swarm_app = typer.Typer(help="Agent swarm management (client)")
agent_app = typer.Typer(help="Run individual AI agents (client)")
pod_app = typer.Typer(help="RunPod instance management (client)")
server_app = typer.Typer(help="Server commands (requires PostgreSQL)")

app.add_typer(swarm_app, name="swarm")
app.add_typer(agent_app, name="agent")
app.add_typer(pod_app, name="pod")
app.add_typer(server_app, name="server")


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_NETWORK = os.getenv("GEISTER_NETWORK", "staging")
DEFAULT_MODEL = os.getenv("GEISTER_MODEL", "gpt-oss:20b")
DEFAULT_REALM_FOLDER = "."


# =============================================================================
# Swarm Commands
# =============================================================================

@swarm_app.command("generate")
def swarm_generate(
    count: int = typer.Argument(..., help="Number of identities to generate"),
    start: int = typer.Option(1, "--start", "-s", help="Starting index"),
):
    """Generate agent identities for the swarm."""
    from agent_swarm import cmd_generate
    cmd_generate(count, start)


@swarm_app.command("list")
def swarm_list():
    """List all agent identities."""
    from agent_swarm import cmd_list
    cmd_list()


@swarm_app.command("run")
def swarm_run(
    start: int = typer.Option(1, "--start", "-s", help="Start index"),
    end: Optional[int] = typer.Option(None, "--end", "-e", help="End index (default: all)"),
    network: str = typer.Option(DEFAULT_NETWORK, "--network", "-n", help="Network to use"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Ollama model to use"),
    delay: float = typer.Option(1.0, "--delay", "-d", help="Delay between agents (seconds)"),
    persona: Optional[str] = typer.Option(None, "--persona", "-p", help="Persona for all agents"),
    distribution: bool = typer.Option(False, "--distribution", help="Use realistic persona distribution"),
):
    """Run citizen agents from the swarm."""
    from agent_swarm import cmd_run
    cmd_run(start, end, network, model, delay, persona, distribution)


@swarm_app.command("cleanup")
def swarm_cleanup(
    confirm: bool = typer.Option(False, "--confirm", help="Actually delete identities"),
):
    """Delete all agent identities."""
    from agent_swarm import cmd_cleanup
    cmd_cleanup(confirm)


# =============================================================================
# Agent Commands
# =============================================================================

@agent_app.command("citizen")
def agent_citizen(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Agent name"),
    network: str = typer.Option(DEFAULT_NETWORK, "--network", help="Network to connect to"),
    realm_folder: str = typer.Option(DEFAULT_REALM_FOLDER, "--realm-folder", "-f", help="Path to realm folder"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Ollama model to use"),
    profile_picture: Optional[str] = typer.Option(None, "--profile-picture", "-p", help="Profile picture URL"),
):
    """Run a citizen agent that joins a realm and sets up profile."""
    from citizen_agent import run_citizen_agent
    
    try:
        run_citizen_agent(
            name=name,
            network=network,
            realm_folder=realm_folder,
            model=model,
            profile_picture_url=profile_picture
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Agent interrupted by user[/yellow]")
        raise typer.Exit(1)


@agent_app.command("persona")
def agent_persona(
    persona: str = typer.Option("compliant", "--persona", "-p", help="Persona type (compliant, exploiter, watchful)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Agent name"),
    network: str = typer.Option(DEFAULT_NETWORK, "--network", help="Network to connect to"),
    realm_folder: str = typer.Option(DEFAULT_REALM_FOLDER, "--realm-folder", "-f", help="Path to realm folder"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Ollama model to use"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID for memory persistence"),
    realm_principal: Optional[str] = typer.Option(None, "--realm-principal", help="Realm canister ID"),
    list_personas: bool = typer.Option(False, "--list", "-l", help="List available personas"),
):
    """Run a persona agent with specific behavioral patterns."""
    if list_personas:
        from citizen_personas import get_personas
        personas = get_personas()
        console.print("\n[bold]Available Citizen Personas:[/bold]")
        console.print("=" * 50)
        for pname, p in sorted(personas.items()):
            console.print(f"\n{p.emoji} [bold]{p.name}[/bold]")
            console.print(f"   {p.description}")
            console.print(f"   [dim]Motivation: {p.motivation}[/dim]")
        return
    
    from persona_agent import run_persona_agent
    from citizen_personas import get_persona
    import random
    
    # Generate agent name if not provided
    agent_name = name
    if not agent_name:
        suffixes = ["Alpha", "Beta", "Gamma", "Delta", "Omega"]
        p = get_persona(persona)
        if p:
            agent_name = f"{p.name}{random.choice(suffixes)}"
        else:
            agent_name = f"Agent{random.randint(100, 999)}"
    
    try:
        run_persona_agent(
            persona_name=persona,
            agent_name=agent_name,
            network=network,
            realm_folder=realm_folder,
            model=model,
            agent_id=agent_id,
            realm_principal=realm_principal
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Agent interrupted by user[/yellow]")
        raise typer.Exit(1)


@agent_app.command("voter")
def agent_voter(
    voter_id: Optional[str] = typer.Option(None, "--voter-id", "-i", help="Voter principal ID"),
    proposal: Optional[str] = typer.Option(None, "--proposal", "-p", help="Specific proposal to vote on"),
    network: str = typer.Option(DEFAULT_NETWORK, "--network", "-n", help="Network to connect to"),
    realm_folder: str = typer.Option(DEFAULT_REALM_FOLDER, "--realm-folder", "-f", help="Path to realm folder"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Ollama model to use"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Analyze but don't vote"),
    strategy: str = typer.Option("balanced", "--strategy", "-s", help="Voting strategy (balanced, progressive, conservative)"),
):
    """Run a voter agent that reviews and votes on proposals."""
    from voter_agent import run_voter_agent
    
    try:
        run_voter_agent(
            voter_id=voter_id,
            proposal_id=proposal,
            network=network,
            realm_folder=realm_folder,
            model=model,
            dry_run=dry_run,
            voting_strategy=strategy
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Agent interrupted by user[/yellow]")
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
# Ask Command
# =============================================================================

@app.command("ask")
def ask_question(
    question: str = typer.Argument(..., help="Question to ask Geister"),
    api_url: Optional[str] = typer.Option(None, "--api-url", "-u", help="Geister API URL (or set GEISTER_API_URL)"),
    persona: Optional[str] = typer.Option(None, "--persona", "-p", help="Persona to use"),
    realm_principal: Optional[str] = typer.Option(None, "--realm", "-r", help="Realm principal ID"),
    ollama_url: Optional[str] = typer.Option(None, "--ollama-url", help="Ollama URL (or set OLLAMA_HOST)"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Stream response in real-time"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", "-a", help="Agent ID for memory persistence (requires local PostgreSQL)"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", "-n", help="Display name for the agent"),
):
    """Ask Geister a question."""
    import requests
    
    # Resolve API URL from env or default
    resolved_api_url = api_url or os.getenv("GEISTER_API_URL", "https://geister-api.realmsgos.dev")
    # Ensure URL has scheme
    if not resolved_api_url.startswith("http"):
        resolved_api_url = f"https://{resolved_api_url}"
    
    resolved_ollama_url = ollama_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    # Handle agent memory if agent_id is provided
    memory = None
    if agent_id:
        try:
            from agent_memory import AgentMemory
            memory = AgentMemory(agent_id, persona=persona)
            if agent_name:
                memory.ensure_profile(display_name=agent_name)
            console.print(f"[dim]🤖 Agent: {agent_name or agent_id} ({persona or 'default'})[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not load agent memory: {e}[/yellow]")
            console.print("[dim]Continuing without memory persistence...[/dim]")
    
    console.print(f"[dim]Asking Geister: {question}[/dim]\n")
    
    full_response = ""
    
    if stream:
        # Use streaming endpoint for real-time feedback
        try:
            url = f"{resolved_api_url}/api/ask"
            payload = {
                "question": question,
                "user_principal": agent_id or "",
                "realm_principal": realm_principal or "",
                "persona": persona or "",
                "ollama_url": resolved_ollama_url,
                "stream": True
            }
            
            console.print("[bold green]Geister:[/bold green] ", end="")
            
            with requests.post(url, json=payload, stream=True, timeout=300) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        print(chunk, end="", flush=True)
                        full_response += chunk
            
            print()  # Final newline
            
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Error: {e}[/red]")
    else:
        # Non-streaming mode with spinner
        from rich.status import Status
        from ashoka_cli import AshokaClient
        
        client = AshokaClient(base_url=resolved_api_url)
        
        with Status("[bold blue]Thinking...[/bold blue]", spinner="dots") as status:
            result = client.ask_question(
                question=question,
                persona=persona or "",
                realm_principal=realm_principal or "",
                ollama_url=resolved_ollama_url
            )
        
        if "answer" in result:
            full_response = result['answer']
            console.print(f"[bold green]Geister:[/bold green] {full_response}")
        else:
            console.print(f"[yellow]Response:[/yellow] {result}")
    
    # Save to agent memory if enabled
    if memory and full_response:
        try:
            memory.record_action(
                action_type="conversation",
                action_summary=f"Asked: {question[:100]}...",
                action_details={"question": question, "answer": full_response},
                realm_principal=realm_principal
            )
            console.print("[dim]💾 Saved to agent memory[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not save to memory: {e}[/yellow]")


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
        # Ensure URL has scheme
        if not url.startswith("http"):
            url = f"https://{url}"
        # Root endpoint returns {"status": "ok", ...}
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
        
        # Mask sensitive values
        if var_name in ("DB_PASS", "RUNPOD_API_KEY") and current:
            display_value = current[:4] + "***" + current[-4:] if len(current) > 8 else "***"
        else:
            display_value = current or "[dim]not set[/dim]"
        
        # Highlight if set vs using default
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
    
    # Connection checks
    if check:
        console.print()
        console.print("[bold]Connection Status:[/bold]")
        
        # Check Geister API
        api_url = os.getenv("GEISTER_API_URL", "https://geister-api.realmsgos.dev")
        ok, msg = _check_api_connection(api_url)
        color = "green" if ok else "red"
        console.print(f"  Geister API ({api_url}): [{color}]{msg}[/{color}]")
        
        # Check Ollama - prefer GEISTER_OLLAMA_URL (tunnel) over OLLAMA_HOST (direct)
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
