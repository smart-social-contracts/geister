#!/bin/bash
# Pod entrypoint: Cloudflare tunnel + Ollama + PostgreSQL + Flask API

set -x

# --- Cloudflare Tunnel ---
# Decode credentials from base64 environment variables
# Generate with: base64 -w 0 <file> && echo
if [ ! -z "$CLOUDFLARED_CREDS_B64" ]; then
    echo "Setting up Cloudflare Tunnel credentials..."
    printf '%s' "$CLOUDFLARED_CREDS_B64" | base64 -d > /root/.cloudflared/credentials.json
    chmod 600 /root/.cloudflared/credentials.json

    if [ ! -z "$CLOUDFLARED_PEM_B64" ]; then
        printf '%s' "$CLOUDFLARED_PEM_B64" | base64 -d > /root/.cloudflared/cert.pem
        chmod 600 /root/.cloudflared/cert.pem
    fi

    echo "Starting Cloudflare Tunnel..."
    cloudflared tunnel --config /root/.cloudflared/config.yml run realms-runpod > /var/log/cloudflared.log 2>&1 &
    echo "Cloudflare Tunnel started (PID: $!)"
else
    echo "WARNING: CLOUDFLARED_CREDS_B64 not set. Skipping tunnel setup."
fi

# --- Ollama ---
./run_ollama_only.sh

# --- PostgreSQL ---
echo "Starting PostgreSQL..."
service postgresql start
sleep 3

echo "Setting up PostgreSQL database..."
sudo -u postgres createdb geister_db 2>/dev/null || echo "Database already exists"
sudo -u postgres psql -d geister_db -c "CREATE USER geister_user WITH PASSWORD 'geister_pass';" 2>/dev/null || echo "User already exists"
sudo -u postgres psql -d geister_db -c "GRANT ALL PRIVILEGES ON DATABASE geister_db TO geister_user;" 2>/dev/null || echo "Privileges already granted"
sudo -u postgres psql -d geister_db -c "ALTER USER geister_user WITH SUPERUSER;" 2>/dev/null || echo "Superuser already set"

if [ -f "database/schema.sql" ]; then
    echo "Initializing database schema..."
    sudo -u postgres psql -d geister_db -f database/schema.sql 2>/dev/null || echo "Schema already initialized"
fi

# --- Flask API ---
echo "Starting Flask API..."
export DB_HOST=localhost
export DB_NAME=geister_db
export DB_USER=geister_user
export DB_PASS=geister_pass
export DB_PORT=5432
export OLLAMA_URL=http://localhost:11434
export DEFAULT_LLM_MODEL=${DEFAULT_LLM_MODEL:-gpt-oss:20b}
export GEISTER_USE_LLM=true
export GEISTER_DFX_NETWORK=ic
export DFX_WARNING=-mainnet_plaintext_identity
# Respect RunPod env (pod_manager sets 3600); default 1h auto-shutdown. Set 0 to disable.
export INACTIVITY_TIMEOUT_SECONDS=${INACTIVITY_TIMEOUT_SECONDS:-3600}

mkdir -p logs
python3 api.py >> logs/api.log 2>&1 &
API_PID=$!

sleep 2
if ps -p $API_PID > /dev/null 2>&1; then
    echo "Flask API started (PID: $API_PID)"
else
    echo "ERROR: Flask API failed to start. Check logs/api.log"
    cat logs/api.log
fi

echo "=== Pod ready (Ollama + API) ==="

sleep 99999999  # Keep container alive