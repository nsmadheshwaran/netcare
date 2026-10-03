# Architecture

NetCare is a **modular monolith**: one FastAPI service, one PostgreSQL database and one React SPA. Each module
has its own router and service, so modules can be split into separate services later if needed.

```
Browser (React SPA) --HTTPS--> reverse proxy (nginx) --> FastAPI (/api/v1) --> PostgreSQL
                                                         (future) APScheduler jobs, report generation
Customer site: (future) Windows agent --outbound HTTPS, per-agent revocable token--> FastAPI
```

## Backend layout (`backend/app`)
| File | Role |
|---|---|
| `config.py` | Environment-based settings and production safety checks |
| `db.py` | Engine and session factory |
| `models.py` | SQLAlchemy models. Money is `Numeric(14,2)`, quantities are `Numeric(14,3)`, timestamps are UTC-aware |
| `schemas.py` | Pydantic request/response models with validation (GSTIN, PIN, HSN, decimals) |
| `security.py` | Argon2 password hashing, JWT, login rate limiter |
| `permissions.py` | Maps each role to its permissions |
| `deps.py` | `get_current_user`, `get_org_context` (tenant resolution), `require(perm)`, audit helper |
| `services/inventory.py` | **The only code that changes stock** |
| `routers/*` | Thin HTTP layer: auth, organization, customers, products, inventory, dashboard, audit, health |

## Request flow and tenancy
1. `Authorization: Bearer <JWT>` identifies the user. The token carries `token_version`, so a password change
   or "sign out everywhere" revokes older tokens.
2. `X-Organization-ID` selects the business. `get_org_context` requires an **active membership** and returns
   404 otherwise, so a caller cannot tell whether another business exists.
3. `require("customers.edit")` checks the role's permission.
4. Every query filters on `ctx.org_id`, and every object loaded by ID is checked against it.

## Inventory consistency
- `stock_levels` holds the quantity on hand per product and location. `stock_movements` is an append-only
  ledger that records `balance_after` for each movement.
- `apply_movement` locks the level row (`SELECT ... FOR UPDATE` on PostgreSQL), validates the change, and
  writes the level and the ledger entry in the same transaction. On any error the whole request rolls back,
  so a failed transfer leaves both locations unchanged.
- `idempotency_key` is unique per organization. A retried request returns the original movement.
- Sales, purchases and service parts will call the same service. Their movement types (`sale`,
  `purchase_receipt`, `service_part`) are already defined.

## Billing and trade (Phase 2)
- `services/billing.py` does the money maths and the numbering. All values are `Decimal`, rounded half-up to
  the paisa at each stored amount:
  - Per line: gross = qty × price.
  - Then the line discount %.
  - Then a share of the document discount, allocated by net value (the last line takes the remainder).
  - What is left is the taxable value.
  - Tax = taxable × rate, split CGST/SGST (SGST takes the odd paisa) or IGST.
- `next_number` locks the `document_sequences` row (`SELECT ... FOR UPDATE`). The number is taken in the same
  transaction as the document, so a failed issue rolls the number back and errors leave no gaps.
- `services/trade.py` holds organization-scoped lookups, line building (defaults from the product), status
  recomputation, and `balance = total - paid - credited`.
- **What moves stock:**

  | Event | Stock movement |
  |---|---|
  | Goods receipt | `purchase_receipt` (+) |
  | Invoice issue | `sale` (−) |
  | Invoice cancel | `sale_cancel` (+) |
  | Credit note with restock | `customer_return` (+) |
  | Purchase return | `supplier_return` (−) |

  Quotations, drafts and bills never move stock.
- **What changes balances:** issuing an invoice creates a receivable; payment allocations and credit notes
  reduce it. Supplier bills create payables; allocations and purchase returns reduce them.

## Finance and reports (Phase 3)
- **Costing.** `services/inventory.apply_movement` locks the product row. A costed inflow (receipt, stock-in
  with a cost, return, cancellation) updates `avg_cost` as:

  `(on_hand × avg + qty × cost) / (on_hand + qty)`

  Outflows and transfers are valued at the current average. Issuing an invoice copies the sale cost onto the
  line, so profit for a past period never changes when later purchases change the average.
- **Reports.** `services/reports.py` builds an `export.Report` (title, columns, rows, totals, sections, notes,
  draft flag) from persisted records only. `services/export.py` renders any report as CSV (with a UTF-8 BOM,
  formula-safe), Excel or PDF. Adding a report means writing one function and adding it to `CATALOG`.
- **PDFs.** `services/pdf_docs.py` builds the invoice, quotation, thermal and receipt layouts with ReportLab.
  All user text is XML-escaped before it reaches ReportLab markup.
