FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# --- System setup ---
ENV DEBIAN_FRONTEND=noninteractive

# Update package lists and fix broken packages
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y --fix-broken
RUN apt-get update
RUN apt-get install -y --no-install-recommends \
    curl git python3 python3-pip python3-venv unzip sudo nano wget jq netcat net-tools openssh-server \
    ca-certificates \
    gnupg \
    lsb-release \
    build-essential \
    zstd
RUN apt-get install -y --no-install-recommends postgresql postgresql-contrib

# --- Cloudflared installation ---
RUN curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb && \
    dpkg -i /tmp/cloudflared.deb && \
    rm /tmp/cloudflared.deb

RUN apt-get clean

# --- Create persistent volumes ---
RUN mkdir -p /workspace/ollama
RUN mkdir -p /workspace/venv
RUN mkdir -p /workspace/chromadb_data


# --- SSH server ---
RUN mkdir -p ~/.ssh
RUN touch ~/.ssh/authorized_keys
RUN chmod 700 ~/.ssh
RUN chmod 600 ~/.ssh/authorized_keys
RUN mkdir -p /run/sshd

# --- Git configuration ---
RUN git config --global user.name "Docker User"
RUN git config --global user.email "docker@container.local"
RUN git config --global init.defaultBranch main
# Trust the workspace directory for Git operations
RUN git config --global --add safe.directory /app/geister

ARG DFX_VERSION=0.29.0
RUN DFX_VERSION=${DFX_VERSION} DFXVM_INIT_YES=true sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)"
ENV PATH="/root/.local/share/dfx/bin:$PATH"

# --- Ollama installation ---
RUN curl -fsSL https://ollama.com/install.sh | sh
ENV PATH="/root/.ollama/bin:${PATH}"
ENV OLLAMA_HOME=/workspace/ollama

# --- PostgreSQL setup ---
USER postgres
RUN /etc/init.d/postgresql start && \
    psql --command "CREATE USER geister_user WITH SUPERUSER PASSWORD 'geister_pass';" && \
    createdb -O geister_user geister_db
USER root

# --- Configure PostgreSQL for external connections ---
RUN sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/14/main/postgresql.conf
RUN echo 'host    all             all             0.0.0.0/0               scram-sha-256' >> /etc/postgresql/14/main/pg_hba.conf

# --- Cloudflared setup ---
# Config is baked in; credentials injected at runtime via CLOUDFLARED_CREDS_B64
RUN mkdir -p /root/.cloudflared
COPY cloudflared/config.yml /root/.cloudflared/config.yml

# --- App environment ---
WORKDIR /app/geister

# Copy all files from the geister folder
COPY . .

# Note: Python dependencies will be installed by run.sh into the persistent volume
# This prevents duplicate installations and allows for faster container restarts

# Ollama
EXPOSE 11434

# PostgreSQL
EXPOSE 5432

# ChromaDB
EXPOSE 8001

# SSH
EXPOSE 2222

# Flask (API)
EXPOSE 5000


CMD ["./start.sh"]
