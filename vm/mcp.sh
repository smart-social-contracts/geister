#!/bin/bash
# Dev script to run the Geister MCP server (Streamable HTTP) on this VM.
# It exposes realm tools to external MCP clients (e.g. the user's Claude),
# authenticated with personal pairing tokens.
#
# Usage: ./vm/mcp.sh [start|stop|status|logs|fg|restart|help]
#
# Sits behind the realms-vm Cloudflare tunnel as geister-mcp.realmsgos.dev
# (ingress -> http://localhost:5001).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[MCP]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error(){ echo -e "${RED}[ERROR]${NC} $1"; }

SERVICE_NAME="geister-mcp"
PID_FILE="$SCRIPT_DIR/.mcp.pid"
LOG_FILE="$SCRIPT_DIR/mcp.dev.log"

setup_env() {
    source "$SCRIPT_DIR/venv/bin/activate"
    if [ -f "$SCRIPT_DIR/geister-api.env" ]; then
        set -a; source "$SCRIPT_DIR/geister-api.env"; set +a
        export DB_HOST=localhost
    fi
    if [ -f "$SCRIPT_DIR/geister-api.secrets.env" ]; then
        set -a; source "$SCRIPT_DIR/geister-api.secrets.env"; set +a
    fi
    # MCP-specific defaults (override in geister-api.env if needed)
    export GEISTER_MCP_HOST="${GEISTER_MCP_HOST:-127.0.0.1}"
    export GEISTER_MCP_PORT="${GEISTER_MCP_PORT:-5001}"
    # Realms live in the 'staging' registry on the IC ('ic' has no registry id).
    export GEISTER_MCP_NETWORK="${GEISTER_MCP_NETWORK:-staging}"
    export REALMS_PROJECT_DIR="${REALMS_PROJECT_DIR:-/srv/dev/realms}"
    # Tier 2 OAuth: the public issuer/resource id (the tunnel hostname) and the
    # registry consent page the /authorize step redirects the browser to.
    export GEISTER_MCP_PUBLIC_URL="${GEISTER_MCP_PUBLIC_URL:-https://geister-mcp.realmsgos.dev}"
    export GEISTER_OAUTH_CONSENT_URL="${GEISTER_OAUTH_CONSENT_URL:-https://staging.realmsgos.org/connect/authorize}"
}

is_running() {
    [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1
}

start_service() {
    if is_running; then warn "$SERVICE_NAME already running (PID $(cat $PID_FILE))"; return 1; fi
    setup_env
    log "Starting $SERVICE_NAME on ${GEISTER_MCP_HOST}:${GEISTER_MCP_PORT} (network=$GEISTER_MCP_NETWORK)..."
    nohup "$SCRIPT_DIR/venv/bin/python3" "$PROJECT_DIR/mcp_server.py" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"; disown
    sleep 2
    if is_running; then log "$SERVICE_NAME started (PID $(cat $PID_FILE)); logs: $LOG_FILE"
    else error "Failed to start"; rm -f "$PID_FILE"; tail -20 "$LOG_FILE" 2>/dev/null; return 1; fi
}

stop_service() {
    if ! is_running; then warn "$SERVICE_NAME not running"; rm -f "$PID_FILE"; return 0; fi
    PID=$(cat "$PID_FILE"); log "Stopping $SERVICE_NAME (PID $PID)..."
    kill "$PID" 2>/dev/null || true
    for i in {1..10}; do ps -p "$PID" >/dev/null 2>&1 || break; sleep 0.5; done
    ps -p "$PID" >/dev/null 2>&1 && { warn "Force killing..."; kill -9 "$PID" 2>/dev/null || true; }
    rm -f "$PID_FILE"; log "$SERVICE_NAME stopped"
}

case "${1:-start}" in
    start)   start_service ;;
    stop)    stop_service ;;
    status)  is_running && log "running (PID $(cat $PID_FILE))" || warn "not running" ;;
    logs)    tail -f "$LOG_FILE" ;;
    fg)      setup_env; "$SCRIPT_DIR/venv/bin/python3" "$PROJECT_DIR/mcp_server.py" ;;
    restart) stop_service; sleep 1; start_service ;;
    *)       echo "Usage: $0 {start|stop|status|logs|fg|restart}" ;;
esac
