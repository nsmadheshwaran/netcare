# API guide

Interactive docs are at `http://localhost:8000/docs` (Swagger) and `/redoc`. All business endpoints live under
`/api/v1`.

**Versioning:** breaking changes will go to `/api/v2`. Version 1 stays available until clients have migrated.

## Authentication
```bash
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","full_name":"You","password":"at-least-10-chars","organization_name":"My Shop"}'
```
The response is `{"access_token":"...","token_type":"bearer"}`. Look up your organizations with:
```bash
curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```
Send both of these headers on every business call:
```
Authorization: Bearer <token>
X-Organization-ID: <organization_id from /auth/me>
```

## Endpoints
| Method and path | Permission |
|---|---|
| POST /auth/register, /auth/login | public |
| GET /auth/me, POST /auth/change-password, POST /auth/logout-all | signed in |
| GET /organization, PUT /organization | any member, org.manage |
| GET/POST /organization/members, PATCH /organization/members/{id} | users.manage |
| GET/POST /organization/locations | any member, locations.manage |
| GET/POST /customers, GET/PUT /customers/{id}, POST /customers/{id}/archive and /restore | customers.view, customers.edit |
| GET /customers/export.csv, POST /customers/import (multipart: file, mapping, commit) | customers.view, customers.edit |
| GET/POST /product-categories | products.view, products.edit |
| GET/POST /products, GET/PUT /products/{id}, archive and restore | products.view, products.edit |
| GET /inventory/levels, GET /inventory/movements | inventory.view |
| POST /inventory/movements, POST /inventory/transfers | inventory.adjust |
| GET/POST /suppliers, GET/PUT /suppliers/{id}, archive and restore | suppliers.view, suppliers.edit |
| GET/POST /purchase-orders, GET/PUT /purchase-orders/{id} (PUT: drafts only) | purchases.view, purchases.edit |
| POST /purchase-orders/{id}/approve | purchases.approve |
| POST /purchase-orders/{id}/cancel, /close | purchases.edit |
| GET/POST /purchase-orders/{id}/receipts (adds stock) | purchases.view, purchases.edit |
| GET/POST /purchase-invoices, GET /purchase-invoices/{id}, POST .../cancel | purchases.view, purchases.edit |
| GET/POST /purchase-returns (removes stock, reduces the bill) | purchases.view, purchases.edit |
| GET/POST /quotations, GET/PUT /quotations/{id}, POST .../status, POST .../convert?location_id= | sales.view, sales.edit |
| GET/POST /invoices, GET/PUT /invoices/{id} (PUT: drafts only) | sales.view, sales.edit |
| POST /invoices/{id}/issue, /cancel, /credit-notes | sales.edit |
| GET /credit-notes, GET /customers/{id}/account | sales.view |
| GET/POST /payments, GET /payments/{id}, POST .../allocate, POST .../void | payments.view, payments.edit |
| GET/POST /accounts, PATCH /accounts/{id} | finance.view, finance.manage |
| GET/POST /finance-categories | expenses.view, finance.manage |
| GET/POST /finance-entries, POST .../void (kind: expense needs expenses.edit; income and transfer need finance.manage) | expenses.view |
| GET /tax-rates, POST /tax-rates, POST /tax-rates/{id}/retire | products.view, org.manage |
| GET /reports, GET /reports/{key}?format=json,csv,xlsx,pdf | reports.view |
| GET /invoices/{id}/pdf?layout=a4,thermal, GET /quotations/{id}/pdf | sales.view |
| GET /payments/{id}/pdf | payments.view |
| POST, GET, DELETE /organization/logo | org.manage (GET: any member) |
| GET/POST /service-tickets, GET/PATCH /service-tickets/{id} | service.view, service.edit (PATCH: service.work on own tickets) |
| POST /service-tickets/{id}/status, /notes, /approval, /parts, /parts/{pid}/return | service.work on own tickets, or service.edit |
| POST /service-tickets/{id}/assign | service.edit |
| POST /service-tickets/{id}/invoice | service.edit + sales.edit |
| POST /service-tickets/{id}/assets (register installed equipment) | assets.edit |
| GET /service-tickets/{id}/pdf | service.view |
| GET/POST /assets, GET/PUT /assets/{id}, GET /assets/{id}/history, POST /assets/{id}/replace | assets.view, assets.edit |
| GET/POST /maintenance-schedules, PUT /maintenance-schedules/{id}, POST .../ticket | service.view, service.edit |
| GET /my-work | tasks.view |
| GET/POST /employees, PUT /employees/{id}, GET /employees/me | tasks.view, employees.manage |
| GET/PUT /attendance | employees.view, attendance.manage |
| GET/POST /leave-requests, POST .../decide, POST .../cancel | tasks.view (own), attendance.manage |
| GET/POST /tasks, PUT /tasks/{id}, POST /tasks/{id}/status | tasks.view, tasks.edit (assignees may move their own) |
| GET /documents/meta (categories, limits, storage used) | documents.view |
| GET /documents?q=&entity_type=&entity_id=&category=&expiring_days=&deleted= | documents.view (+ record view permission; `deleted` needs documents.sensitive) |
| POST /documents (multipart: file, entity_type, entity_id, title, category, tags, notes, expires_on, is_sensitive) | documents.edit (+ record view permission) |
| GET/PATCH /documents/{id}, GET /documents/{id}/download?inline= | documents.view, documents.edit |
| POST /documents/{id}/delete {reason}, POST .../restore, POST .../purge | documents.edit, documents.sensitive, documents.purge |
| GET /analytics/overview?date_from=&date_to= | analytics.view |
| GET /reports/pack?date_from=&date_to=&format=xlsx,pdf,csv&keys= | reports.view |
| GET /dashboard/summary?period=day,week,month,quarter,year&location_id= | dashboard.view |
| GET /audit-logs | audit.view |
| GET /health, GET /ready | public |

