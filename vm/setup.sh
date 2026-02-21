#!/bin/bash
# VM Setup Script for Geister API
# Installs PostgreSQL, Python deps, configures systemd service and Cloudflare tunnel
# Run as root on the DigitalOcean VM (srv1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Geister API VM Setup ==="
echo "Project directory: $PROJECT_DIR"

# --- 1. Install PostgreSQL ---
echo ""
echo "--- Step 1: Installing PostgreSQL ---"
if ! command -v psql &>/dev/null; then
    apt-get update
    apt-get install -y postgresql postgresql-contrib
    echo "PostgreSQL installed."
else
    echo "PostgreSQL already installed."
fi

# Start and enable PostgreSQL
systemctl start postgresql
systemctl enable postgresql
echo "PostgreSQL is running."

# --- 2. Configure PostgreSQL database ---
echo ""
echo "--- Step 2: Configuring PostgreSQL database ---"
sudo -u postgres createdb geister_db 2>/dev/null || echo "Database geister_db already exists"
sudo -u postgres psql -d geister_db -c "CREATE USER geister_user WITH PASSWORD 'geister_pass';" 2>/dev/null || echo "User geister_user already exists"
sudo -u postgres psql -d geister_db -c "GRANT ALL PRIVILEGES ON DATABASE geister_db TO geister_user;" 2>/dev/null || echo "Privileges already granted"
sudo -u postgres psql -d geister_db -c "ALTER USER geister_user WITH SUPERUSER;" 2>/dev/null || echo "Superuser already set"

# Initialize schema
if [ -f "$PROJECT_DIR/database/schema.sql" ]; then
    echo "Initializing database schema..."
    sudo -u postgres psql -d geister_db -f "$PROJECT_DIR/database/schema.sql" 2>/dev/null || echo "Schema already initialized"
fi
echo "PostgreSQL database configured."

# --- 3. Python virtual environment and dependencies ---
echo ""
echo "--- Step 3: Setting up Python virtual environment ---"
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    python3 -m venv "$SCRIPT_DIR/venv"
    echo "Virtual environment created at $SCRIPT_DIR/venv"
else
    echo "Virtual environment already exists."
fi

"$SCRIPT_DIR/venv/bin/pip" install --upgrade pip
"$SCRIPT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo "Python dependencies installed."

# --- 4. Install systemd service ---
echo ""
echo "--- Step 4: Installing systemd service ---"
ln -sf "$SCRIPT_DIR/geister-api.service" /etc/systemd/system/geister-api.service
systemctl daemon-reload
systemctl enable geister-api
echo "Systemd service installed and enabled."

# --- 5. Cloudflare tunnel setup ---
echo ""
echo "--- Step 5: Cloudflare tunnel ---"
if [ ! -f /root/.cloudflared/credentials.json ]; then
    echo ""
    echo "⚠️  Cloudflare tunnel credentials not found at /root/.cloudflared/credentials.json"
    echo ""
    echo "To set up the Cloudflare tunnel:"
    echo "  1. cloudflared tunnel create realms-vm"
    echo "  2. Copy the credentials file to /root/.cloudflared/credentials.json"
    echo "  3. Add DNS route: cloudflared tunnel route dns realms-vm geister-api.realmsgos.dev"
    echo "  4. Copy config: cp $SCRIPT_DIR/cloudflared-config.yml /root/.cloudflared/config.yml"
    echo "  5. Install as service: cloudflared service install"
    echo "  6. systemctl start cloudflared"
    echo ""
else
    echo "Cloudflare credentials found."
    if [ ! -f /root/.cloudflared/config.yml ]; then
        cp "$SCRIPT_DIR/cloudflared-config.yml" /root/.cloudflared/config.yml
        echo "Cloudflared config installed."
    else
        echo "Cloudflared config already exists. Review $SCRIPT_DIR/cloudflared-config.yml if needed."
    fi
fi

# --- 6. Start the API ---
echo ""
echo "--- Step 6: Starting Geister API ---"
systemctl start geister-api
sleep 2

if systemctl is-active --quiet geister-api; then
    echo "✅ Geister API is running!"
    echo ""
    echo "Useful commands:"
    echo "  journalctl -u geister-api -f          # Follow logs"
    echo "  systemctl restart geister-api          # Restart after code changes"
    echo "  systemctl status geister-api           # Check status"
else
    echo "❌ Geister API failed to start. Check logs:"
    echo "  journalctl -u geister-api --no-pager -n 50"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Quick deploy workflow:"
echo "  cd $PROJECT_DIR && git pull && systemctl restart geister-api"
