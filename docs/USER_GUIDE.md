# User guide

## Getting started
1. Open NetCare and choose **Create an account**. Enter your business name, your name, your email and a
   password (at least 10 characters). You become the **Owner**, and a location called **Main** is created.
2. Go to **Settings** to add your GSTIN, state code, address and any extra shops or warehouses.
3. Go to **Users and Roles** to add staff. Give each person a temporary password privately and ask them to
   change it under **Settings → Change your password**.

## Roles
| Role | Can do |
|---|---|
| Owner | Everything, including business settings and managing owners |
| Manager | Everything except business settings |
| Accountant | View customers, products, stock, dashboard and audit log |
| Salesperson | View and edit customers; view products and stock |
| Inventory manager | Manage products, stock movements and locations |
| Technician, Viewer | View only |
| Receptionist | View and edit customers; view products |

Documents: every role can view documents (on records it can see), and every role except Viewer can upload.
Sensitive documents and the deleted list: owners and managers. Purge: owners. Analytics: owners, managers and
accountants.

## Customers
- **Add customer:** choose Individual or Business. GSTIN and the 6-digit PIN code are checked for format.
- If the phone, email or GSTIN matches an existing customer, NetCare warns you. Click **Save anyway** if the
  new record really is a different customer.
- **Archive** hides a customer without deleting their history. Tick **Show archived** to find and restore them.
- **Import CSV:** choose a file and click **Preview**. Match each column to a field, check the duplicate and
  error counts, then click **Import**. Nothing is saved until you click **Import**.
- **Export** downloads a CSV of the current list.

## Products
- Each product needs a unique **SKU**. Tick **This is a service** for labour or installation charges; services
  have no stock.
- **Minimum stock** controls the low-stock warning on the dashboard.
- GST rate and HSN/SAC are stored for your records only. **Have your accountant confirm them.** NetCare does
  not file GST.

## Inventory
- **Record movement:**
  - **Stock in:** goods arrived
  - **Stock out:** goods left for a reason other than a sale (sales will be recorded automatically later)
  - **Adjustment:** correct a count; use a negative number to reduce
  - **Damaged:** write off goods
  - **Customer return**, **Return to supplier**
- **Transfer** moves stock between locations in one step.
- Stock can never go below zero. If you try, you see how much is actually available.
- **Movement history** shows every change, who made it and the resulting balance. Entries cannot be edited;
  record an adjustment to correct a mistake.

## Before you invoice
In **Settings**, set your **GST state code** (for example 33 for Tamil Nadu), your default terms and your
payment instructions. You can also set number prefixes; do this before your first invoice. Then give each
customer and supplier their state code. NetCare uses CGST + SGST when the state codes match and IGST when they
differ. If a code is missing, the sale is treated as intra-state and the invoice shows a warning.

## Buying stock (Purchases)
1. **New purchase order.** Choose the supplier, the delivery location and the products. Prices default to
   each product's purchase price.
2. An owner or manager clicks **Approve**.
3. When goods arrive, click **Receive goods** and enter what actually came. Part deliveries are fine, and
   stock goes up immediately. If the rest will never come, click **Close**.
4. **Record supplier bill.** Enter the supplier's bill number and the amounts exactly as printed. NetCare
   refuses the same bill number twice for the same supplier.
5. **Pay** the bill in full or in part. **You owe suppliers** on the dashboard tracks what is left.
6. Faulty goods: use **Return to supplier**. Stock goes down, and if you choose the bill, the amount you owe
   goes down too.

## Selling (Quotations and Sales)
- **Quotation:** prices for a customer. It changes nothing until it is converted. Mark it sent, accepted or
  rejected. Accepted quotations can be **converted to a draft invoice**.
- **Invoice:** saved as a **draft** first so you can check it. **Issue** gives it its number
  (`INV/2026-27/00001`) and deducts stock. If any item is short at that location, issuing is refused and
  nothing changes.
- Add labour, installation or delivery charges as **service** products, or as free-text lines with a price.
- **Discounts:** a percentage per line, plus an amount off the whole invoice. The amount is spread across
  lines so tax is calculated on the discounted value.
- **Record payment** on an invoice. If the customer pays more than is due, the extra is kept as an
  **advance**, and you can apply it to a later invoice from **Payments**.
- **Return / credit note:** pick the items and quantities. Tick **Put back into stock** unless the goods are
  damaged. The credit reduces what the customer owes.
- **Cancel** is only for mistakes with no payments or credits. Stock is restored and the number is not
  reused; the cancelled invoice explains the gap.

## Payments
Invoices and bills are not money. Only payments recorded here count as cash received or paid. If a cheque
bounces or a UPI payment is reversed, **Void** the payment: the invoice becomes due again, and the record
stays, with your reason.

## Printing
- On an invoice, **Print A4** opens a PDF to print or save; **Thermal** opens an 80 mm receipt for roll
  printers. Draft invoices print as **DRAFT** and cancelled ones as **CANCELLED**.
- Quotations have a **Print** button. On **Payments**, the printer icon produces a receipt (money in) or a
  voucher (money out).
- Add your logo, bank/UPI payment instructions and terms in **Settings**; they appear on invoices.

## Expenses, income and accounts
- **Finance** shows each cash and bank account's balance. A "Cash in hand" and a "Bank" account are created
  automatically. Add your real accounts with their opening balances, and mark the ones to use by default.
