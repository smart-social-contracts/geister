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

### Remote Mode (default)

Connects to hosted API and Ollama. No local setup required.

```bash
export GEISTER_API_URL=https://geister-api.realmsgos.dev
export GEISTER_OLLAMA_URL=https://geister-ollama.realmsgos.dev
```

### Local Mode

Run everything locally. Requires PostgreSQL and Ollama.

```bash
# 1. Start PostgreSQL
docker run -d --name geister-db \
  -e POSTGRES_DB=geister_db \
  -e POSTGRES_USER=geister_user \
  -e POSTGRES_PASSWORD=geister_pass \
  -p 5432:5432 postgres:15-alpine

# 2. Initialize schema
PGPASSWORD=geister_pass psql -h localhost -U geister_user -d geister_db -f database/schema.sql

# 3. Start local Ollama
ollama serve

# 4. Configure environment
export GEISTER_API_URL=http://localhost:5000
export OLLAMA_HOST=http://localhost:11434
export DB_PASS=geister_pass

# 5. Start API server
geister server start

# 6. In another terminal, use the CLI
geister agent ask 1 "Hello"
```

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
