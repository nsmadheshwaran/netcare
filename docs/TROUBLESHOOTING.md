# Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `alembic` is not recognized | Python Scripts folder is not on PATH. Use `python -m alembic ...` |
| `no such table: users` | Migrations not applied. Run `python -m alembic upgrade head` in `backend/` |
| Frontend shows "Request failed" or a proxy error | The API is not running on port 8000. Start uvicorn |
| Always sent back to the sign-in page | Token expired (60 minutes by default) or password changed. Sign in again |
| `Too many failed attempts` | 5 wrong passwords in 5 minutes. Wait, or restart the backend in development |
| `Organization not found` | You are not an active member of the selected business, or the owner deactivated you |
| `Insufficient stock` | The movement would make stock negative at that location. Check **Stock levels** |
| `Possible duplicate of customer #N` | Phone, email or GSTIN matches an existing customer. Use **Save anyway** if it is a different person |
| CSV import says "must be UTF-8" | In Excel choose *Save As → CSV UTF-8* |
| Backend refuses to start: `NETCARE_SECRET_KEY must be set` | `NETCARE_ENV=production` with the default key. Set a long random key |
| `npm run build` fails on Node 18 or 20 | Vite 8 needs Node 22.12 or later |
| Times look wrong by 5:30 | Fixed in 0.1.0 (timestamps are UTC-aware). Pull the latest code |
