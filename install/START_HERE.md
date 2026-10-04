# NetCare Business Suite: start here

NetCare runs on one computer in your business. Your data stays on that computer.

## What you need
- A Windows 10 or 11 PC that stays on during working hours (2 CPU cores, 8 GB RAM, 20 GB free disk recommended).
- **Docker Desktop**, free from docker.com. Install it, open it, and wait until it says it is running.
  (Docker's own licence terms apply; they are free for small businesses.)

## Install (about 15 minutes, mostly waiting)
1. Unzip this folder somewhere permanent, for example `C:\NetCare`. Do not run it from inside the zip file.
2. Open the folder, click the address bar, type `powershell` and press Enter.
3. Run this command:
   ```
   powershell -ExecutionPolicy Bypass -File .\install\install.ps1
   ```
4. Wait. The first time it downloads and builds everything. When it finishes, your browser opens NetCare.
5. Choose **Create an account** and enter your business name, your name, your email and a password of at
   least 10 characters. You become the Owner.
6. Follow the **Get started** checklist on the first page: business details (address, state, GSTIN), products
   with GST rates and HSN codes, then customers.

If the installer stops with an error, it says in plain words what to fix. Fix it and run the same command again.

## Use from other computers in the office
Open PowerShell **as Administrator** in this folder and run the install command again with `-AllowLan` on the end.
Staff then open `http://` + your PC's name + `:8080` in their browser (for example `http://office-pc:8080`).
This works on your office network only. Do not make it reachable from the internet.

## Backups: please read
- NetCare saves a backup every night at 2:00 AM into the `backups` folder (the PC must be on).
- A backup on the same PC is lost if the PC breaks or is stolen. **Copy the `backups` folder to another disk or
  a cloud drive every week.**
- Never delete the file called `.env` in this folder. It holds your database password. Keep a copy somewhere safe.
- To restore a backup (this replaces everything with the backup's contents):
  ```
  powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 -BackupFile .\backups\netcare-XXXX.sql.gz
  ```

## Starting and stopping
NetCare starts by itself when Docker Desktop starts. To stop it: `docker compose stop`. To start it again:
`docker compose start`. Both are run in PowerShell inside this folder.

## What NetCare is not
- It is not accounting or GST-filing software. The GST summary is a draft for your accountant to check.
- It does not create GST e-invoices (IRN) or e-way bills.
- Email, SMS and WhatsApp alerts work only after you enter your own email or messaging provider details.

## More help
The `docs` folder has the user guide and troubleshooting notes. For anything else, contact the person who
supplied NetCare to you.
