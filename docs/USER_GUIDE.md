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

## Dashboard
Choose a period (today, week, month, quarter, or Indian financial year starting 1 April) and a location. All
figures come from your records. Modules that are not built yet are listed under **Not yet available**, and
no numbers are shown for them.
