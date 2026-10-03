# NetCare Business Suite

**One Platform to Manage Your Business and IT Infrastructure.**

A multi-tenant business management platform for Indian small businesses: computer shops, CCTV installers,
IT service providers, electronics retailers, schools and SMBs.

> **Status: Phase 5 (documents and analytics) complete.** Business management, finance and reports, service
> and repair tickets, technicians, customer equipment, maintenance schedules, employees, attendance, leave,
> tasks, a secure document library, analytics, network monitoring, CCTV records and endpoint security visibility
> work end to end, plus a local data organizer. Notifications are **not built yet**. They show as "Planned" in
> the UI and appear on the dashboard as "Not yet available", with no placeholder numbers.

## What works today

| Area | Capabilities |
|---|---|
| Accounts | Self-service registration (creates the business, an owner, and a "Main" location), sign-in, password change, sign-out on all devices, login rate limiting |
| Organizations | Business profile (GSTIN, state code, address), multiple locations, adding users with any of 8 roles, deactivating users, last-owner protection |
| Access control | Server-side role permissions; every query is scoped to the caller's organization |
| Customers | Individual/business customers, GSTIN/PIN validation, search, sort, pagination, archive/restore, duplicate detection (phone/email/GSTIN), CSV export (formula-injection safe), CSV import with column mapping, preview, and per-row errors |
| Products | Categories, SKU (unique per org), barcode, brand/model, HSN/SAC, prices (decimal), GST rate field, min stock, warranty months, serial-tracking flag, services (no stock), archive/restore |
| Inventory | Stock in/out, signed adjustments, damaged, customer/supplier returns, transfers between locations; append-only movement ledger with running balance; negative stock blocked; idempotency keys; row locking on PostgreSQL |
| Suppliers | GSTIN, state code, payment terms, outstanding balance |
| Purchasing | Purchase orders (draft, approve, partial or full receipt, close, cancel); goods receipts add stock; supplier bills (duplicate bill numbers blocked, due date from terms); purchase returns reduce stock and the bill balance |
| Sales | Quotations (sent, accepted, rejected, expiry) converted to draft invoices; invoices with line and invoice-level discounts; issuing assigns the number and deducts stock in one transaction; cancellation restores stock; credit notes for partial or full returns, with or without restocking |
| Payments | Cash, UPI, bank transfer, card, cheque, other; allocation across invoices or bills; advances applied later; void with reason (keeps the record) |
| Tax (records only) | Per-line GST rate and HSN/SAC; CGST/SGST or IGST from your state code vs. the place of supply; optional rounding to the rupee |
| Finance | Cash/bank accounts with opening balances, expenses and other income by category (GST you can claim recorded separately), transfers between accounts, void with reason |
| Costing | Moving-average cost per product, captured on each invoice line at issue; returns go back in at their original cost |
| Reports | Profit and loss summary, cash flow by account, daily closing, sales/purchase registers, expenses, receivables and payables ageing, stock valuation, draft GST summary; each as screen, PDF, Excel or CSV |
| Documents | A4 GST invoice and quotation (logo, HSN, CGST/SGST or IGST, amount in words, payment instructions), 80 mm thermal receipt, payment receipt/voucher |
| Tax | Versioned GST rate master (retire and add, never edit) enforced on document dates once configured; tax-inclusive (MRP) pricing per invoice |
| Service | Repair, installation, maintenance and complaint tickets with an enforced status workflow; estimates need recorded customer approval before work starts; parts are taken from stock when used and returned if unused; one-click draft invoice for parts and labour (no double stock deduction); timeline of notes, calls and changes; job sheet and completion report PDFs |
| Technicians | "My work" page with assigned jobs, today's visits and tasks; technicians can update only their own tickets (enforced by the API) |
| Customer equipment | Cameras, DVR/NVRs, computers, network gear per customer site with serial, IP, location, warranty status, service history and replacement records; installations register equipment in one step |
| Maintenance | Recurring schedules (AMC visits) that create visit tickets and roll forward when the job is completed |
| People | Employees (optionally linked to a login), daily attendance, leave requests and approval (approved leave fills attendance), tasks with owners and due dates. No payroll |
| Documents | Upload PDF, images, Word/Excel (no macros), text and CSV (type checked from the bytes, 15 MB, per-business quota); attach to customers, suppliers, products, invoices, bills, orders, expenses, service jobs, equipment or employees; expiry dates and an expiry report; sensitive documents for owners/managers; soft delete, restore, owner-only purge; every download audited |
| Analytics | Sales, gross profit, collections, expenses, invoices, new customers and service jobs against the previous period; trend charts; top products, customers, categories and payment methods |
| Monitoring | Agents at customer sites (outbound HTTPS only, revocable per-agent tokens) run ping and TCP-port checks you configure; up/slow/down/unknown status, outages, uptime and latency charts, uptime report. No scanning or discovery |
| CCTV | DVR/NVR with storage and retention, cameras by channel, MAC/firmware, warranty and live network status |
| Endpoint security | Microsoft Defender status of PCs running the agent (opt-in, read-only): protection switches, definition age, scans, 30-day detections; critical / needs attention / protected / not reporting with reasons and next steps; review notes |
| Data organizer | Local tool (no network): duplicates by SHA-256, optional sorting by type and month, HTML preview, dry run, approval by number, journal and rollback, never deletes; backup verification by hash |
| Report pack | Every report for a period in one ZIP (Excel, PDF or CSV) for the accountant |
| Numbering | Gap-free, per organization and financial year (e.g. `INV/2026-27/00001`), configurable prefixes, row-locked |
| Dashboard | Period (day/week/month/quarter/FY) and location filters; invoiced, received, receivables (and overdue), payables, sales vs purchases chart; customer counts, stock valuation at cost, low/out-of-stock, activity chart, recent activity, all from the database |
| Audit | Every create/update/archive/stock change/import/export is logged with the user and IP address |
| UI | React + Tailwind, responsive, light/dark mode, empty/loading/error states, confirmation dialogs |

