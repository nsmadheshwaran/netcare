# Testing

## Run
```bash
cd backend
python -m pytest -q
```
```bash
cd frontend
npm test
npx tsc -p .
npm run build
```
`npx tsc -p .` is the TypeScript type check.

## Results at milestone 1 (2026-10-02, Windows 11, Python 3.14.7, Node 24.18.1)
| Suite | Result |
|---|---|
| Backend pytest | **23 passed** |
| Alembic upgrade, downgrade base, upgrade again, `alembic check` | passed, models match migrations |
| Frontend vitest | **3 passed** |
| TypeScript type check | no errors |
| Vite production build | succeeded |
| Manual end-to-end in browser | Registered through the UI. Created 2 customers, 1 category, 1 product and a stock-in through the running API. Confirmed that an over-sell was rejected (409) and that the dashboard showed the correct valuation (12 × ₹1,450.50 = ₹17,406.00) |

## Results at Phase 2 (2026-10-02, same machine)
| Suite | Result |
|---|---|
| Backend pytest | **44 passed**: 23 foundation, 13 trade workflows, 7 billing maths, 1 migration data-preservation |
| `alembic check` after `0002` | models match migrations; upgrade, downgrade, upgrade verified on a database with existing rows |
| Frontend vitest, `tsc`, Vite build | 3 passed, no type errors, build succeeded |
| Mutation check | Two deliberate bugs were inserted to prove the tests catch them: committing stock per line during issue, and removing the double-issue guard. Both made tests fail and were then reverted |
| Manual run in browser | A full purchase-to-payment flow on the running app (details below). All figures were checked by hand; all list pages and the dashboard rendered them correctly |

The manual run covered: PO → approve → partial receipt → supplier bill → part payment; quotation with line
and invoice-level discounts → accepted → converted → issued (CGST + SGST); UPI receipt; credit note without
restock; an inter-state invoice (IGST only) shown as overdue; and rejections for over-crediting and for a due
date before the invoice date. The forms were **not clicked through**, because the browser pane was hidden.
Each form was type-checked, and the same API calls they make were exercised.

### Phase 2 test coverage
- **Purchasing:** draft, approve, partial receipt, over-receipt blocked, idempotent receipt, receipt only after
  approval, locked after approval, bill due date from supplier terms, duplicate supplier bill blocked,
  supplier payment, purchase return reducing stock and the bill, services rejected on POs, cancel and close
  rules.
- **Sales:** quotation discount maths, quotes and drafts never move stock, convert once only, issue numbering,
  no double issue, issued invoices locked, overpayment kept as an advance, overpaying a paid invoice blocked,
  voiding reopens the invoice.
- **Atomicity:** an issue that fails on the second line leaves the first line's stock, the invoice status and
  the number sequence untouched.
- **Tax:** intra-state vs inter-state, unknown state treated as intra-state, explicit place-of-supply
  override, odd-paisa CGST/SGST split.
- **Credit notes:** three partial credits sum to the exact invoice total; restock vs no restock; over-credit
  blocked; cancelling a credited invoice blocked.
- **Numbering:** per financial year (31 March vs 1 April), custom prefix, cancelled numbers not reused,
  numbering per organization.
- **Payments:** wrong customer, both parties, allocation over amount, zero amount, invalid method, paying a
  draft, advance then later allocation, idempotent receipt.
- **Isolation and roles:** cross-tenant reads, cancels, approvals, billing with another tenant's product or
  customer, paying another tenant's invoice; inventory managers cannot approve POs; accountants are
  read-only on sales; technicians see no sales or payments.

## Results at Phase 4 (2026-10-03)
| Suite | Result |
|---|---|
| Backend pytest | **70 passed** (10 new service/people tests); suite time cut from about 66 s to about 20 s by migrating once per session |
| `alembic check`, data-preservation migration test | passed through `0004`; upgrade, downgrade, upgrade verified on the dev database with data |
| pyflakes, `tsc`, vitest, Vite build | clean, clean, 3 passed, built |
| Mutation check | Removing the "don't deduct ticket parts again" rule, and removing the technician ownership check: both made tests fail and were reverted |
| Live run | Installation job on the running app: 4 cameras used from stock, equipment registered with warranty, invoice of Rs 12,267.28 (10,396 + 18%); stock unchanged on issue (no double deduction); completion report PDF read and improved (it now lists installed equipment and omits empty sections); IT Assets, My work and Employees pages render the data |

