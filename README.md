# Geister

AI governance agents for [Realms](https://github.com/smart-social-contracts/realms).

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Check status
geister status --check

# Generate agents
geister agent generate 10

# List agents
geister agent ls

# Talk to an agent (by index or ID)
geister agent ask 1 "Please join the realm"

# Interactive session
geister agent ask 1
```

## Modes

```bash
geister mode          # Show current mode
geister mode remote   # Use hosted API (default)
geister mode local    # Use local API
```

### Remote Mode (default)

Connects to hosted API. No local setup required.

```bash
geister mode remote
```

### Local Mode

Run API locally. Requires Docker and PostgreSQL.

```bash
# Quick start (does everything)
./local_start.sh

# Then in another terminal
geister agent ask 1 "Hello"
```

Or manually:
```bash
geister mode local
docker run -d --name geister-db -e POSTGRES_DB=geister_db -e POSTGRES_USER=geister_user -e POSTGRES_PASSWORD=geister_pass -p 5432:5432 postgres:15-alpine
PGPASSWORD=geister_pass psql -h localhost -U geister_user -d geister_db -f database/schema.sql
DB_PASS=geister_pass geister server start
```

**Note:** Ollama URL is configured separately via `OLLAMA_HOST`. You can use the remote Ollama or run locally with `ollama serve`.

## Commands

```
geister
├── agent
│   ├── ls              # List agents
│   ├── generate <n>    # Create n agent identities
│   ├── ask <id> [q]    # Ask question or start chat
│   ├── inspect <id>    # Show agent data
│   └── rm <id>/--all   # Remove agent(s)
├── pod                 # RunPod management
├── server              # Local server commands
├── status              # Show configuration
├── personas            # List personas
└── version             # Show version
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEISTER_API_URL` | API endpoint | `https://geister-api.realmsgos.dev` |
| `GEISTER_OLLAMA_URL` | Ollama endpoint | `https://geister-ollama.realmsgos.dev` |
| `OLLAMA_HOST` | Local Ollama | `http://localhost:11434` |
| `DB_PASS` | Database password | - |

Run `geister status` to see current configuration.
