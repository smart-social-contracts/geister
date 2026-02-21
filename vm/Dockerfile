FROM python:3.11-slim

# System deps for psycopg2-binary and dfx
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates libpq-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dfx (needed by realm_tools.py for canister calls)
RUN DFXVM_INIT_YES=1 sh -ci "$(curl -fsSL https://internetcomputer.org/install.sh)"
ENV PATH="/root/.local/share/dfx/bin:${PATH}"

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose API port
EXPOSE 5000

CMD ["python3", "api.py"]
