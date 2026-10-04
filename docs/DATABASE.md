# Database

Production uses PostgreSQL. Local development and the automated tests use SQLite. Alembic is the **only**
way the schema changes.

## Tables (migration `0001`)
| Table | Purpose | Key constraints |
|---|---|---|
| organizations | Tenant (business) | |
| users | Login identities | unique email |
| memberships | Links a user to an organization with a role | unique (organization, user) |
| locations | Shops and warehouses | unique (organization, name) |
| customers | CRM records, soft-deleted via `archived_at` | index (organization, name) |
| product_categories | | unique (organization, name) |
| products | Goods and services | unique (organization, sku), prices ≥ 0 |
| stock_levels | Quantity on hand per product and location | unique (product, location) |
| stock_movements | Append-only stock ledger | unique (organization, idempotency_key) |
| audit_logs | Who did what, and when | |

### Migration `0002` (Phase 2)
| Table | Purpose | Key constraints |
|---|---|---|
| suppliers | Vendors | |
| document_sequences | Next number per organization, document type and financial year | unique (org, type, FY); row-locked |
| purchase_orders, purchase_order_lines | Orders, with `received_quantity` per line | unique (org, number) |
| goods_receipts, goods_receipt_lines | Each delivery; links to its stock movement | unique (org, number), (org, idempotency_key) |
| purchase_invoices, purchase_invoice_lines | Supplier bills (payables) | unique (org, supplier, supplier bill no.) |
| purchase_returns, purchase_return_lines | Goods sent back to suppliers | |
| quotations, quotation_lines | Estimates | |
| sales_invoices, sales_invoice_lines | Drafts have no number; `returned_quantity` per line | unique (org, number), (org, idempotency_key) |
| credit_notes, credit_note_lines | Sales returns and credits | |
| payments | Money in (`customer_id`) or out (`supplier_id`), never both | amount > 0; exactly one party |
| payment_allocations | Links a payment to one invoice or bill | amount > 0; exactly one target |

Document tables share the same money columns: `subtotal`, `discount_total`, `taxable_total`,
`cgst_total`/`sgst_total`/`igst_total`, `round_off`, `total`, `is_interstate` and `place_of_supply`. Lines
store `taxable_value`, the tax split and `line_total`. The server computes and stores all of these, so a
document never changes if a product price or tax rate changes later.

### Migration `0003` (Phase 3)
| Table / column | Purpose |
|---|---|
| money_accounts | Cash, bank and other accounts; opening balance; one default per kind |
| finance_categories | Expense and income categories (common ones are created on first use) |
| finance_entries | Expenses, other income and transfers; `tax_amount` is GST the business can claim; voided, never deleted |
| tax_rates | Versioned GST rate master: `effective_from`/`effective_to`, never updated in place |
| products.avg_cost | Moving-average cost; existing products were seeded from `purchase_price` |
| sales_invoice_lines.unit_cost | Cost captured when the invoice was issued; empty for invoices issued before 0003 |
| payments.account_id | Which account the money went into or came out of |
| organizations.logo, logo_mime, prices_include_tax_default | Branding and pricing default |
| quotations / sales_invoices.prices_include_tax | Whether the line prices included GST |

