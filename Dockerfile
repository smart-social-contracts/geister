FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# --- System setup ---
ENV DEBIAN_FRONTEND=noninteractive

# System packages: Ollama + Cloudflare tunnel + Python + PostgreSQL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates netcat zstd \
        python3 python3-pip python3-venv libpq-dev \
        postgresql postgresql-contrib sudo && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Cloudflared installation ---
RUN curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb && \
    dpkg -i /tmp/cloudflared.deb && \
    rm /tmp/cloudflared.deb

# --- Persistent volume for Ollama models ---
RUN mkdir -p /workspace/ollama

# --- Ollama installation ---
RUN curl -fsSL https://ollama.com/install.sh | sh
ENV PATH="/root/.ollama/bin:${PATH}"
ENV OLLAMA_HOME=/workspace/ollama

# --- dfx installation (needed by realm_tools.py for canister calls) ---
RUN DFXVM_INIT_YES=1 sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)" && \
    /root/.local/share/dfx/bin/dfxvm install 0.29.0
ENV PATH="/root/.local/share/dfx/bin:${PATH}"

# --- Cloudflared setup ---
# Config is baked in; credentials injected at runtime via CLOUDFLARED_CREDS_B64
RUN mkdir -p /root/.cloudflared
COPY cloudflared/config.yml /root/.cloudflared/config.yml

# --- Application code ---
WORKDIR /app/geister

# Install Python dependencies first for better caching
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chmod +x start.sh run_ollama_only.sh

# Ollama + Flask API
EXPOSE 11434 5000

CMD ["./start.sh"]
