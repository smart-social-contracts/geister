# Geister — Operations Guide

## Architecture (two machines)

| Machine | Runs | URL |
|---------|------|-----|
| **This VM (srv1)** | Flask API, PostgreSQL, Cloudflare tunnel | `geister-api.realmsgos.dev` → `localhost:5000` |
| **RunPod pod** | Ollama (LLM) only | `geister-ollama.realmsgos.dev` → `localhost:11434` |

The API and the LLM are on different machines. The pod does NOT run the API.

## If the API is down (502 on `geister-api.realmsgos.dev`)

The Flask API just needs to be restarted **on this VM**. Don't touch the RunPod pod.

```bash
cd /srv/geister
source vm/geister-api.env
export DB_HOST=localhost INACTIVITY_TIMEOUT_SECONDS=0 TERM=xterm-256color
gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120 api:app
```

The Cloudflare tunnel (`cloudflared` systemd service) is always running and routes the public URL to `localhost:5000`.

## If Ollama is down (errors mentioning Ollama / LLM unreachable)

The RunPod pod needs restarting:

```bash
cd /srv/geister
export RUNPOD_API_KEY=<key from .env or vm/geister-api.env>
geister pod status   # check
geister pod stop     # if stuck
geister pod start    # restart
```

## Environment variables

All env vars live in `vm/geister-api.env`. When running locally, override `DB_HOST=localhost` (the file defaults to `postgres` for Docker).

Set `INACTIVITY_TIMEOUT_SECONDS=0` to prevent auto-shutdown.

## Key files

- `api.py` — Flask API (entry point, CORS config, chat endpoints)
- `vm/geister-api.env` — all environment variables
- `vm/dev.sh` — helper script: `./vm/dev.sh start|stop|restart|logs`
- `start.sh` — RunPod pod entrypoint (Ollama + tunnel only, no API)
- `vm/cloudflared-config.yml` — Cloudflare tunnel routing

## Frontend extensions (Realms)

Extensions live in `/srv/realms/extensions/extensions/`. After building a Svelte extension:

1. Upload to `file_registry` canister (stores the bundle)
2. **Also** upload to each frontend canister directly (Dominion, Agora, Syntropia) — the extension-loader prioritizes same-origin assets over the registry

Canister IDs at runtime come from `globalThis.__CANISTER_IDS` (loaded by `canister_ids.js`), not from build-time `process.env`.
