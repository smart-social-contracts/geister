#!/usr/bin/env bash
# Usage: source ./load_secret_envs.sh
# Decrypts secrets.enc.yaml and exports all key-value pairs as environment variables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="${SCRIPT_DIR}/secrets.enc.yaml"
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.age/key.txt}"

if [ ! -f "$SECRETS_FILE" ]; then
  echo "Error: $SECRETS_FILE not found" >&2
  return 1 2>/dev/null || exit 1
fi

if ! command -v sops &>/dev/null; then
  echo "Error: sops is not installed" >&2
  return 1 2>/dev/null || exit 1
fi

while IFS=': ' read -r key value; do
  [[ -z "$key" || "$key" == "sops" ]] && break
  export "$key=$value"
  echo "Exported $key"
done < <(sops -d "$SECRETS_FILE")
