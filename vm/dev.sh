#!/bin/bash
# Dev script to run Geister API locally with hot reload
# Usage: ./vm/dev.sh [start|stop|status|logs|fg]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEV]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

SERVICE_NAME="geister-api"
PID_FILE="$SCRIPT_DIR/.dev.pid"
LOG_FILE="$SCRIPT_DIR/dev.log"

setup_env() {
    # Stop any Docker containers that might conflict
    for container in $(docker ps --format '{{.Names}}' | grep -E "geister-api" 2>/dev/null); do
        warn "Stopping Docker container ${container}..."
        docker stop "$container" 2>/dev/null || true
    done

    # Create venv if it doesn't exist
    if [ ! -d "$SCRIPT_DIR/venv" ] || [ ! -f "$SCRIPT_DIR/venv/bin/activate" ]; then
        log "Creating virtual environment..."
        python3 -m venv "$SCRIPT_DIR/venv"
        source "$SCRIPT_DIR/venv/bin/activate"
        pip install -r "$PROJECT_DIR/requirements.txt"
    else
        source "$SCRIPT_DIR/venv/bin/activate"
    fi

    # Load env file with DB_HOST override for local dev
    if [ -f "$SCRIPT_DIR/geister-api.env" ]; then
        set -a
        source "$SCRIPT_DIR/geister-api.env"
        set +a
        # Override DB_HOST for local dev (docker-compose uses "postgres" service name)
        export DB_HOST=localhost
        log "Loaded geister-api.env (DB_HOST=localhost)"
    fi
}

is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

start_service() {
    if is_running; then
        warn "$SERVICE_NAME is already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    setup_env

    log "Starting $SERVICE_NAME on port 5000 (background)..."

    nohup "$SCRIPT_DIR/venv/bin/python3" "$PROJECT_DIR/api.py" \
        >> "$LOG_FILE" 2>&1 &

    echo $! > "$PID_FILE"
    disown

    sleep 2
    if is_running; then
        log "$SERVICE_NAME started (PID: $(cat $PID_FILE))"
        log "Logs: $LOG_FILE"
    else
        error "Failed to start $SERVICE_NAME"
        rm -f "$PID_FILE"
        tail -20 "$LOG_FILE" 2>/dev/null
        return 1
    fi
}

stop_service() {
    if ! is_running; then
        warn "$SERVICE_NAME is not running"
        rm -f "$PID_FILE"
        return 0
    fi

    PID=$(cat "$PID_FILE")
    log "Stopping $SERVICE_NAME (PID: $PID)..."
    kill "$PID" 2>/dev/null || true

    # Wait for process to stop
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done

    # Force kill if still running
    if ps -p "$PID" > /dev/null 2>&1; then
        warn "Force killing..."
        kill -9 "$PID" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    log "$SERVICE_NAME stopped"
}

status_service() {
    if is_running; then
        log "$SERVICE_NAME is running (PID: $(cat $PID_FILE))"
    else
        warn "$SERVICE_NAME is not running"
    fi
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        warn "No log file found"
    fi
}

run_foreground() {
    if is_running; then
        error "$SERVICE_NAME is already running in background (PID: $(cat $PID_FILE))"
        error "Stop it first with: ./vm/dev.sh stop"
        return 1
    fi

    setup_env

    log "Starting $SERVICE_NAME on port 5000 (foreground)..."
    log "Press Ctrl+C to stop"
    log ""

    python3 "$PROJECT_DIR/api.py"
}

show_help() {
    echo ""
    echo "=============================================="
    echo "  Geister API Dev Script"
    echo "=============================================="
    echo ""
    echo "USAGE: $0 {start|stop|status|logs|fg|restart|help}"
    echo ""
    echo "COMMANDS:"
    echo "  start   - Start service in background (survives SSH disconnect)"
    echo "  stop    - Stop the background service"
    echo "  status  - Show service status"
    echo "  logs    - Tail the log file (Ctrl+C to exit)"
    echo "  fg      - Run in foreground (Ctrl+C to stop)"
    echo "  restart - Restart the service"
    echo "  help    - Show this help message"
    echo ""
    echo "MECHANISM:"
    echo "  - Runs Flask API on port 5000"
    echo "  - Uses nohup + disown to survive SSH disconnects"
    echo "  - Overrides DB_HOST=localhost for local PostgreSQL"
    echo "  - Stores PID in .dev.pid for process management"
    echo "  - Logs output to dev.log"
    echo ""
    echo "CONTAINER HANDLING:"
    echo "  - Automatically stops any running 'geister-api' Docker containers"
    echo ""
    echo "FILES:"
    echo "  - PID file: $PID_FILE"
    echo "  - Log file: $LOG_FILE"
    echo "  - Env file: $SCRIPT_DIR/geister-api.env"
    echo ""
}

case "${1:-start}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    status)
        status_service
        ;;
    logs)
        show_logs
        ;;
    fg|foreground)
        run_foreground
        ;;
    restart)
        stop_service
        sleep 1
        start_service
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
