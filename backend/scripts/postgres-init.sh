#!/usr/bin/env bash
# Runs once on fresh volume creation via /docker-entrypoint-initdb.d/.
# Creates the non-superuser app role the API connects as (RLS applies to it).
# Only runs on an empty data volume (down -v), so the role cannot pre-exist —
# no IF NOT EXISTS guard needed.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname   "$POSTGRES_DB" \
     --variable="app_db_password=$APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE terramind_app LOGIN PASSWORD :'app_db_password';
EOSQL