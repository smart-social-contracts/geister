#!/usr/bin/env python3
"""
Geister CLI - Unified command-line interface for AI governance agents.

Combines functionality from:
- Agent swarm management (generate, run, cleanup)
- Individual agents (citizen, persona, voter)
- RunPod management (start, stop, status)
- API server
- Direct Ashoka queries

Usage:
    geister swarm generate 10
    geister swarm run --persona compliant
    geister agent citizen --name "Alice"
    geister agent persona --persona exploiter
    geister pod start main
    geister api
    geister ask "What proposals need attention?"
"""

import os
import sys
from typing import Optional

import typer
from rich.console import Console

# Environment variables configuration
ENV_VARS = {
    "ASHOKA_API_URL": ("Ashoka API URL", "http://localhost:5000"),
    "OLLAMA_HOST": ("Ollama server URL", "http://localhost:11434"),
    "GEISTER_NETWORK": ("Default network", "staging"),
    "GEISTER_MODEL": ("Default LLM model", "gpt-oss:20b"),
    "CITIZEN_AGENT_MODEL": ("Model for citizen agent", "gpt-oss:20b"),
    "PERSONA_AGENT_MODEL": ("Model for persona agent", "gpt-oss:20b"),
    "VOTER_AGENT_MODEL": ("Model for voter agent", "gpt-oss:20b"),
    "RUNPOD_API_KEY": ("RunPod API key", None),
    "DB_HOST": ("Database host", "localhost"),
    "DB_NAME": ("Database name", "ashoka_db"),
    "DB_USER": ("Database user", "ashoka_user"),
    "DB_PASS": ("Database password", "***"),
    "DB_PORT": ("Database port", "5432"),
    "POD_TYPE": ("Pod type for API auto-shutdown", None),
    "INACTIVITY_TIMEOUT_SECONDS": ("API inactivity timeout (0=disabled)", "0"),
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
swarm_app = typer.Typer(help="Agent swarm management")
agent_app = typer.Typer(help="Run individual AI agents")
pod_app = typer.Typer(help="RunPod instance management")

app.add_typer(swarm_app, name="swarm")
app.add_typer(agent_app, name="agent")
app.add_typer(pod_app, name="pod")


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
# API Command
# =============================================================================

@app.command("api")
def run_api(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(5000, "--port", "-p", help="Port to bind to"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
):
    """Start the Ashoka API server."""
    console.print(f"[bold blue]🚀 Starting Ashoka API server on {host}:{port}[/bold blue]")
    
    from api import app as flask_app
    flask_app.run(host=host, port=port, debug=debug)


# =============================================================================
# Ask Command
# =============================================================================

@app.command("ask")
def ask_question(
    question: str = typer.Argument(..., help="Question to ask Ashoka"),
    api_url: Optional[str] = typer.Option(None, "--api-url", "-u", help="Ashoka API URL (or set ASHOKA_API_URL)"),
    persona: Optional[str] = typer.Option(None, "--persona", "-p", help="Persona to use"),
    realm_principal: Optional[str] = typer.Option(None, "--realm", "-r", help="Realm principal ID"),
    ollama_url: Optional[str] = typer.Option(None, "--ollama-url", help="Ollama URL (or set OLLAMA_HOST)"),
):
    """Ask Ashoka a question."""
    from ashoka_cli import AshokaClient
    
    # Resolve API URL from env or default
    resolved_api_url = api_url or os.getenv("ASHOKA_API_URL", "http://localhost:5000")
    # Ensure URL has scheme
    if not resolved_api_url.startswith("http"):
        resolved_api_url = f"https://{resolved_api_url}"
    
    resolved_ollama_url = ollama_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    client = AshokaClient(base_url=resolved_api_url)
    
    console.print(f"[dim]Asking Ashoka: {question}[/dim]\n")
    
    result = client.ask_question(
        question=question,
        persona=persona or "",
        realm_principal=realm_principal or "",
        ollama_url=resolved_ollama_url
    )
    
    if "answer" in result:
        console.print(f"[bold green]Ashoka:[/bold green] {result['answer']}")
    else:
        console.print(f"[yellow]Response:[/yellow] {result}")


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

@app.command("status")
def status():
    """Show current environment variable configuration."""
    from rich.table import Table
    
    table = Table(title="Geister Environment Variables", show_header=True, header_style="bold cyan")
    table.add_column("Variable", style="bold")
    table.add_column("Description")
    table.add_column("Current Value", style="green")
    table.add_column("Default", style="dim")
    
    for var_name, (description, default) in ENV_VARS.items():
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
    
    console.print()
    console.print(table)
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
