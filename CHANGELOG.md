# Changelog

## Unreleased
### Fixed
- Dashboard "Stock value (at cost)" showed 0 when cost came from stock-in rather than the product's list purchase price; it now uses the average cost, like the stock valuation report.
- The SKU and document-prefix input patterns were invalid regular expressions in current browsers, so the browser skipped that validation.

## 1.1.2 (2026-10-04)
### Fixed
- Docker: the backend container crashed on start (alembic could not find the app package). First trial run of the compose setup on a PC: build, migrations, register and sign in all work.

## 1.1.1 (2026-10-04)
### Added
- Email an invoice to the customer (or another address) from the invoice page; credit note PDF; sign-on-tablet approval for service tickets.
### Fixed
- Email invoice now needs edit permission, validates the address and refuses draft/cancelled invoices.
- Credit note PDF button called the wrong URL.
- Signature pad no longer claims the signature was stored (the image is not saved; the approval note says so), and strokes/scaling are correct.
- Tests close leaked database sessions (PostgreSQL CI failure). 144 backend tests.

## 1.1.0 (2026-10-04)
### Added
- Stay signed in: rotating refresh tokens (30 days), silent renewal in the app, reuse detection; sign out ends
  the session.
- Emailed invitations (no temporary password needed) and "Forgot password?" with single-use links; owners can
  email a new link to a locked-out member.
- GitHub Actions CI: backend on SQLite and PostgreSQL 16 (with a full migration down/up), frontend checks,
  Docker builds with `nginx -t`, Playwright browser tests.
- SNMP v2c read-only checks (GET of listed OIDs only) with readings in the check details; agent 1.2.0.
- `install-agent.ps1` / `uninstall-agent.ps1`: one-command Windows install as a visible startup task.
- SMS/WhatsApp alerts through Twilio or a webhook bridge; per-user opt-in and mobile number; urgent kinds only.
- Migrations `0009`-`0011`. Test count: 141 backend tests (was 127), 5 frontend tests (was 3).

## 1.0.0 (2026-10-03): Phase 10, pilot release
### Added
- Module switches (Settings → Modules): Buying and selling, Finance, Service, People, Documents, Network
  monitoring, Endpoint security. Enforced by the API (switched-off permissions are removed for every role),
  reflected in the menu, reports, notifications and agents; data is kept.
- Get started checklist on the Overview, computed from real data.
- Owners and managers can reset a staff member's password (not for logins shared with another business).
- Tests: end-to-end business day across every module; automated tenant-isolation sweep over every endpoint.
- `docs/PILOT.md` go-live checklist.

### Security
- nginx no longer forwards client-supplied `X-Forwarded-For` (clients could fake their IP for the login rate
  limit and audit log).
- Rate limits for login, agent and API requests; Content-Security-Policy and Permissions-Policy headers;
  static-file locations no longer drop the security headers.
- Saving business details can no longer switch modules back on by omission.

## 0.9.0 (2026-10-03): Phase 9, notifications
### Added
- In-app notifications: header bell with unread count, Alerts page (unread/all, mark read, open the related
  page), per-user preferences for each kind, in the app and by email.
- Events: device down and back up, PC security critical, service job and task assigned to you, leave request
  and decision. Daily digests: overdue invoices, low stock, maintenance due, agents not reporting, documents
  expiring (counted per person's visibility). Never about your own action; never repeated (dedupe keys).
- Email through your SMTP server (`NETCARE_SMTP_*`), queued in an outbox and retried with back-off; test email;
  delivery log for owners. Background worker thread once a minute (`NETCARE_NOTIFICATIONS_WORKER`).
- Migration `0008`. Test count: 120 backend tests (was 112).

## 0.8.0 (2026-10-03): Phase 8, data organizer
### Added
- `organizer/netcare_organizer.py`: local command-line tool (standard library only, no network code).
  `plan` finds duplicates (size, then partial and full SHA-256) and optionally sorts loose files into
  Type\YYYY-MM; `preview` writes an HTML page; `apply` is a dry run until actions are approved; every move is
  journaled before and after; `rollback` undoes newest first; `verify-backup` compares by SHA-256 and says
  "verified" only when every file matches. Never deletes, never overwrites, refuses system folders and whole
  drives, skips locked or changed files.
- Data Organizer page with the safety rules and commands.
- Test count: 112 backend tests (was 101).

## 0.7.0 (2026-10-03): Phase 7, endpoint security visibility
### Added
- Agents can report their PC's Microsoft Defender status (opt-in per agent, Windows, read-only `Get-Mp*`
  cmdlets every 15 minutes): protection switches, mode, versions, definition and scan times, and detections of
  the last 30 days. Agent version 1.1.0.
