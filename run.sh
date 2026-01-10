#!/bin/bash

set -e # Exit on error
set -x # Print commands

# Start SSH server in the background
echo $SSH_AUTH_KEY >> ~/.ssh/authorized_keys
/usr/sbin/sshd -D -p 2222 &

# Create logs directory if it doesn't exist
mkdir -p logs

# Create workspace directories if they don't exist
mkdir -p /workspace/ollama
mkdir -p /workspace/venv
mkdir -p /workspace/chromadb_data

# Setup Python virtual environment in the persistent volume
if [ ! -d "/workspace/venv/bin/activate" ]; then
    echo "Creating new virtual environment in /workspace/venv..."
    python3 -m venv /workspace/venv
fi

# Activate the virtual environment
source /workspace/venv/bin/activate

export DFX_WARNING=-mainnet_plaintext_identity

# Set default realm ID
export ASHOKA_USE_LLM=true
export ASHOKA_DFX_NETWORK="ic"
echo "ASHOKA_DEFAULT_MODEL=$ASHOKA_DEFAULT_MODEL"
echo "ASHOKA_USE_LLM=$ASHOKA_USE_LLM"
echo "ASHOKA_DFX_NETWORK=$ASHOKA_DFX_NETWORK"

# Export OLLAMA_HOME explicitly
export OLLAMA_HOST=0.0.0.0
export OLLAMA_HOME=/workspace/ollama
export OLLAMA_MODELS=/workspace/ollama/models
# Set default models to pull if not defined
: ${OLLAMA_MODEL_LIST:=${ASHOKA_DEFAULT_MODEL:-"llama3.2:1b"}}
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_HOME=$OLLAMA_HOME"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_MODEL_LIST=$OLLAMA_MODEL_LIST"
chmod -R 777 $OLLAMA_HOME

# Start Ollama in the background
ollama serve 2>&1 | tee -a logs/ollama.log &

# Wait until Ollama is ready (port 11434 open)
echo "Waiting for Ollama to become available..."
while ! nc -z localhost 11434; do
  sleep 1
done

echo "Ollama is up and running at http://localhost:11434"

# Pull the models
echo "Pulling models: $OLLAMA_MODEL_LIST"
for model in $OLLAMA_MODEL_LIST; do
  echo "Pulling model: $model"
  ollama pull $model
done

pip3 install --upgrade pip
pip3 install -r requirements.txt

# # Check if requirements have been installed already
# if [ ! -f "/workspace/venv/.requirements_installed" ]; then
#     echo "Installing Python requirements..."
#     pip3 install --upgrade pip
#     pip3 install -r requirements.txt
#     # Create a flag file to indicate requirements are installed
#     touch /workspace/venv/.requirements_installed
# else
#     echo "Python requirements already installed, skipping installation."
# fi

mkdir -p /app/chromadb_data
chmod 777 /app/chromadb_data

echo "Starting PostgreSQL..."
service postgresql start

sleep 5

echo "Setting up PostgreSQL database..."
sudo -u postgres createdb ashoka_db 2>/dev/null || echo "Database already exists"
sudo -u postgres psql -d ashoka_db -c "CREATE USER ashoka_user WITH PASSWORD 'ashoka_pass';" 2>/dev/null || echo "User already exists"
sudo -u postgres psql -d ashoka_db -c "GRANT ALL PRIVILEGES ON DATABASE ashoka_db TO ashoka_user;" 2>/dev/null || echo "Privileges already granted"

if [ -f "database/schema.sql" ]; then
    echo "Initializing database schema..."
    sudo -u postgres psql -d ashoka_db -f database/schema.sql 2>/dev/null || echo "Schema already initialized"
fi



# Start ChromaDB server in background
echo "Starting ChromaDB server..."
python3 -c "import chromadb.cli.cli; chromadb.cli.cli.app()" run --host 0.0.0.0 --port 8001 --path /app/chromadb_data 2>&1 | tee -a logs/chromadb.log &
CHROMADB_PID=$!

CHROMADB_STARTUP_TIMEOUT=60
echo "Waiting for ChromaDB to be ready in $CHROMADB_STARTUP_TIMEOUT seconds..."
for i in {1..$CHROMADB_STARTUP_TIMEOUT}; do
    if curl -s http://localhost:8001/api/v1/heartbeat > /dev/null 2>&1; then
        echo "ChromaDB is ready!"
        break
    fi
    if [ $i -eq $CHROMADB_STARTUP_TIMEOUT ]; then
        echo "ChromaDB failed to start within $CHROMADB_STARTUP_TIMEOUT seconds"
        exit 1
    fi
    sleep 1
done

# Run API server
echo "Starting API server..."
./start_or_restart_api.sh