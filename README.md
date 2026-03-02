# Geister

AI governance agents for [Realms](https://github.com/smart-social-contracts/realms).

Swarm dashboard showing agent status, persona distribution, and telos executor controls.

![Geister Swarm Dashboard](docs/dashboard.png)

Chat interface for interacting with individual agents in real time.

![Agent Chat](docs/agent-chat.png)

Agent activity log with conversation history, telos step completions, and tool calls.

![Agent Activity](docs/agent-activity.png)

Telos tab showing the agent's current mission progress and step-by-step onboarding.

![Agent Telos](docs/agent-telos.png)

Telos execution log with live updates across all agents in the swarm.

![Telos Execution Log](docs/telos-log.png)

## Architecture

```
┌─────────────────────────┐       ┌──────────────────────────────────┐
│   RunPod (GPU)          │       │   DigitalOcean VM (srv1)         │
│                         │       │                                  │
│   Ollama LLM server     │◄──────│   Geister API (Flask :5000)      │
│   (geister-ollama.      │ HTTPS │   PostgreSQL                     │
│    realmsgos.dev)       │       │   (geister-api.realmsgos.dev)    │
│                         │       │                                  │
│   Cloudflare tunnel     │       │   Cloudflare tunnel (realms-vm)  │
│   (realms-runpod)       │       │   systemd service                │
└─────────────────────────┘       └──────────────────────────────────┘
```

- **Pod** — Only Ollama (needs GPU). Lightweight Docker image, auto-shuts down after inactivity.
- **VM** — API + database (Docker containers). Cloudflare tunnel exposes the API.

### VM Setup (Production — Docker)

```bash
sudo ./vm/setup.sh docker   # builds & starts containers
```

### VM Setup (Development — direct on host)

```bash
sudo ./vm/setup.sh dev      # installs PostgreSQL, venv, dfx
./vm/dev.sh start            # run API in background
./vm/dev.sh fg               # or run in foreground
./vm/dev.sh logs             # tail logs
```

### Quick Deploy (VM)

```bash
cd /srv/geister && git pull && docker compose -f vm/docker-compose.yml up -d --build
```

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Load secrets (must be sourced, not executed)
source ./load_secret_envs.sh

# Start the RunPod instance (deploys a new one if none exists - takes a few minutes)
geister pod start main --deploy-new --verbose

# Check status
geister status

# Check dashboard
https://geister-api.realmsgos.dev/dashboard

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

Run API locally. Requires Docker.

```bash
./local.sh start    # Start PostgreSQL + API server
./local.sh stop     # Stop PostgreSQL, switch to remote
./local.sh status   # Show current status
```

Then in another terminal:
```bash
geister agent ask 1 "Hello"
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

## MCP Server (AI Tool Integration)

Geister exposes its 26 realm tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), allowing any compatible AI client to interact with Realms governance.

### Public Endpoint

```
https://geister-mcp.realmsgos.dev/mcp
```

### Connect from Windsurf

Open **Cmd/Ctrl+Shift+P → "Open MCP Configuration"** and add:

```json
{
  "mcpServers": {
    "realms-governance": {
      "serverUrl": "https://geister-mcp.realmsgos.dev/mcp"
    }
  }
}
```

### Connect from Claude Desktop

Edit `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "realms-governance": {
      "url": "https://geister-mcp.realmsgos.dev/mcp"
    }
  }
}
```

### Connect from Cursor

In Settings → MCP, add a server with URL: `https://geister-mcp.realmsgos.dev/mcp`

### Run Locally

```bash
# HTTP server (remote access)
python mcp_server.py --transport http --port 8090

# stdio (local IDE integration)
python mcp_server.py --transport stdio
```

### Available Tools (26)

| Category | Tools |
|----------|-------|
| Registry | `list_realms`, `search_realm`, `registry_get_credits`, `registry_redeem_voucher`, `registry_deploy_realm`, `registry_deploy_status` |
| Citizen | `join_realm`, `set_profile_picture`, `get_my_status`, `get_my_principal` |
| Realm Status | `realm_status`, `db_schema`, `db_get`, `find_objects` |
| Governance | `get_proposals`, `get_proposal`, `cast_vote`, `get_my_vote`, `submit_proposal` |
| Economic | `get_balance`, `get_transactions`, `get_vault_status` |
| ICW Tokens | `icw_check_balance`, `icw_transfer_tokens`, `pay_invoice`, `icw_get_address` |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEISTER_API_URL` | API endpoint | `https://geister-api.realmsgos.dev` |
| `GEISTER_OLLAMA_URL` | Ollama endpoint | `https://geister-ollama.realmsgos.dev` |
| `OLLAMA_HOST` | Local Ollama | `http://localhost:11434` |
| `DB_PASS` | Database password | - |
| `MCP_TRANSPORT` | MCP transport (`http` or `stdio`) | `http` |
| `MCP_HOST` | MCP server bind host | `0.0.0.0` |
| `MCP_PORT` | MCP server port | `8090` |

Run `geister status` to see current configuration.
