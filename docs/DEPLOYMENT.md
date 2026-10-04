# Deployment

> The Docker configuration was trial-run once on a PC (build, migrations, register and sign in all worked), but not on a real server. Do a trial deployment on a staging server before real data.

## Single server with Docker Compose
```bash
cd netcare
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/ready
```
Before starting, edit `.env` and set strong `POSTGRES_PASSWORD` and `NETCARE_SECRET_KEY` values.

The backend container runs `alembic upgrade head` automatically on start. The app listens on
**127.0.0.1:8080 only**; put an HTTPS reverse proxy in front of it.

## HTTPS with Caddy (simplest option)
`/etc/caddy/Caddyfile`:
```
netcare.example.com {
    reverse_proxy 127.0.0.1:8080
}
```
Caddy obtains and renews certificates automatically. Set `NETCARE_CORS_ORIGINS=https://netcare.example.com`.

## HTTPS with nginx
```nginx
server {
    listen 443 ssl http2;
    server_name netcare.example.com;
    ssl_certificate     /etc/letsencrypt/live/netcare.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/netcare.example.com/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    location / {
        limit_req zone=api burst=40 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```
Note: `limit_req_zone` belongs in the `http {}` block.

## Backups
```bash
scripts/backup.sh
scripts/restore.sh backups/netcare-20261002-210000.sql.gz
```
`backup.sh` writes a gzipped `pg_dump` and a `-files.tar.gz` archive of uploaded documents (the `docstore`
volume) to `backups/`. `restore.sh` asks you to confirm, then overwrites the database and, if the matching
files archive is next to the dump, the documents. Keep the two files of one backup together: a database
restored without its documents archive has records whose downloads answer "file missing" (HTTP 410).

Upload limits: `NETCARE_MAX_UPLOAD_MB` (default 15) and `NETCARE_ORG_STORAGE_QUOTA_MB` (default 2048). If you
raise the upload limit above 15 MB, also raise `client_max_body_size` in `frontend/nginx.conf` and in your
HTTPS proxy.

- Schedule `backup.sh` daily with cron and copy `backups/` off the server.
- **A backup is not proven until it has been restored.** Test-restore to a staging server every month.

## Upgrades
```bash
scripts/backup.sh
git pull
docker compose up -d --build
docker compose logs -f backend
```
Always back up first. Migrations run automatically when the backend starts; watch the backend logs for
"Running upgrade". To roll back, restore the backup taken before the upgrade and deploy the previous version.

## Logs
The backend writes one JSON-style line per request to stdout. View them with `docker compose logs backend`.
