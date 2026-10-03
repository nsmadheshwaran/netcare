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

SNMP metrics are **not** implemented yet.

## Install (Windows)
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
