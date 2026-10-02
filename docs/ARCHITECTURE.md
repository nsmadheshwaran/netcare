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

## Frontend layout (`frontend/src`)
- `api.ts`: fetch wrapper and error formatting
- `auth.tsx`: session and permissions context
- `components/`: layout and UI kit
- `pages/`: one file per module

Permission checks in the UI only hide controls. The API enforces every permission.
