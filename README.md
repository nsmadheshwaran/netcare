# NetCare Business Suite

**One Platform to Manage Your Business and IT Infrastructure.**

A multi-tenant business management platform for Indian small businesses: computer shops, CCTV installers,
IT service providers, electronics retailers, schools and SMBs.

> **Status: Phase 2 (business management) complete.** Foundation plus suppliers, purchasing, quotations,
> sales invoices, payments and returns work end to end. Expenses, finance reports, PDF invoices, service,
> IT monitoring, endpoint security and the data organizer are **not built yet**. They show as "Planned" in
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
- [ ] **Phase 3, finance and GST:** expenses, cash/bank records, P&L and cash-flow summaries, versioned tax configuration, tax-inclusive prices, PDF invoices and receipts (ReportLab), Excel exports, accountant-ready tax summary
- [ ] **Phase 4:** service tickets, technicians, maintenance schedules, employees, tasks
- [ ] **Phase 5:** documents (secure upload), analytics, report exports
- [ ] **Phase 6:** device inventory, monitoring agent, uptime/latency, CCTV assets
- [ ] **Phase 7:** endpoint security visibility (Defender status/events)
- [ ] **Phase 8:** local data organizer (dry run, approval, rollback)
- [ ] **Phase 9:** notifications (in-app, email, optional SMS/WhatsApp)
- [ ] **Phase 10:** module toggles UI, onboarding, security review, E2E tests, pilot release

## Important limitations

- This is not accounting, GST filing, or statutory compliance software. GST rates and HSN codes are stored
  only for your records. A qualified accountant must review the tax configuration before production use.
- The suite has been tested on SQLite. The PostgreSQL code paths (row locks, migrations) are written for
  PostgreSQL but have **not yet run against a real PostgreSQL server**. This matters more now that invoice
  numbering and stock depend on row locks. See [TESTING](docs/TESTING.md).
- GST amounts are calculated for record-keeping. They are not a compliance determination, and there is no
  e-invoicing (IRN) or e-way bill support.