## Conventions
- **Lists:** `?page=1&size=25&q=...&sort=name&order=asc` returns `{items, total, page, size}`.
- **Errors:** `{"detail": "message"}`, or a list of field errors for 422.
- **Status codes:**
  - 401: not signed in
  - 403: role lacks the permission
  - 404: not found, *or the record belongs to another organization*
  - 409: conflict, duplicate, or insufficient stock
  - 422: validation error
  - 429: too many login attempts
- **Money and quantities** are decimal strings, such as `"1999.00"`. Send them as strings to avoid
  floating-point rounding.
- **Idempotency:** stock movements, transfers, invoices, goods receipts, credit notes, purchase returns and
  payments accept `idempotency_key`. Sending the same key again returns the original result instead of
  creating a duplicate. The UI generates one key per form, so a double-click cannot record something twice.

## Example: sell, then get paid
```bash
curl -X POST localhost:8000/api/v1/invoices -H "Authorization: Bearer $T" -H "X-Organization-ID: 1" \
  -H "Content-Type: application/json" \
  -d '{"customer_id":3,"location_id":1,"invoice_date":"2026-10-02","idempotency_key":"counter-0042",
       "lines":[{"product_id":7,"quantity":"2"},{"description":"Labour","unit_price":"500","quantity":"1","tax_rate":"18"}]}'
```
That creates a draft invoice: no number, no stock change. For product lines, price and GST rate default from
the product. Then issue it:
```bash
curl -X POST localhost:8000/api/v1/invoices/12/issue -H "Authorization: Bearer $T" -H "X-Organization-ID: 1"
```
Issuing assigns the number, deducts stock and creates the receivable. Then record the payment:
```bash
curl -X POST localhost:8000/api/v1/payments -H "Authorization: Bearer $T" -H "X-Organization-ID: 1" \
  -H "Content-Type: application/json" \
  -d '{"customer_id":3,"payment_date":"2026-10-02","amount":"4000","method":"upi","reference":"UPI-1234",
       "allocations":[{"invoice_id":12,"amount":"4000"}]}'
```
Document rules:
- Issued documents cannot be edited. Cancel them (only if nothing has been paid or credited), or issue a
  credit note.
- `display_status` adds `overdue` for unpaid invoices past their due date.
- `balance_due = total - amount_paid - credited_amount`.

## Reports
`GET /reports` lists the available reports and the parameters each one takes:
- `period` reports take `date_from` and `date_to` (default: this month; at most three years).
- `daily-closing` takes `day`.
- The ageing reports take `as_of`.
- `stock-valuation` takes an optional `location_id`.

Add `format=pdf`, `xlsx` or `csv` to download. Every report run is written to the audit log.

`GET /reports/pack` returns a ZIP of every report for one period (or only `keys=a,b`). Period reports cover the
period; as-of reports use `date_to`; the daily closing is left out.

## Documents
```bash
curl -H "Authorization: Bearer $T" -H "X-Organization-ID: 1" -F file=@warranty.pdf \
     -F entity_type=customer -F entity_id=12 -F category=warranty -F expires_on=2027-03-31 \
     http://localhost:8000/api/v1/documents
```
Errors: 413 too large, 422 type not accepted or bad target, 409 same file already attached, 507 quota full,
410 file missing on disk (restore from backup).

## Example: receive stock
```bash
curl -X POST localhost:8000/api/v1/inventory/movements \
  -H "Authorization: Bearer $T" -H "X-Organization-ID: 1" -H "Content-Type: application/json" \
  -d '{"product_id":1,"location_id":1,"movement_type":"stock_in","quantity":"10","reference":"Bill 4411","idempotency_key":"bill-4411"}'
```
