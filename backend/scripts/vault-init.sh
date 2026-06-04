#!/usr/bin/env bash
# Standalone Vault seeder — run outside compose (developer convenience).
# The compose stack uses the vault-init service instead.
# Requires: VAULT_ADDR, VAULT_TOKEN, ANTHROPIC_API_KEY, JWT_SIGNING_KEY in env.
set -euo pipefail

: "${VAULT_ADDR:?VAULT_ADDR must be set}"
: "${VAULT_TOKEN:?VAULT_TOKEN must be set}"
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"
: "${JWT_SIGNING_KEY:?JWT_SIGNING_KEY must be set}"

export VAULT_ADDR VAULT_TOKEN

vault kv put secret/terra-mind/anthropic api_key="$ANTHROPIC_API_KEY"
vault kv put secret/terra-mind/jwt        signing_key="$JWT_SIGNING_KEY"

echo "vault-init: secrets seeded at secret/terra-mind/{anthropic,jwt}"
