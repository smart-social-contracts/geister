#!/bin/bash
# Pod entrypoint: Cloudflare tunnel + Ollama
# API and database run on the VM — see vm/setup.sh

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

./run_ollama_only.sh

sleep 99999999  # Keep container alive