- **Record expense** for rent, electricity, salaries and so on. Fill in "GST you can claim" only if your
  accountant confirms you can take input credit on that bill; that amount is left out of expenses in the
  profit and loss.
- **Transfer** records cash deposited to the bank, or withdrawn.
- Mistakes are **voided** (kept with a reason), never deleted.

## Tax rates and GST-inclusive prices
- Under **Settings, GST rates**, list the rates your accountant confirmed. Once at least one is listed, a
  document can only use rates in effect on its date. When a rate changes, **Retire** the old one with its
  last day and add the new one. Older invoices stay valid.
- If your shelf prices include GST, tick **Prices I enter include GST** in Settings, or choose it per invoice.
  NetCare then works out the taxable value from the price.

## Reports
Open **Reports**, pick a report and a period, and download it as PDF, Excel or CSV for your accountant.
- **Profit and loss** is an operating summary: net sales, minus the cost of goods sold, minus expenses.
- **Daily closing** helps you count the cash drawer at the end of the day.
- **Customer dues** shows who to chase.
- **GST summary** is a **draft** for your accountant. It is not a return to file.

Use **Export all reports** to download every report for a period as one ZIP file (Excel, PDF or CSV), for
example at month end for your accountant.

## Documents
Open **Documents** to upload bills, warranty cards, contracts, photos, manuals and ID proofs (PDF, JPEG, PNG,
WebP, Word, Excel, text or CSV, up to 15 MB). You can also attach files directly from a service job, a
customer's account or a piece of customer equipment.
- Set an **expiry date** on contracts, AMCs, licences and warranty cards. Filter "Expired or expiring in 30
  days", or run the **Documents expiring** report.
- People only see documents attached to records they are allowed to see. A salesperson cannot open an
  employee's papers, for example.
- Owners and managers can mark a document **sensitive** (ID proofs, contracts). Only they can see it.
- Deleting asks for a reason. Owners and managers can see deleted documents and restore them. Only an owner
  can **purge** a deleted document, which removes the file permanently.
- Technicians can attach photos and reports to their own jobs.

## Analytics
**Analytics** (owners, managers and accountants) shows sales, gross profit, collections, expenses, new
customers and service jobs for a period, each compared with the previous period of the same length, plus a
trend chart and your top products, customers, categories and payment methods. Gross profit only counts sales
whose cost was recorded; the page says how many lines were left out.

## Network monitoring
Owners and managers set this up; technicians and reception can watch it.
1. **Add agent** for a site and copy the `agent.json` it shows (the token is shown only once). Install the
   agent on an always-on PC at that site: see the [agent guide](MONITORING_AGENT.md).
2. **Add check** for each device: *Ping*, or *TCP port open* for devices that ignore ping (cameras and NVRs
   usually answer on 554 or 80). Link the check to the equipment so its status shows under IT Assets and CCTV.
3. **Down** means several results in a row failed (you choose how many). **Unknown** means the agent is not
   reporting, so NetCare cannot tell. Click a check for uptime, latency and its outages.
- **New token** if the agent PC was replaced; **Revoke** if it was lost. Either stops the old agent at once.
- The **Uptime and latency** report lists every check for a period.

## CCTV
**CCTV Management** shows each DVR/NVR with its storage, how many days it keeps, and the cameras on each
channel, with warranty and live network status. When adding a camera under IT Assets, choose its recorder
and channel; a channel can only be used once per recorder.

## Service jobs
1. **New ticket.** Pick the customer and the type (repair, installation, maintenance or complaint). Choose
   their registered equipment or describe a walk-in item, note what came with it (charger, bag), and assign a
   technician.
2. If you give an **estimate**, work can't start until you record the customer's answer (**Customer
   approved**, with a note such as "by phone").
3. The technician opens **My work**, starts the job, writes the diagnosis, and adds **parts from stock**.
   Unused parts can be returned.
4. Record the **work performed**, then **Mark completed**.
5. The office clicks **Create invoice**: parts plus labour go onto a draft invoice. Issue it under Sales.
   Then **Close** the ticket. Warranty jobs close without an invoice.
6. **Print** a job sheet when equipment comes in, and a completion report when it's done.

## Installations and customer equipment
- On an installation ticket, use **Register installed equipment** to list each camera, DVR and so on, with
  serial, location, IP and warranty months. You can tick **Start a maintenance schedule** at the same time.
- **IT Assets** lists all equipment by customer. Filter **Expiring in 30 days** before calling customers
  about AMC renewals.
- **Service management → Maintenance schedules** shows what's due. **Create visit ticket** makes the job, and
  completing it moves the next due date forward.

## Employees, attendance, leave and tasks
- Add staff under **Employees**. Tick **Technician** for people who take service jobs, and link their login so
  they see **My work**.
- **Attendance:** pick a day, mark each person (or **Mark everyone present**), then save. Corrections are kept
  in the audit log.
- **Leave:** staff request it themselves; an owner or manager approves it, and approved days show as leave in
  attendance.
- **Tasks:** assign follow-ups with due dates. People tick off their own tasks.
- NetCare does not calculate salaries, PF, ESI or other statutory dues.

## Dashboard
Choose a period (today, week, month, quarter, or Indian financial year starting 1 April) and a location. All
figures come from your records. Modules that are not built yet are listed under **Not yet available**, and
no numbers are shown for them.
