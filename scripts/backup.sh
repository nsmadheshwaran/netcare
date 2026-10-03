#!/bin/sh
# Usage: scripts/backup.sh   -> writes backups/netcare-YYYYmmdd-HHMMSS.sql.gz
#                                  and backups/netcare-YYYYmmdd-HHMMSS-files.tar.gz (uploaded documents)
set -eu
cd "$(dirname "$0")/.."
. ./.env
mkdir -p backups
stamp="$(date +%Y%m%d-%H%M%S)"
f="backups/netcare-$stamp.sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists | gzip > "$f"
# Files are taken after the dump, so every document row in the dump has its file (new uploads may be extra).
d="backups/netcare-$stamp-files.tar.gz"
docker compose exec -T backend tar -C /app/storage -czf - . > "$d"
# A backup is only trusted once it has been test-restored; see docs/DEPLOYMENT.md.
gzip -t "$f" && gzip -t "$d" && echo "Wrote $f ($(du -h "$f" | cut -f1)) and $d ($(du -h "$d" | cut -f1))"
