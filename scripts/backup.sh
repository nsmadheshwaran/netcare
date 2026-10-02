#!/bin/sh
# Usage: scripts/backup.sh   -> writes backups/netcare-YYYYmmdd-HHMMSS.sql.gz
set -eu
cd "$(dirname "$0")/.."
. ./.env
mkdir -p backups
f="backups/netcare-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists | gzip > "$f"
# A backup is only trusted once it has been test-restored; see docs/DEPLOYMENT.md.
gzip -t "$f" && echo "Wrote $f ($(du -h "$f" | cut -f1))"