- **Dates.** `services/timeutil.today()` returns the business-local date (UTC+05:30 by default, set by
  `NETCARE_UTC_OFFSET_MINUTES`). Timestamps are stored in UTC; document dates are the business's own dates.

## Service (Phase 4)
- **Workflow.** `routers/service.py` holds the ticket state machine (`TRANSITIONS`). Guards:
  - Work can't start while an estimate awaits approval.
  - Completion requires recorded work.
  - Cancellation requires all parts returned and no invoice.
  - Closing a chargeable job requires an invoice.
- **Permissions.** `_can_work` lets `service.edit` touch any ticket, and `service.work` only tickets assigned
  to the caller's employee record.
- **Stock.**
  - A part used is a `service_part` movement (−).
  - A part returned is `service_part_return` (+) at the cost it left at.
  - Ticket invoices mark their part lines with `ticket_part_id`, so issuing skips the stock deduction and copies
    the part's cost for the profit and loss summary.
- **Maintenance.** Completing a ticket linked to a schedule sets `last_done` and moves `next_due` forward by
  the interval (month-end safe).

## Documents, analytics and report pack (Phase 5)
- **Storage.** `services/storage.py` writes uploads to `NETCARE_STORAGE_DIR/<org_id>/<random hex>` (write to
  `.part`, fsync, rename). The database row (`stored_documents`) holds the metadata, size and SHA-256. Paths
  are generated, never taken from the user, and are resolved and checked to stay inside the storage root.
- **Type detection.** `storage.detect` reads the bytes: PDF, PNG, JPEG, WebP, DOCX/XLSX (a ZIP with
  `[Content_Types].xml`; macros, too many entries or a high compression ratio are refused), or UTF-8 text/CSV.
  The stored content type and extension come from detection, not the browser.
- **Access.** `routers/library.py`: `documents.view/edit` plus view permission on the attached record
  (`ENTITIES` maps each entity type to its permission), so listing and fetching by id respect module access.
  `documents.sensitive` gates sensitive files and the deleted list; `documents.purge` (owner) removes files.
  Technicians attach to service tickets through the same `_can_work` check as ticket edits.
- **Lifecycle.** Delete is soft (reason kept, file kept, restorable). Purge removes the file *after* the commit
  and keeps the row as a tombstone. A failed insert removes the file it just wrote. The same file on the same
  record is a 409.
- **Analytics.** `services/analytics.py` computes KPIs for the period and the previous period of equal length,
  a daily (up to 62 days) or monthly trend, and top products/customers/categories/payment methods. Gross profit
  uses the cost captured on each invoice line; uncosted product lines are counted and reported in `notes`.
- **Report pack.** `GET /reports/pack` renders every allowed report into one ZIP. `REPORT_PERMS` adds extra
  permissions to individual reports (the document expiry report needs `documents.view`).

## Monitoring and CCTV (Phase 6)
- **Pieces.** `agent/netcare_agent.py` (runs at the site) calls `GET /api/v1/agent/config` and
  `POST /api/v1/agent/results`. `routers/monitoring.py` holds that agent API and the admin API.
  `services/monitoring.py` holds tokens, target validation, the state machine and the statistics.
- **Agent auth.** `current_agent` hashes the bearer token and looks it up; revoked tokens get 401. The agent
  only sees its own enabled checks; results for other check ids are rejected per item (`rejected_check_ids`).
- **State machine.** Results are applied in `observed_at` order; late results are stored but do not change
  state. `failure_threshold` failures in a row make a check down and open a `monitor_incidents` row from the
  first failure (`failing_since`); the next success closes it. A latency above `latency_warn_ms` is degraded.
  Duplicates (same check and timestamp) are skipped, so agent retries are safe.
- **Unknown.** `effective_status` is computed at read time: agent silent for 5 minutes, check disabled, or
  result older than three intervals means unknown. The stored state is kept, and no incident is invented.
- **Retention.** Raw results are pruned after 30 days on ingest; incidents are kept. Uptime is the share of
  successful results in the window (None when there are none), downtime comes from incidents.
- **CCTV.** Cameras link to a DVR/NVR (`assets.recorder_id`, `channel`, unique per recorder) at the same
  customer. Equipment shows the worst effective status of its enabled checks (`monitor_status`).

## Frontend layout (`frontend/src`)
- `api.ts`: fetch wrapper and error formatting
- `auth.tsx`: session and permissions context
- `components/`: layout and UI kit
- `pages/`: one file per module

Permission checks in the UI only hide controls. The API enforces every permission.
