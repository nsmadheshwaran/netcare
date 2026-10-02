# Installation (local development)

## Requirements
| Tool | Tested version | Notes |
|---|---|---|
| Python | 3.14 (3.12+ should work) | `python --version` |
| Node.js | 24 (Vite 8 needs 22.12 or later) | `node --version` |
| PostgreSQL | optional locally | SQLite is used if `NETCARE_DATABASE_URL` is not set |
| Docker | optional | for the full stack, see DEPLOYMENT.md |

## Backend
```bash
cd netcare/backend
python -m pip install -r requirements-dev.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```
`alembic upgrade head` creates or updates the database schema.

Configuration comes from environment variables prefixed with `NETCARE_`, or from `backend/.env`:

| Variable | Default | Meaning |
|---|---|---|
| `NETCARE_DATABASE_URL` | `sqlite:///./netcare_dev.db` | e.g. `postgresql+psycopg://netcare:pw@localhost:5432/netcare` |
| `NETCARE_SECRET_KEY` | dev-only value | JWT signing key. Required in production, at least 32 characters |
| `NETCARE_ENV` | `development` | `production` refuses to start with SQLite or the default key |
| `NETCARE_CORS_ORIGINS` | `http://localhost:5173` | comma-separated list |
| `NETCARE_ACCESS_TOKEN_MINUTES` | `60` | |

## Frontend
```bash
cd netcare/frontend
npm install
npm run dev
```
The dev server runs on http://localhost:5173 and proxies `/api` to port 8000.

## Using PostgreSQL locally
Install PostgreSQL 16, then:
```sql
CREATE USER netcare WITH PASSWORD 'choose-one';
CREATE DATABASE netcare OWNER netcare;
```
Set `NETCARE_DATABASE_URL`, then run `python -m alembic upgrade head` again.
