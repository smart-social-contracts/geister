#!/bin/bash
# VM Setup Script for Geister API
# Two modes: Docker (production) or dev (direct on host)
# Run as root on the DigitalOcean VM (srv1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MODE="${1:-docker}"

echo "=== Geister API VM Setup (mode: $MODE) ==="
echo "Project directory: $PROJECT_DIR"

# --- 1. Cloudflare tunnel setup (shared by both modes) ---
echo ""
echo "--- Step 1: Cloudflare tunnel ---"
if [ ! -f /root/.cloudflared/credentials.json ]; then
    echo ""
    echo "⚠️  Cloudflare tunnel credentials not found at /root/.cloudflared/credentials.json"
    echo ""
    echo "To set up the Cloudflare tunnel:"
    echo "  1. cloudflared tunnel login"
    echo "  2. cloudflared tunnel create realms-vm"
    echo "  3. cp <tunnel-id>.json /root/.cloudflared/credentials.json"
    echo "  4. cloudflared tunnel route dns --overwrite-dns realms-vm geister-api.realmsgos.dev"
    echo "  5. cp $SCRIPT_DIR/cloudflared-config.yml /root/.cloudflared/config.yml"
    echo "  6. cloudflared service install && systemctl start cloudflared"
    echo ""
else
    echo "Cloudflare credentials found."
    if [ ! -f /root/.cloudflared/config.yml ]; then
        cp "$SCRIPT_DIR/cloudflared-config.yml" /root/.cloudflared/config.yml
        echo "Cloudflared config installed."
    else
        echo "Cloudflared config already exists."
    fi
fi

if [ "$MODE" = "docker" ]; then
    # ===== DOCKER MODE (production) =====
    echo ""
    echo "--- Step 2: Starting Docker containers ---"
    cd "$SCRIPT_DIR"
    docker compose up -d --build
    sleep 3
    echo ""
    echo "Checking health..."
    if curl -sf http://localhost:5000/ > /dev/null 2>&1; then
        echo "✅ Geister API is running (Docker)!"
    else
        echo "⏳ Container starting... check with: docker compose -f $SCRIPT_DIR/docker-compose.yml logs -f"
    fi
    echo ""
    echo "Useful commands:"
    echo "  docker compose -f $SCRIPT_DIR/docker-compose.yml logs -f    # Follow logs"
    echo "  docker compose -f $SCRIPT_DIR/docker-compose.yml restart    # Restart"
    echo "  docker compose -f $SCRIPT_DIR/docker-compose.yml down       # Stop"
    echo ""
    echo "Quick deploy:"
    echo "  cd $PROJECT_DIR && git pull && docker compose -f vm/docker-compose.yml up -d --build"

elif [ "$MODE" = "dev" ]; then
    # ===== DEV MODE (direct on host) =====
    echo ""
    echo "--- Step 2: Installing host PostgreSQL ---"
    if ! command -v psql &>/dev/null; then
        apt-get update
        apt-get install -y postgresql postgresql-contrib
        echo "PostgreSQL installed."
    else
        echo "PostgreSQL already installed."
    fi
    systemctl start postgresql
    systemctl enable postgresql

    echo ""
    echo "--- Step 3: Configuring PostgreSQL database ---"
    sudo -u postgres createdb geister_db 2>/dev/null || echo "Database geister_db already exists"
    sudo -u postgres psql -d geister_db -c "CREATE USER geister_user WITH PASSWORD 'geister_pass';" 2>/dev/null || echo "User geister_user already exists"
    sudo -u postgres psql -d geister_db -c "GRANT ALL PRIVILEGES ON DATABASE geister_db TO geister_user;" 2>/dev/null || echo "Privileges already granted"
    sudo -u postgres psql -d geister_db -c "ALTER USER geister_user WITH SUPERUSER;" 2>/dev/null || echo "Superuser already set"

    if [ -f "$PROJECT_DIR/database/schema.sql" ]; then
        echo "Initializing database schema..."
        sudo -u postgres psql -d geister_db -f "$PROJECT_DIR/database/schema.sql" 2>/dev/null || echo "Schema already initialized"
    fi
    echo "PostgreSQL database configured."

    echo ""
    echo "--- Step 4: Python virtual environment ---"
    if [ ! -d "$SCRIPT_DIR/venv" ]; then
        python3 -m venv "$SCRIPT_DIR/venv"
        echo "Virtual environment created."
    else
        echo "Virtual environment already exists."
    fi
    "$SCRIPT_DIR/venv/bin/pip" install --upgrade pip
    "$SCRIPT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
    echo "Python dependencies installed."

    echo ""
    echo "--- Step 5: Installing dfx ---"
    if ! command -v dfx &>/dev/null; then
        DFXVM_INIT_YES=1 sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)"
        echo "dfx installed."
    else
        echo "dfx already installed: $(dfx --version)"
    fi

    echo ""
    echo "✅ Dev setup complete!"
    echo ""
    echo "Start the API:"
    echo "  ./vm/dev.sh start     # Background"
    echo "  ./vm/dev.sh fg        # Foreground"
    echo "  ./vm/dev.sh logs      # Tail logs"
    echo ""
    echo "Quick deploy:"
    echo "  cd $PROJECT_DIR && git pull && ./vm/dev.sh restart"
else
    echo "Usage: $0 [docker|dev]"
    echo "  docker  - Production: Docker containers (default)"
    echo "  dev     - Development: direct on host with venv"
    exit 1
fi

echo ""
echo "=== Setup Complete ==="
