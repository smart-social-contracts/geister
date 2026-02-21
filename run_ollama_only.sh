#!/bin/bash
# Pod-only startup: Ollama + Cloudflare tunnel
# API and PostgreSQL now run on the VM (srv1)

set -e
set -x

# Create logs directory
mkdir -p logs

# Create workspace directories
mkdir -p /workspace/ollama

# Export Ollama environment
export OLLAMA_HOST=0.0.0.0
export OLLAMA_HOME=/workspace/ollama
export OLLAMA_MODELS=/workspace/ollama/models
: ${OLLAMA_MODEL_LIST:=${DEFAULT_LLM_MODEL:-"gpt-oss:20b"}}

echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_HOME=$OLLAMA_HOME"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_MODEL_LIST=$OLLAMA_MODEL_LIST"
chmod -R 777 $OLLAMA_HOME

# Start Ollama
ollama serve 2>&1 | tee -a logs/ollama.log &

# Wait until Ollama is ready
echo "Waiting for Ollama to become available..."
while ! nc -z localhost 11434; do
  sleep 1
done
echo "Ollama is up and running at http://localhost:11434"

# Pull models
echo "Pulling models: $OLLAMA_MODEL_LIST"
for model in $OLLAMA_MODEL_LIST; do
  echo "Pulling model: $model"
  ollama pull $model
done

echo "=== Pod ready (Ollama only) ==="
echo "API and database are running on the VM."