### Migration `0004` (Phase 4)
| Table / column | Purpose |
|---|---|
| employees | Staff; optional `user_id` link to a login (unique per business) |
| attendance | One row per employee per day (unique); corrections are audited |
| leave_requests | Pending/approved/rejected/cancelled; approval fills attendance |
| tasks | Assigned work with priority, due date, optional customer/ticket link |
| assets | Customer equipment; serial unique per business; `installed_by_ticket_id` is a plain id (no FK) to avoid a cycle with tickets |
| service_tickets | The job: type, status, technician, estimate/approval (with the customer's drawn signature and signer name), labour, warranty flag, links to schedule and invoice |
| ticket_parts | Parts used, with the stock movement out and (if returned) back |
| ticket_events | Append-only timeline |
| maintenance_schedules | Interval in months, next due, last done |
| sales_invoice_lines.ticket_part_id | Marks lines whose stock already left on a ticket |

### Migration `0005` (Phase 5)
| Table / column | Purpose |
|---|---|
| stored_documents | Metadata of an uploaded file: attached record (`entity_type`, `entity_id`, checked against the business in code, not by FK), title, category, tags, expiry, sensitive flag, detected type, size, SHA-256, random `storage_key`; soft delete (`deleted_*`) and `purged_at` tombstone |

### Migration `0006` (Phase 6)
| Table / column | Purpose |
|---|---|
| monitor_agents | Agent per site: SHA-256 of its token (unique), display prefix, active/revoked, last seen/IP/version/host |
| monitor_checks | One target per check (ICMP host or TCP host+port), interval, timeout, failure threshold, latency warning, current state (`status`, `consecutive_failures`, `failing_since`, `status_since`, last result) |
| check_results | Raw results, unique per (check, observed_at); pruned after 30 days |
| monitor_incidents | Outages: started at the first failure, ended at the next success |
| assets.mac_address, firmware, recorder_id, channel, resolution, hdd_capacity_gb, retention_days | Device and CCTV details; `(recorder_id, channel)` unique |

### Migration `0007` (Phase 7)
| Table / column | Purpose |
|---|---|
| monitor_agents.collect_endpoint | Opt-in: this agent also reports its PC's Defender status |
| endpoints | One PC per (agent, hostname): OS, last report, Defender switches, mode, versions, definition and scan times, optional link to a computer asset |
| endpoint_threats | Defender detections, unique per (endpoint, DetectionID): name, severity, category, status, file paths, review (acknowledged by/at/note) |

### Migration `0008` (Phase 9)
| Table | Purpose |
|---|---|
| notifications | Per user and business: kind, severity, title, body, app link, read time; unique `dedupe_key` per user and business |
| notification_prefs | Per user, business and kind: in app on/off, email on/off |
| email_outbox | Queued emails: status pending/sent/failed, attempts, next attempt, last error |

### Migrations `0009` to `0011` (1.1.0)
| Table / column | Purpose |
|---|---|
| refresh_tokens | Hashed refresh tokens, family per sign-in, rotation (`used_at`), revocation, expiry, IP and browser |
| user_tokens | Hashed single-use invite/reset links with expiry |
| email_outbox.organization_id nullable; email_outbox.channel | Account emails without a business; email / sms / whatsapp |
| monitor_checks.snmp_community, snmp_oids, last_values; check_results.values | SNMP checks and readings |
| users.phone; notification_prefs.sms | Text-message alerts |

The file bytes are not in the database; they are in `NETCARE_STORAGE_DIR`. Back up both.

Every business table has an `organization_id` column with `ON DELETE CASCADE` to its organization.

## Migrations
```bash
cd backend
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic revision --autogenerate -m "describe change" --rev-id 0002
python -m alembic check
```
These commands apply all migrations, roll back one, create a new migration, and confirm that the models match
the migrations (`check` fails if they differ).

Review every autogenerated migration before committing it. Never edit a migration that has already been
applied; add a new one instead.

## SQLite migration safety
Alembic batch mode rebuilds SQLite tables by dropping and recreating them. With foreign keys switched on,
dropping a parent table cascades deletes into its child tables. `alembic/env.py` switches foreign keys off
during migrations, and `tests/test_migrations.py` checks that data survives. Keep this in mind if you ever
run migrations without going through `env.py`.

## Corrections policy
Stock movements are never edited or deleted. To fix a mistake, record a new `adjustment` movement.
Issued invoices are cancelled or credited, never edited. Payments are voided (kept, with a reason), never
deleted. Customers and products are archived (soft-deleted), never hard-deleted, so their history stays intact.
