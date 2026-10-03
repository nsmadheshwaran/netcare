#!/bin/sh
# Usage: scripts/restore.sh backups/netcare-XXXX.sql.gz   (OVERWRITES the current database)
# If backups/netcare-XXXX-files.tar.gz exists next to it, uploaded documents are restored too.
set -eu
cd "$(dirname "$0")/.."
. ./.env
[ -f "${1:-}" ] || { echo "backup file required"; exit 1; }
printf "This will overwrite database %s. Type YES to continue: " "$POSTGRES_DB"; read ans
[ "$ans" = "YES" ] || exit 1
docker compose stop backend
gunzip -c "$1" | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
files="${1%.sql.gz}-files.tar.gz"
if [ -f "$files" ]; then
  docker compose run --rm -T --no-deps --entrypoint sh backend -c "rm -rf /app/storage/* && tar -C /app/storage -xzf -" < "$files"
  echo "Restored documents from $files"
else
  echo "No documents archive ($files) found: database only"
fi
docker compose start backend
