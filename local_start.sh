#!/bin/bash
# Start Geister in local mode
# Usage: ./local_start.sh

set -e

echo "🚀 Starting Geister in local mode..."

# Switch to local mode
echo "📌 Setting mode to local..."
geister mode local

# Check if PostgreSQL container exists
if docker ps -a --format '{{.Names}}' | grep -q '^geister-db$'; then
    # Container exists, check if running
    if docker ps --format '{{.Names}}' | grep -q '^geister-db$'; then
        echo "✅ PostgreSQL container already running"
    else
        echo "🔄 Starting existing PostgreSQL container..."
        docker start geister-db
    fi
else
    echo "🐘 Creating PostgreSQL container..."
    docker run -d --name geister-db \
        -e POSTGRES_DB=geister_db \
        -e POSTGRES_USER=geister_user \
        -e POSTGRES_PASSWORD=geister_pass \
        -p 5432:5432 \
        postgres:15-alpine
fi

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if PGPASSWORD=geister_pass psql -h localhost -U geister_user -d geister_db -c "SELECT 1" &>/dev/null; then
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
PGPASSWORD=geister_pass psql -h localhost -U geister_user -d geister_db -f database/schema.sql 2>/dev/null || echo "   Schema already initialized"

# Start API server
echo ""
echo "🌐 Starting API server..."
echo "   Press Ctrl+C to stop"
echo ""
export DB_PASS=geister_pass
geister server start
