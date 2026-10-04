# Handover: installing NetCare for a customer (one-time sale)

This is the checklist for selling NetCare once to a business and leaving them running on their own PC or
server. Each customer gets their **own installation and their own data**; nothing is shared between customers.

## What the customer needs
- A Windows 10/11 PC (or server) that stays on during working hours: 2 CPU cores, 8 GB RAM, 20 GB free disk.
- **Docker Desktop** (free for small businesses; check Docker's licence terms for larger ones): docker.com.
- For staff on other PCs: the PC and the staff PCs on the same office network.

## Install (about 15 minutes, mostly waiting)
1. Install Docker Desktop, start it, and wait until it says it is running.
2. Copy the NetCare folder to the PC (for example `C:\NetCare`).
3. Open PowerShell in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install\install.ps1
   ```
   It creates random passwords, builds and starts NetCare, schedules a **daily backup at 2:00 AM**, and
   opens the browser. If something is missing it says what to do.
4. Create the owner account on the page that opens, then work through the **Get started** checklist
   (business details with GSTIN and state, products with HSN codes and GST rates, customers).

**Other PCs in the office:** run the install from a PowerShell opened **as Administrator** with `-AllowLan`.
Staff then open `http://<pc-name>:8080`. The connection is plain HTTP on the office network; do not expose the
port to the internet. The firewall step needs Administrator and has not been tested on a real office network.

## Backups: the customer must understand this
- Backups are written to the `backups` folder next to NetCare (the newest 30 are kept).
- A backup on the same disk does not survive a dead disk or a stolen PC. **Copy `backups` to another disk or a
  cloud drive every week.**
- Restore (overwrites everything, asks you to type YES):
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 -BackupFile .\backups\netcare-XXXX.sql.gz
  ```
- The restore has been tested with sample data: records and uploaded documents came back. **Do one restore
  test on the customer's own machine before leaving.**
- Never delete the `.env` file: it holds the database password. Keep a copy in a safe place.

## Updates
Run `scripts\backup.ps1` first. Then put the new NetCare files in the same folder (keep `.env` and `backups`)
and run `docker compose up -d --build`. Database changes apply automatically on start. This upgrade path was tested once with
sample data (an older version with an issued invoice, payment and stock upgraded to the current one: the data,
sign-in and PDFs were intact), but take the backup and keep it until the new version works.

## Tell the customer what NetCare is not
- Not accounting or GST-filing software: the GST summary is a draft for their accountant.
- No GST e-invoice (IRN) or e-way bill.
- Email, SMS and WhatsApp alerts work only after they add their own SMTP / Twilio details
  (see [NOTIFICATIONS](NOTIFICATIONS.md)).

## Before you take payment (things only you can decide)
- **Sales agreement:** price, what support is included and for how long, who owns the data (the customer),
  and a limit on your liability. A starting draft is in [SALES_AGREEMENT_TEMPLATE](SALES_AGREEMENT_TEMPLATE.md).
  Have a lawyer review it; neither document is legal advice.
- **Support:** decide how problems are reported and how fast you answer. They will run a business on this.
- **Accountant:** ask the customer's accountant to check one printed invoice before real use.
- **Licence and source code:** decide whether the customer receives the source or only the running app.
- **Data protection:** their customers' personal data lives on the customer's own machine; tell them they are
  responsible for who can open that PC.
