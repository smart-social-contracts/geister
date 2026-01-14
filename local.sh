#!/bin/bash
# Geister local mode manager
# Usage: ./local.sh start|stop|status

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DB_CONTAINER="geister-db"
DB_USER="geister_user"
DB_PASS="geister_pass"
DB_NAME="geister_db"

start_local() {
    echo "🚀 Starting Geister in local mode..."

    # Switch to local mode
    echo "📌 Setting mode to local..."
    geister mode local

    # Check if PostgreSQL container exists
    if docker ps -a --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        if docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
            echo "✅ PostgreSQL container already running"
        else
            echo "🔄 Starting existing PostgreSQL container..."
            docker start $DB_CONTAINER
        fi
    else
        echo "🐘 Creating PostgreSQL container..."
        docker run -d --name $DB_CONTAINER \
            -e POSTGRES_DB=$DB_NAME \
            -e POSTGRES_USER=$DB_USER \
            -e POSTGRES_PASSWORD=$DB_PASS \
            -p 5432:5432 \
            postgres:15-alpine
    fi

    # Wait for PostgreSQL to be ready
    echo "⏳ Waiting for PostgreSQL to be ready..."
    for i in {1..30}; do
        if PGPASSWORD=$DB_PASS psql -h localhost -U $DB_USER -d $DB_NAME -c "SELECT 1" &>/dev/null; then
            echo "✅ PostgreSQL is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "❌ PostgreSQL failed to start"
            exit 1
        fi
        sleep 1
    done

    # Initialize schema
    echo "📋 Initializing database schema..."
    PGPASSWORD=$DB_PASS psql -h localhost -U $DB_USER -d $DB_NAME -f database/schema.sql 2>/dev/null || echo "   Schema already initialized"

    # Start API server
    echo ""
    echo "🌐 Starting API server..."
    echo "   Press Ctrl+C to stop"
    echo ""
    export DB_PASS=$DB_PASS
    export DEFAULT_LLM_MODEL=${DEFAULT_LLM_MODEL:-gpt-oss:20b}
    python api.py
}

stop_local() {
    echo "🛑 Stopping Geister local mode..."

    # Stop PostgreSQL container
    if docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        echo "🐘 Stopping PostgreSQL container..."
        docker stop $DB_CONTAINER
        echo "✅ PostgreSQL stopped"
    else
        echo "ℹ️  PostgreSQL container not running"
    fi

    # Switch back to remote mode
    echo "📌 Setting mode to remote..."
    geister mode remote

    echo "✅ Done"
}

show_status() {
    echo "📊 Geister Local Status"
    echo ""
    
    # Show mode
    geister mode
    
    # Check PostgreSQL
    echo ""
    if docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        echo "🐘 PostgreSQL: running"
    elif docker ps -a --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        echo "🐘 PostgreSQL: stopped"
    else
        echo "🐘 PostgreSQL: not created"
    fi
}

clean_local() {
    echo "🧹 Cleaning Geister local environment..."

    # Stop and remove PostgreSQL container
    if docker ps -a --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        echo "🐘 Removing PostgreSQL container..."
        docker rm -f $DB_CONTAINER
        echo "✅ PostgreSQL container removed"
    else
        echo "ℹ️  PostgreSQL container not found"
    fi

    # Clean up agent identities
    echo "🤖 Removing agent identities..."
    geister agent rm --all --confirm
    echo "✅ Agent identities removed"

    # Switch back to remote mode
    echo "📌 Setting mode to remote..."
    geister mode remote

    echo "✅ Clean complete"
}

case "${1:-}" in
    start)
        start_local
        ;;
    stop)
        stop_local
        ;;
    status)
        show_status
        ;;
    clean)
        clean_local
        ;;
    *)
        echo "Usage: $0 {start|stop|status|clean}"
        echo ""
        echo "  start   Start PostgreSQL and API server in local mode"
        echo "  stop    Stop PostgreSQL and switch to remote mode"
        echo "  status  Show current status"
        echo "  clean   Remove PostgreSQL container, agent identities, and reset to remote mode"
        exit 1
        ;;
esac