Phase 4 test coverage: approval gating; technician ownership and office-only actions; parts out and back;
completion requires work recorded; closing requires an invoice unless warranty; invoice once; no double
deduction; part cost reaches the P&L; invoice cancel unlinks the ticket without restocking; installation
registers assets with warranty and a schedule; duplicate serial; invalid IP (422, not 500); maintenance roll
forward; asset/customer mismatch; asset replacement; warranty filters and reports; employee/login linking
rules; attendance upsert, future date, time order; leave overlap, self-approval, approval fills attendance;
task ownership; month-end date arithmetic; cross-tenant isolation for tickets, assets, employees, tasks and parts.

## Results at Phase 3 (2026-10-02)
| Suite | Result |
|---|---|
| Backend pytest | **60 passed**: 45 earlier (one new inclusive-price maths test), plus 15 finance/report/PDF tests |
| `alembic check` and migration data-preservation test | passed through `0003` |
| pyflakes | clean (app and tests) |
| Frontend vitest, `tsc`, Vite build | 3 passed, no errors, built |
| Mutation check | Two deliberate bugs were inserted: returning stock at the current average instead of the original cost, and starting new products at zero cost. Both made tests fail and were reverted |
| Visual check | A generated A4 invoice, a thermal receipt and a P&L PDF were opened and read. Layout bugs found this way were fixed: wrapped headers, missing address commas, unexplained discounts on the thermal receipt, left-aligned report amounts |
| Live run | Expenses, account balances, P&L, cash flow, and PDF/Excel downloads through the running app; the Finance, Expenses and Reports pages render the data |

### Phase 3 test coverage
- **Costing:** moving average across receipts; the sale cost is frozen at issue; restocked returns go back in at
  the original cost (checked against the resulting average); transfers don't move the average; new products
  start at their purchase price.
- **Finance:** default category creation, default account creation per method, cash flow per account
  (opening, in, out, closing, totals), claimable GST excluded from the P&L, voiding removes an entry from
  reports, daily closing by method, validation (category kind, tax > amount, self-transfer, negative
  amounts), idempotency.
- **Tax:** the rate master is optional until configured; duplicate open rate refused; retirement is enforced
  by date, including the last valid day; history is kept; only owners manage rates; inclusive vs exclusive
  invoices.
- **Reports:** all 10 reports in all 4 formats (Excel files re-opened, PDFs checked for a valid header),
  organization name with `&` and `<`, invalid range, unknown report, ageing buckets, formula neutralising in
  CSV, role access, tenant isolation.
- **Documents:** A4 and thermal invoices, quotation, payment receipt; inline vs download; logo upload rejects
  SVG disguised as PNG, GIF and oversize files.
- **Words:** lakh/crore grouping, paise, zero.

## What the backend tests cover
- **Auth:** registration, login, `/me`, Argon2 hash stored, duplicate email, weak password, rate limit (429),
  invalid tokens, token revocation on password change.
- **Tenant isolation:** reading, updating or archiving another tenant's customer; reading their product; using
  their category or location; moving their stock; switching `X-Organization-ID` to a foreign organization;
  export leakage.
- **Roles:** viewer, technician and inventory-manager boundaries; managers cannot touch owners; last owner is
  protected; deactivated members lose access.
- **Customers:** CRUD, GSTIN and PIN validation, duplicate detection, search, sort, pagination,
  archive/restore, CSV import preview/commit with mapping and in-file duplicates, CSV formula neutralising.
- **Products:** unique SKU (case-insensitive), negative price and >2-decimal rejection.
- **Inventory:** sign handling per movement type, no negative stock, rejected movements leave no trace,
  idempotency, atomic transfers, services carry no stock.
- **Dashboard:** empty state, real valuation, low-stock count, every period, invalid period.
- **Timestamps:** returned as UTC-aware values.

Every test uses a fresh temporary SQLite database **built by running the real Alembic migrations**, so the
migrations are exercised on every run. No real customer data is used.

## Gaps
- **Not yet run against PostgreSQL.** Phase 2 relies on row locks for invoice numbering and stock, so this is now
  the most important gap. SQLite serialises writes, which hides concurrency bugs; true concurrent-issue tests
  need PostgreSQL. Add a CI job with a `postgres:16` service and
  `NETCARE_DATABASE_URL=postgresql+psycopg://...`.
- No browser E2E suite yet (Playwright is planned). Frontend tests cover only the API client.
