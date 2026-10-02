# Changelog

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