- Endpoint Security page: each PC rated critical / needs attention / protected / not reporting, with the
  reasons in plain words and what to do; detection history; link a PC to its equipment record; "Mark
  reviewed" notes for resolved detections. "Endpoint security" report.
- Migration `0007`. Test count: 101 backend tests (was 91).

### Fixed
- Monitoring outages stayed open forever when a check was disabled or its agent revoked, inflating downtime.
- Editing a document with `null` for title, category or the sensitive flag returned a server error.
- Checks belonging to a revoked agent could not be edited or disabled.

## 0.6.0 (2026-10-03): Phase 6, monitoring and CCTV
### Added
- Monitoring agent (`agent/netcare_agent.py`, Python standard library only): fetches its checks, runs ping and
  TCP-port checks, queues results on disk while offline, retries with backoff, stops when its token is revoked.
  Install and uninstall steps in `docs/MONITORING_AGENT.md`.
- Agents with per-agent tokens (shown once, stored hashed, rotate and revoke); checks with interval, timeout,
  failure threshold and latency warning; single-host targets only.
- Up/slow/down/unknown status, outages (from the first failure to recovery), uptime and latency statistics for
  24 hours, 7 and 30 days, latency chart, overview tiles; "Uptime and latency" report.
- CCTV page: recorders with storage and retention, cameras by channel. Equipment gains MAC address, firmware,
  recorder and channel, resolution, storage and retention, and shows its live network status.
- Migration `0006`. Test count: 91 backend tests (was 80).

## 0.5.0 (2026-10-03): Phase 5, documents and analytics
### Added
- Document library: upload PDF, images, Word/Excel (no macros), text and CSV up to 15 MB; attach to customers,
  suppliers, products, invoices, bills, purchase orders, expenses, service tickets, equipment or employees, or
  keep as general documents. Categories, tags, notes and expiry dates; search and filters.
- File type detected from the bytes; files stored on disk under random names with a SHA-256 checksum; per
  business storage quota; duplicate uploads to the same record refused.
- Access follows the attached record (you only see documents on records you can see). Sensitive and deleted
  documents are for owners and managers; purge (permanent removal) is owner-only. Uploads, downloads and
  changes are audited.
- Attachment panels on service tickets, customer accounts and customer equipment. Technicians can attach to
  their own jobs.
- Analytics page: sales, gross profit, collections, expenses, invoices, new customers and service jobs compared
  with the previous period, trend charts, top products/customers/categories, collections by method.
- "Export all reports": one ZIP with every report for a period. New "Documents expiring" report.
- Migration `0005`. Docker Compose `docstore` volume; `backup.sh` and `restore.sh` include documents.
  Test count: 80 backend tests (was 70).

### Changed
- nginx accepts request bodies up to 16 MB (was 5 MB) for document uploads.
- The Vite dev proxy target can be set with `NETCARE_API_URL`.

## 0.4.0 (2026-10-03): Phase 4, service and employees
### Added
- Service tickets (repair, installation, maintenance, complaint) with an enforced status workflow, priorities,
  technician assignment, visit scheduling and a timeline of notes and changes.
- Estimates need recorded customer approval before work can start. Warranty jobs skip approval and billing.
- Parts used on a job leave stock immediately at moving-average cost; unused parts can be returned.
  Billing a ticket creates a draft invoice whose part lines do not deduct stock again. Cancelling that invoice
  does not restock the parts, and the ticket can be invoiced again.
- Technician permission (`service.work`): only tickets assigned to your own employee record. Closing and
  cancelling are office-only.
- Customer equipment (assets) with warranty status, IP, site location, service history and replacements.
  Completed installations register equipment and can start a maintenance schedule in one step.
- Maintenance schedules that create visit tickets and roll forward from the completion date.
- Employees (optionally linked to logins), attendance (bulk daily entry, corrections audited), leave requests
  with approval (approved leave marks attendance; nobody approves their own leave except the owner), tasks.
- My work page; job sheet and completion report PDFs (installations list the equipment installed).
- Reports: service performance, warranty expiry, maintenance due, task completion, attendance. Dashboard service tiles.
- Migration `0004`. Test count: 70 backend tests (was 60).

