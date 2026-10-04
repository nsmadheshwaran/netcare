# Notifications

## Channels
| Channel | Status |
|---|---|
| In app (bell and **Alerts** page) | Always on. The bell refreshes every minute and when the window regains focus. |
| Email | Sent only when SMTP is configured (below). Each user chooses per kind; some kinds email by default. |
| SMS / WhatsApp | Optional, through **Twilio** or a **webhook** to your own bridge (for MSG91, Gupshup or any Indian gateway). Only urgent kinds can be texted (device down, PC critical, job assigned to you). Each person opts in and saves their own mobile number under Alerts → Preferences. Same outbox and retries as email. |

## What is sent, and to whom
| Kind | When | Who |
|---|---|---|
| Device down / back up | An outage opens (failure threshold reached) and when it ends | `monitoring.view` (owner, manager, technician, reception) |
| PC security critical | A PC's rating becomes critical (at most once per PC per day) | `security.view` |
| Job assigned to you | A service ticket is created for, or reassigned to, your employee record | that person |
| Task assigned to you | A task is created for, or reassigned to, you | that person |
| Leave request | Someone requests leave | `attendance.manage`, except the requester |
| Leave decided | Your request is approved or rejected | the requester |
| Daily: invoices overdue, low stock, maintenance due, agents not reporting, documents expiring | Once per business-local day, when there is something to report | `payments.view`, `inventory.view`, `service.edit`, `monitoring.manage`, `documents.view` |

Nobody is notified about their own action. The document digest counts only documents that person may see.
Each user can switch every kind off in the app or by email under **Alerts → Preferences**.

## How it works
- Events call `services/notify.notify()` in the same database transaction as the change, so a notification
  exists exactly when the change was saved. A `dedupe_key` per user stops repeats.
- A background thread in the API (`NETCARE_NOTIFICATIONS_WORKER`, on by default) runs once a minute: it builds
  daily digests for every active business and sends queued emails. Run the API with **one** worker process;
  with several, digests are still not duplicated, but an email could be sent twice.
- Emails wait in `email_outbox`. A failed send retries after 2, 4, 8 and 16 minutes, then is marked failed with
  the error. Owners see the last 100 under **Alerts → Email delivery**.
- Owners can build today's digests at once with `POST /api/v1/notifications/run-digests`.

## Configure text messages
```ini
NETCARE_SMS_PROVIDER=twilio            # or webhook
NETCARE_SMS_CHANNEL=sms                # or whatsapp
NETCARE_TWILIO_ACCOUNT_SID=AC...
NETCARE_TWILIO_AUTH_TOKEN=...
NETCARE_TWILIO_FROM=+1415...           # your Twilio number (WhatsApp-enabled for whatsapp)
# webhook instead: NetCare POSTs {"to": "+91...", "message": "...", "channel": "sms"} with Bearer <secret>
NETCARE_SMS_WEBHOOK_URL=https://your-bridge.example.com/send
NETCARE_SMS_WEBHOOK_SECRET=long-random-secret
```
In India, SMS to Indian numbers requires DLT registration of your sender ID and message templates (done with
your provider); WhatsApp business messages to people who have not messaged you first need approved templates.
Test with one number before switching it on for everyone.

## Configure email
Set in `.env` and restart the backend:
```ini
NETCARE_APP_URL=https://netcare.example.com
NETCARE_SMTP_HOST=smtp.example.com
NETCARE_SMTP_PORT=587
NETCARE_SMTP_USER=alerts@example.com
NETCARE_SMTP_PASSWORD=app-password-here
NETCARE_SMTP_FROM=NetCare <alerts@example.com>
NETCARE_SMTP_STARTTLS=true
```
Then use **Alerts → Preferences → Send me a test email**. For Gmail or Microsoft 365, use an app password or
an SMTP relay; keep the password only in `.env`.
