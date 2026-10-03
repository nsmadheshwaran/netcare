# Security

## Implemented
- **Passwords:** Argon2id hashes. Plaintext is never stored. Minimum length is 10.
- **Sessions:** short-lived JWTs (default 60 minutes) signed with `NETCARE_SECRET_KEY`. Changing a password or
  using "sign out everywhere" increments `token_version`, which invalidates every earlier token.
- **Login abuse:** after 5 failed attempts per email and IP address, sign-in is blocked for 5 minutes (HTTP 429).
- **Tenant isolation:** each request resolves the organization from an *active membership*. All queries filter
  on that organization, and objects fetched by ID are re-checked. A foreign ID returns 404, not 403, so callers
  cannot tell whether it exists. Automated tests cover reading, updating, archiving, moving stock in, and
  referencing categories and locations of another tenant.
- **Authorization:** role permissions are enforced in the API (`deps.require`). The UI only hides buttons.
  Only owners can grant or remove the owner role, and an organization always keeps at least one active owner.
- **Technician scope:** technicians (`service.work`) can change only tickets assigned to their own employee
  record. The API enforces this, not just the UI. Closing, cancelling, assigning and billing are office
  actions. Nobody except the owner can approve their own leave. Employee records can only be linked to logins
  that are members of the same business.
- **Input validation:** Pydantic validates every request (GSTIN, PIN, HSN/SAC, email, decimal precision). The
  ORM parameterises all SQL.
- **CSV:** imports are limited to 2 MB, UTF-8 only, and preview first. Exports prefix cells starting with
  `= + - @` to block spreadsheet formula injection.
- **Uploads (logo):** limited to 300 KB and 4000 × 4000 pixels. The type is detected from the file's bytes
  (PNG/JPEG signatures), never from its name or declared type, and the image must decode. Logos are stored in
  the database and served only to signed-in members of that business.
- **PDFs:** user-entered text is XML-escaped before ReportLab renders it, so names like `A & B <Traders>`
  cannot break or inject markup.
- **Reports:** limited to a three-year span per request to bound load; every report run is audited.
- **Headers:** `X-Content-Type-Options`, `X-Frame-Options: DENY`, and `Referrer-Policy` are set. CORS is limited
  to configured origins.
- **Audit log:** creates, updates, archives, stock changes, imports, exports and membership changes are logged
  with the user and IP address.
- **Production guard:** with `NETCARE_ENV=production`, the app refuses to start with the default secret or
  with SQLite.
- **Network:** PostgreSQL has no published port in Docker Compose. The web container binds to 127.0.0.1 only,
  so traffic must come through your HTTPS proxy.

## Known limitations (fix before going live)
- **Tokens live in `localStorage`.** That is simple but readable by any XSS. React escapes output and there is
  no raw HTML rendering, but before production consider httpOnly cookies with CSRF protection.
- **No refresh tokens.** Users sign in again after the token expires.
- **No password reset or email verification yet.** Both need an email provider. For now, an owner adds users
  with a temporary password that the user should change.
- **The login limiter is in memory**, so it only works with a single backend worker (the Docker image runs
  one). Use Redis or the database before scaling out.
- **No general API rate limiting** beyond login. Add it at the reverse proxy (nginx `limit_req`).
- **No Content-Security-Policy header yet.**
- The backend trusts `X-Forwarded-For` because it is only reachable through the proxy. Never publish port 8000
  directly.
- Run dependency audits regularly with `pip-audit` and `npm audit`. Neither has been run in CI yet.

## Reporting
Report vulnerabilities privately to the maintainer. Do not open public issues for them.