### Changed
- Tests copy a database migrated once per session instead of migrating per test (66 s to about 20 s).

### Fixed
- An invalid item in the equipment registration list returned a server error instead of a validation error.


## 0.3.0 (2026-10-02): Phase 3, finance, GST support and documents
### Added
- Money accounts (cash, bank, other) with opening balances and defaults. Payments now record which account
  they used; payments without one go to the default cash or bank account.
- Expenses and other income by category, with claimable GST recorded separately; transfers between accounts;
  void with reason.
- Moving-average costing: products carry `avg_cost`, issued invoice lines store `unit_cost`, and returns and
  cancellations go back into stock at their original cost.
- Ten reports (profit and loss, cash flow, daily closing, sales and purchase registers, expenses, receivables
  and payables ageing, stock valuation, draft GST summary), each as JSON, CSV, Excel or PDF.
- Printable A4 tax invoice and quotation, 80 mm thermal receipt, and payment receipt/voucher, with amounts in
  words using lakh and crore.
- Business logo upload (PNG/JPEG checked by content, 300 KB limit).
- Versioned GST rate master, enforced by document date once configured; tax-inclusive (MRP) pricing.
- Business-local dates (IST, configurable offset) for "today", overdue status, the dashboard and reports.
- Migration `0003`. Test count: 60 backend tests (was 44). pyflakes added to the dev requirements.

### Fixed
- Dashboard "today" used the UTC date and was wrong between midnight and 05:30 IST.
- New products started with zero average cost, so stock added without a cost looked free.


## 0.2.0 (2026-10-02): Phase 2, business management
### Added
- Suppliers with payment terms and outstanding balances.
- Purchase orders with an approval step (`purchases.approve`), partial and full goods receipts that add stock,
  and close or cancel actions.
- Supplier bills linked to orders, with duplicate bill-number protection, and purchase returns that reduce
  stock and the bill balance.
- Quotations with status tracking and expiry, converted into draft invoices.
- Sales invoices: drafts, then issue (number, stock deduction and receivable in one transaction); cancellation
  restores stock; derived overdue status.
- Credit notes for partial or full returns, with optional restocking; the final credit takes the exact
  remaining paisa.
- Payments in and out with allocation, advances, later allocation, and voiding.
- Billing engine (`services/billing.py`): Decimal maths, line and document discounts, CGST/SGST/IGST split,
  rupee rounding, and financial-year document numbering with configurable prefixes.
- Customer account view, dashboard sales/purchase/receivable/payable figures, and new UI pages for suppliers,
  sales, quotations, purchases and payments.
- Migration `0002`. Test count: 44 backend tests (was 23).

### Fixed
- **Data loss in SQLite migrations:** batch table rebuilds fired `ON DELETE CASCADE` and deleted child rows.
  Foreign keys are now off during migrations, and a regression test proves data survives an
  upgrade/downgrade/upgrade cycle. PostgreSQL deployments were not affected.
- Migrations no longer import application code (custom column types now render as plain SQLAlchemy types).
- A race when two requests started a new numbering sequence at the same moment.

## 0.1.0 (2026-10-02): Milestone 1, foundation
### Added
- FastAPI backend with versioned `/api/v1`, Swagger docs, and health/readiness endpoints.
- Alembic migration `0001`: organizations, users, memberships, locations, customers, product categories,
  products, stock levels, stock movements, audit logs.
- Registration, login (Argon2, JWT, rate limited), password change, and sign-out on all devices.
- Multi-tenant organization context, 8 roles with server-side permissions, user management with
  owner safeguards.
- Customers: CRUD, validation, search, archive, duplicate detection, CSV import (mapping, preview) and export.
- Products and categories; services; decimal prices; GST and HSN fields.
- Inventory: movements, adjustments, transfers, idempotency, no negative stock, append-only ledger.
- Dashboard with period and location filters, computed from the database.
- React + TypeScript + Tailwind frontend with light and dark modes and a responsive layout.
- Docker Compose (PostgreSQL, backend, nginx), backup and restore scripts, and documentation.
- 23 backend tests and 3 frontend tests.

### Fixed during development
- Price-change audit recorded the new price as the old price.
- CSV import missed in-file duplicates that shared only one identifier.
- Timestamps were read back without a timezone on SQLite and displayed 5:30 off in IST.