## Quick start (local, Windows)

```bash
cd netcare/backend
python -m pip install -r requirements-dev.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd netcare/frontend
npm install
npm run dev
```

Open http://localhost:5173 and create your business account. API docs are at http://localhost:8000/docs.

Local dev uses SQLite by default (`netcare_dev.db`). For PostgreSQL, set
`NETCARE_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/netcare`. For Docker, see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation

[Installation](docs/INSTALLATION.md) · [Architecture](docs/ARCHITECTURE.md) · [Database](docs/DATABASE.md) ·
[API guide](docs/API_GUIDE.md) · [Security](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) ·
[User guide](docs/USER_GUIDE.md) · [Testing](docs/TESTING.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) ·
[Monitoring agent](docs/MONITORING_AGENT.md) · [Data organizer](docs/DATA_ORGANIZER.md) · [Changelog](CHANGELOG.md)

## Implementation checklist

- [x] **Phase 1, foundation:** FastAPI, React, Alembic, auth, orgs/roles, customers, products, inventory, dashboard, tests, Docker Compose
- [ ] Phase 1 follow-ups: emailed invites and password reset (needs an SMTP provider), refresh tokens, customer profile page, product images, barcode generation, verified PostgreSQL CI run
- [x] **Phase 2, business:** suppliers, purchase orders → goods receipt → supplier bill, quotations → invoices, payments with allocation, credit notes, purchase returns, FY numbering
- [ ] Phase 2 follow-ups: sales orders (deliberately skipped; quotation → invoice covers current needs), serial-number capture at sale, tax-inclusive pricing, per-location user restrictions
- [x] **Phase 3, finance and GST:** expenses, accounts, P&L and cash flow, versioned tax rates, tax-inclusive prices, PDF invoices and receipts, Excel/CSV/PDF exports, draft GST summary
- [x] **Phase 4, service and employees:** tickets, technicians, approvals, parts, ticket billing, assets and warranty, maintenance schedules, employees, attendance, leave, tasks, 5 new reports
- [ ] Phase 4 follow-ups: SMS/WhatsApp job updates to customers (needs a provider), customer signature capture on a tablet, technician mobile layout polish
- [ ] Phase 3 follow-ups: emailing invoices (needs an email provider), bank statement reconciliation, credit note PDF, GSTR-format exports (only after accountant validation)
- [x] **Phase 5, documents and analytics:** secure document library attached to records, expiry tracking, analytics with period comparison, all-reports ZIP export
- [ ] Phase 5 follow-ups: antivirus scanning of uploads, image thumbnails, document versioning, scheduled emailing of report packs (needs an email provider)
- [x] **Phase 6, monitoring and CCTV:** monitoring agent (outbound HTTPS, revocable tokens, ping and TCP checks only), outages, uptime and latency, CCTV recorders and channels, device details
- [ ] Phase 6 follow-ups: signed Windows installer/service for the agent, SNMP read-only metrics, alerts on outages (Phase 9), recorder disk-health checks
- [x] **Phase 7, endpoint security:** read-only Microsoft Defender status and detections from opt-in agents, plain-language ratings and next steps, review notes, report
- [x] **Phase 8, data organizer:** local duplicate finder and folder tidier with plan, preview, dry run, approval, journal, rollback, and backup verification
- [ ] **Phase 9:** notifications (in-app, email, optional SMS/WhatsApp)
- [ ] **Phase 10:** module toggles UI, onboarding, security review, E2E tests, pilot release

## Important limitations

- This is not accounting, GST filing, or statutory compliance software. GST rates and HSN codes are stored
  only for your records. A qualified accountant must review the tax configuration before production use.
- The suite has been tested on SQLite. The PostgreSQL code paths (row locks, migrations) are written for
  PostgreSQL but have **not yet run against a real PostgreSQL server**. This matters more now that invoice
  numbering and stock depend on row locks. See [TESTING](docs/TESTING.md).
- The profit and loss summary is an operating summary, not a statutory statement. Invoices issued before
  Phase 3 have no recorded cost, and the report says how many lines are affected.
- GST amounts are calculated for record-keeping. They are not a compliance determination, and there is no
  e-invoicing (IRN) or e-way bill support.
