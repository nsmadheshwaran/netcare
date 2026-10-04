# Monitoring agent

The agent is a single Python file, [`agent/netcare_agent.py`](../agent/netcare_agent.py), using only the
standard library. It runs on a computer at a customer's site and reports ping and port results to NetCare.

## Design rules (enforced)
| Rule | How |
|---|---|
| Installed explicitly by an administrator on an authorised network | Nothing installs itself. An owner or manager creates the agent in NetCare and copies the token to the site. |
| Outbound HTTPS only | The agent only makes requests to `server_url`. It refuses plain `http://` except for `localhost`. No ports are opened. |
| Unique, revocable token; server keeps only a hash | Tokens are `nca_` + 256 random bits. The database stores the SHA-256. **Revoke** or **New token** in NetCare makes the next request fail with 401, and the agent exits (code 2) instead of retrying. |
| Only configured checks | The agent runs exactly the checks NetCare sends: ping (ICMP) or a TCP connect to one host and port. The server rejects ranges, CIDR blocks, wildcards, URLs, broadcast and multicast; the agent re-checks every host before use. At most 200 checks per agent, each at most every 30 seconds. |
| Queue and retry when offline | Results go to `queue.jsonl` next to the config (up to 50,000; the oldest are dropped beyond that) and are sent with backoff from 5 s to 10 min. Results are idempotent, so a retry after a lost response is harmless. |
| Never | No network discovery or scanning, no logins to devices, no credential guessing, no exploitation, no remote commands, no hidden persistence, no collection of files, keystrokes or messages. The code has no way to do these: it runs `ping` with a validated host and opens TCP connections, nothing else. |

## SNMP readings (read-only)
Choose **SNMP readings** as the check type, give the device's read-only community and the OIDs to read (presets
for uptime, device name, port status and traffic are offered). The agent sends one SNMP v2c **GET** for exactly
those OIDs: never SET, WALK or BULK, so it cannot change a device or explore it. The check is up when the device
answers without an error; the latest readings show in the check's details. The community is stored on the
server and sent only to the agent; the web pages never show it again after saving. Use a read-only community
that is different from the device's admin one.

## Endpoint security (optional, Windows)
Switch on **Report this PC's Microsoft Defender status** when adding or editing the agent. Every 15 minutes
the agent then runs one fixed PowerShell query (`DEFENDER_PS` in the agent, read it before installing):
`Get-MpComputerStatus`, `Get-MpThreat`, `Get-MpThreatDetection` and the Windows version. These are read-only
cmdlets. The agent never calls `Set-MpPreference`, `Start-MpScan`, `Remove-MpThreat` or anything that changes
the PC. Nothing from the server is inserted into the query.

It reports: protection switches, running mode, definition and engine versions and age, last scan times, and
Defender detections of the last 30 days, including the file paths Defender lists for each detection (needed
to find and clean the file). It does not read the files themselves. The status covers only the PC the agent
runs on: install an agent on each PC you want to see. A PC with network checks switched off is fine.

## Install (Windows), with the install script
1. In NetCare: **Network monitoring → Add agent**. Copy the token shown (it is shown once).
2. Install Python 3.10+ from python.org; choose "Install for all users" if offered, and tick "Add to PATH".
3. Copy `netcare_agent.py`, `install-agent.ps1` and `uninstall-agent.ps1` to the PC, open **PowerShell as
   administrator** in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install-agent.ps1 -ServerUrl https://netcare.example.com -Token nca_...
   ```
   It copies the agent to `C:\ProgramData\NetCare\Agent` (readable only by Administrators and SYSTEM), runs it
   once to prove it reaches NetCare, then registers and starts the visible task "NetCare Monitoring Agent"
   (at startup, restarted if it stops). Uninstall with `.\uninstall-agent.ps1`, and revoke the agent in NetCare.

## Install (Windows), by hand
1. In NetCare: **Network monitoring → Add agent**. Copy the `agent.json` shown (the token is shown once).
2. On an always-on PC at the site, install Python 3.10+ from python.org (tick "Add to PATH").
3. Create `C:\NetCare\agent\`, copy `netcare_agent.py` and `agent.json` there. Restrict the folder to
   administrators: the token is a password for this agent.
4. Test: `python C:\NetCare\agent\netcare_agent.py --config C:\NetCare\agent\agent.json --once`.
   You should see `sent N results`, and the agent shows **online** in NetCare.
5. Run it at startup as a visible scheduled task (an administrator command prompt):
   ```bat
   schtasks /Create /TN "NetCare Monitoring Agent" /SC ONSTART /RU SYSTEM ^
     /TR "\"C:\Program Files\Python312\python.exe\" C:\NetCare\agent\netcare_agent.py --config C:\NetCare\agent\agent.json"
   schtasks /Run /TN "NetCare Monitoring Agent"
   ```
   Use your actual `python.exe` path (`where python`). It is listed in Task Scheduler under that name. (A signed installer that registers a Windows service
   and appears in *Installed apps* is a planned follow-up.)

Linux: the same files, run under a systemd service with `Restart=on-failure` (exit code 2 on a revoked token
stops restarts if you set `RestartPreventExitStatus=2`).

## Uninstall
1. In NetCare, **Revoke** the agent (it stops at its next request even if the PC is unreachable).
2. On the PC: `schtasks /Delete /TN "NetCare Monitoring Agent" /F`, then delete `C:\NetCare\agent\`.

## What the status means
- **Up / Slow**: the last result succeeded (slow = above the check's latency warning).
- **Down**: `failure_threshold` results in a row failed. An outage is recorded from the first failure until
  the next success.
- **Unknown**: the agent has not reported for 5 minutes, the check is disabled, or the last result is older
  than three intervals. NetCare does not guess and does not record an outage for this.
- Ping uses the system `ping` command, so no administrator rights are needed. Some devices ignore ping:
  use a TCP check on a port they serve (RTSP 554, HTTP 80/443, Hikvision SDK 8000, Dahua 37777).
