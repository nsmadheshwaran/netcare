#!/bin/sh
# Usage: scripts/restore.sh backups/netcare-XXXX.sql.gz   (OVERWRITES the current database)
set -eu
cd "$(dirname "$0")/.."
. ./.env
[ -f "${1:-}" ] || { echo "backup file required"; exit 1; }
printf "This will overwrite database %s. Type YES to continue: " "$POSTGRES_DB"; read ans
[ "$ans" = "YES" ] || exit 1
docker compose stop backend
gunzip -c "$1" | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
docker compose start backend
