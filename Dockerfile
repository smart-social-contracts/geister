FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# --- System setup ---
ENV DEBIAN_FRONTEND=noninteractive

# Minimal packages: only what's needed for Ollama + Cloudflare tunnel
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates netcat zstd && \
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

# --- Cloudflared setup ---
# Config is baked in; credentials injected at runtime via CLOUDFLARED_CREDS_B64
RUN mkdir -p /root/.cloudflared
COPY cloudflared/config.yml /root/.cloudflared/config.yml

# --- Startup scripts ---
WORKDIR /app/geister
COPY start.sh run_ollama_only.sh ./
RUN chmod +x start.sh run_ollama_only.sh

# Ollama
EXPOSE 11434

CMD ["./start.sh"]
