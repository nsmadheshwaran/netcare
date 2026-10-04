# Pilot release (1.0.0)

Use this checklist to run NetCare for one real business before a wider rollout. Tick every line.

## Before installing
- [ ] A server (or always-on PC) with Docker, 2 CPU, 4 GB RAM, and disk for the database and documents.
- [ ] A domain name and HTTPS in front of the `web` container (see [DEPLOYMENT](DEPLOYMENT.md)).
- [ ] An accountant has reviewed the GST rates, HSN codes and invoice layout for this business.
- [ ] Decide who is owner, and the role of every other user.

## Install
- [ ] Copy `.env.example` to `.env`; set a long random `POSTGRES_PASSWORD` and `NETCARE_SECRET_KEY`,
      `NETCARE_CORS_ORIGINS` and `NETCARE_APP_URL` to the public address.
- [ ] Optional: SMTP settings for email alerts ([NOTIFICATIONS](NOTIFICATIONS.md)).
- [ ] `docker compose up -d --build`; open the site; register the business (this creates the owner).
- [ ] Check that the latest GitHub Actions run is green, including **Backend (PostgreSQL 16)**.

## First day
- [ ] Work through the **Get started** checklist on the Overview page.
- [ ] Settings → Modules: switch off what the business does not use.
- [ ] Issue one test invoice, print it, and check it with the accountant. Cancel it if it was only a test.
- [ ] Add one monitoring agent at a customer site and one check; confirm it shows up/down correctly by
      unplugging the device briefly.
- [ ] Alerts → Preferences → Send me a test email (if email is configured).

## Backups (do not skip)
- [ ] Schedule `scripts/backup.sh` daily (database and documents) and copy `backups/` off the server.
- [ ] **Restore test:** restore last night's backup to a second machine and open an invoice PDF and an uploaded
      document. A backup is not trusted until this has worked.

## During the pilot (first 4 weeks)
- [ ] Weekly: compare the daily closing report with the cash drawer and bank.
- [ ] Weekly: read the audit log for unexpected actions; check Alerts → Email delivery for failures.
- [ ] Keep a list of problems and confusing screens; fix them before inviting more businesses.

## Known limitations to tell the pilot business
- Not accounting or GST-filing software; the GST summary is a draft for the accountant. No e-invoice or e-way bill.
- Password reset by email needs SMTP configured; otherwise an owner or manager resets it under Users and Roles.
- The agent installs with a PowerShell script as a scheduled task (not a signed Windows service); the data
  organizer is a command-line tool.
- SMS/WhatsApp alerts need your own provider account (Twilio, or a webhook to an Indian gateway).
