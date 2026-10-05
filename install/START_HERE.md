# NetCare Business Suite: start here

NetCare runs on one computer in your business. Your data stays on that computer.

## What you need
- A Windows 10 or 11 PC that stays on during working hours (2 CPU cores, 8 GB RAM, 20 GB free disk recommended).
- **Docker Desktop**, free from docker.com. Install it, open it, and wait until it says it is running.
  (Docker's own licence terms apply; they are free for small businesses.)

## Install (about 15 minutes, mostly waiting)
1. Unzip this folder somewhere permanent, for example `C:\NetCare`. Do not run it from inside the zip file.
2. Double-click **Install NetCare.bat**. A black window opens and does the work; this is normal.
3. Wait. The first time it downloads and builds everything. When it finishes, your browser opens NetCare, and
   a **NetCare** icon appears on your Desktop and in the Start menu for next time.
4. Choose **Create an account** and enter your business name, your name, your email and a password of at
   least 10 characters. You become the Owner.
5. Follow the **Get started** checklist on the first page: business details (address, state, GSTIN), products
   with GST rates and HSN codes, then customers.

If the installer stops with an error, it says in plain words what to fix. Fix it and double-click the same
file again. If Windows warns "Windows protected your PC", click **More info**, then **Run anyway** — this
is normal for a script that was not bought from the Microsoft Store, not a sign of a problem.

## Everyday use
Click the **NetCare** icon on your Desktop to open it in your browser (Docker Desktop must be running; it
usually starts with Windows). The Start menu has a **NetCare** folder with:
- **Open NetCare** - same as the Desktop icon.
- **Start NetCare** / **Stop NetCare** - if you ever need to pause it (for example before moving the PC).
- **Backup Now** - takes a backup immediately, in addition to the nightly one.

## Use from other computers in the office
Double-click **Install NetCare (Office Network).bat** instead of the plain installer. Windows will ask to
confirm (this is needed to open the office firewall for NetCare). Staff then open `http://` + your PC's name +
`:8080` in their browser (for example `http://office-pc:8080`). This works on your office network only. Do
not make it reachable from the internet.

## Backups: please read
- NetCare saves a backup every night at 2:00 AM into the `backups` folder (the PC must be on).
- A backup on the same PC is lost if the PC breaks or is stolen. **Copy the `backups` folder to another disk or
  a cloud drive every week.**
- Never delete the file called `.env` in this folder. It holds your database password. Keep a copy somewhere safe.
- To restore a backup (this replaces everything with the backup's contents):
  ```
  powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 -BackupFile .\backups\netcare-XXXX.sql.gz
  ```

## What NetCare is not
- It is not accounting or GST-filing software. The GST summary is a draft for your accountant to check.
- It does not create GST e-invoices (IRN) or e-way bills.
- Email, SMS and WhatsApp alerts work only after you enter your own email or messaging provider details.

## More help
The `docs` folder has the user guide and troubleshooting notes. For anything else, contact the person who
supplied NetCare to you.
