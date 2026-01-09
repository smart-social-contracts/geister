# Geister

AI-powered governance agents for Internet Computer Protocol realms and DAOs. Geister provides intelligent responses to governance questions using multiple AI personas, powered by LLMs.

## Features

- **Multi-Persona AI Agents**: Specialized personas (Compliant, Exploiter, Watchful)
- **Realm Integration**: Context-aware responses using real-time realm data
- **Client/Server Architecture**: Run locally or connect to remote API
- **RunPod Cloud Deployment**: Scalable GPU-powered infrastructure
- **Agent Swarm**: Run multiple agents in parallel

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Check configuration and connectivity
geister status --check

# Ask a question
geister ask "What proposals need attention?"

# List available personas
geister personas
```

## Architecture

Geister uses a **client/server architecture**:

| Command | Runs Where | What it does |
|---------|------------|--------------|
| `geister ask` | Client → API | Sends question to server, which uses Ollama |
| `geister status` | Client only | Checks env vars and pings endpoints |
| `geister personas` | Client only | Lists local persona definitions |
| `geister swarm` | Client → API | Runs agent swarm, agents call API |
| `geister agent` | Client → API | Runs single agent, calls API |
| `geister pod` | Client → RunPod | Manages RunPod instances |
| `geister server start` | Server | Starts the Flask API locally |
| `geister server status` | Client only | Checks if local server is running |

```
Your machine (CLI) → GEISTER_API_URL (server) → GEISTER_OLLAMA_URL (LLM)
```

## Client Commands

### Ask Questions

```bash
# Simple question
geister ask "What is quadratic voting?"

# With specific persona
geister ask "Analyze this budget proposal" --persona advisor

# With realm context
geister ask "Should we proceed?" --realm <realm_principal>
```

### Agent Commands

```bash
# Run citizen agent
geister agent citizen --name "Alice"

# Run persona agent
geister agent persona --persona exploiter

# Run voter agent
geister agent voter --proposal <proposal_id>
```

### Swarm Commands

```bash
# Generate agent identities
geister swarm generate 10

# Run agent swarm
geister swarm run --persona compliant

# List agents
geister swarm list

# Cleanup agents
geister swarm cleanup
```

### Pod Management (RunPod)

```bash
# Start pod
geister pod start main

# Check status
geister pod status main

# Stop pod
geister pod stop main

# Deploy new pod
geister pod deploy main
```

## Server Commands

```bash
# Start local API server (requires PostgreSQL)
geister server start

# Check if local server is running
geister server status
```

### Local Development Setup

```bash
# Start PostgreSQL via Docker
docker run -d --name geister-db \
  -e POSTGRES_DB=geister_db \
  -e POSTGRES_USER=geister_user \
  -e POSTGRES_PASSWORD=geister_pass \
  -p 5432:5432 postgres:15-alpine

# Initialize schema
PGPASSWORD=geister_pass psql -h localhost -U geister_user -d geister_db -f database/schema.sql

# Start server
DB_PASS=geister_pass geister server start
```

## Configuration

### Client Mode (connect to remote API)

```bash
export GEISTER_API_URL=https://geister-api.realmsgos.dev
export GEISTER_OLLAMA_URL=https://geister-ollama.realmsgos.dev
export GEISTER_NETWORK=staging
export GEISTER_MODEL=gpt-oss:20b
export RUNPOD_API_KEY=your_key
```

### Server Mode (run local server)

```bash
export DB_HOST=localhost
export DB_NAME=geister_db
export DB_USER=geister_user
export DB_PASS=your_password
export DB_PORT=5432
```

Use `geister status` to see current configuration.

## File Structure

- `geister_cli.py` - Main CLI entry point
- `api.py` - HTTP API service
- `persona_manager.py` - Multi-persona system
- `agent_swarm.py` - Agent swarm management
- `citizen_agent.py` - Citizen agent implementation
- `persona_agent.py` - Persona agent implementation
- `voter_agent.py` - Voter agent implementation
- `pod_manager.py` - RunPod instance management
- `database/` - Database client and schema
- `prompts/personas/` - AI persona definitions
- `cloudflared/` - Cloudflare tunnel configuration
