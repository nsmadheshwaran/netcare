"""NetCare monitoring agent.

Runs on a computer at a customer's site and reports to NetCare over outbound HTTPS. It only runs the checks
configured for it in NetCare (ping or a TCP connect to one named host and port). It never scans, discovers,
logs in to devices, runs remote commands or reads files.

If endpoint reporting is switched on for the agent in NetCare, it also reads this PC's Microsoft Defender
status and recent detections with one fixed, read-only PowerShell query (DEFENDER_PS). It never changes
Defender settings, starts scans or removes anything.

Standard library only (Python 3.10+). Usage:
    python netcare_agent.py --config agent.json           run until stopped
    python netcare_agent.py --config agent.json --once    run every check once, send, exit (install test)

agent.json:
    {"server_url": "https://netcare.example.com", "token": "nca_...", "queue_file": "queue.jsonl"}
"""
import argparse
import ipaddress
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

VERSION = "1.2.0"
MAX_QUEUE = 50_000
BATCH = 500
HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
                     r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
PING_TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.I)
log = logging.getLogger("netcare-agent")


class Revoked(Exception):
    """The server rejected the token: stop, do not retry."""


def safe_host(host: str) -> str:
    """Accept exactly one IP address or host name. Guards the ping command line against option injection."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if not HOST_RE.match(host):
            raise ValueError(f"refusing unsafe host {host!r}")
        return host


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------------- checks ----------------
def check_tcp(host: str, port: int, timeout_ms: int) -> tuple[bool, int | None, str | None]:
    host = safe_host(host)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_ms / 1000):
            return True, round((time.perf_counter() - start) * 1000), None
    except socket.timeout:
        return False, None, f"TCP {port}: timed out"
    except OSError as e:
        return False, None, f"TCP {port}: {e.strerror or e.__class__.__name__}"


def check_icmp(host: str, timeout_ms: int) -> tuple[bool, int | None, str | None]:
    """Uses the system ping command (no raw sockets, so no administrator rights needed)."""
    host = safe_host(host)
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), host]
    start = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_ms / 1000 + 2,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, None, "ping: timed out"
    except FileNotFoundError:
        return False, None, "ping command not found"
    wall = round((time.perf_counter() - start) * 1000)
    # Windows ping returns 0 for "Destination host unreachable" replies from a router; require a TTL.
    if p.returncode == 0 and "TTL=" in p.stdout.upper():
        m = PING_TIME_RE.search(p.stdout)
        return True, round(float(m.group(1))) if m else wall, None
    return False, None, "ping: no reply"


# ---------------- SNMP v2c GET (read-only) ----------------
# Minimal BER encoding for one GetRequest. Only GET: no SET, no WALK/BULK, so it reads exactly the OIDs listed.
OID_RE = re.compile(r"^[0-2](\.\d{1,10}){1,40}$")
SNMP_ERRORS = {1: "tooBig", 2: "noSuchName", 3: "badValue", 4: "readOnly", 5: "genErr", 6: "noAccess"}


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _len(len(content)) + content


def _int(v: int) -> bytes:
    return _tlv(0x02, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.split(".")]
    out = bytearray([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def snmp_get_request(community: str, oids: list[str], request_id: int) -> bytes:
    varbinds = b"".join(_tlv(0x30, _oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(0xA0, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, varbinds))
    return _tlv(0x30, _int(1) + _tlv(0x04, community.encode()) + pdu)


def _read(buf: bytes, i: int) -> tuple[int, bytes, int]:
    """Read one TLV at i: (tag, content, next index)."""
    tag, n = buf[i], buf[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    if i + n > len(buf):
        raise ValueError("truncated SNMP packet")
    return tag, buf[i:i + n], i + n


def _decode_oid(b: bytes) -> str:
    parts, v = [b[0] // 40, b[0] % 40], 0
    for x in b[1:]:
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            parts.append(v)
            v = 0
    return ".".join(map(str, parts))


def _value(tag: int, b: bytes):
    if tag == 0x02:
        return int.from_bytes(b, "big", signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter32, Gauge32, TimeTicks, Counter64
        return int.from_bytes(b, "big")
    if tag == 0x04:
        try:
            s = b.decode("utf-8")
            return s if s.isprintable() else b.hex(":")
        except UnicodeDecodeError:
            return b.hex(":")
    if tag == 0x40 and len(b) == 4:
        return ".".join(map(str, b))
    if tag == 0x06:
        return _decode_oid(b)
    if tag == 0x05:
        return None
    return {0x80: "noSuchObject", 0x81: "noSuchInstance", 0x82: "endOfMibView"}.get(tag, b.hex())


def parse_snmp_response(packet: bytes, request_id: int) -> tuple[dict, str | None]:
    """Returns ({oid: value}, error or None)."""
    _, msg, _ = _read(packet, 0)
    i = 0
    _, _version, i = _read(msg, i)
    _, _community, i = _read(msg, i)
    tag, pdu, _ = _read(msg, i)
    if tag != 0xA2:
        raise ValueError("not an SNMP response")
    j = 0
    _, rid, j = _read(pdu, j)
    if int.from_bytes(rid, "big", signed=True) != request_id:
        raise ValueError("response to another request")
    _, status, j = _read(pdu, j)
    _, _index, j = _read(pdu, j)
    _, vbl, _ = _read(pdu, j)
    values, k = {}, 0
    while k < len(vbl):
        _, vb, k = _read(vbl, k)
        _, oid, m = _read(vb, 0)
        vtag, vval, _ = _read(vb, m)
        values[_decode_oid(oid)] = _value(vtag, vval)
    code = int.from_bytes(status, "big")
    return values, (f"SNMP error: {SNMP_ERRORS.get(code, code)}" if code else None)


def check_snmp(host: str, port: int, community: str, oids: list[str], timeout_ms: int):
    host = safe_host(host)
    oids = [o for o in oids if OID_RE.match(o)][:20]
    if not oids:
        return False, None, "no valid OIDs configured", None
    rid = int.from_bytes(os.urandom(3), "big")
    start = time.perf_counter()
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout_ms / 1000)
        try:
            s.sendto(snmp_get_request(community, oids, rid), (host, int(port)))
            while True:
                data, _addr = s.recvfrom(65535)
                try:
                    values, err = parse_snmp_response(data, rid)
                    break
                except (ValueError, IndexError):
                    continue  # stray or malformed packet: keep waiting until the timeout
        except socket.timeout:
            return False, None, "SNMP: no answer (wrong community, or SNMP off?)", None
        except OSError as e:
            return False, None, f"SNMP: {e.strerror or e}", None
    lat = round((time.perf_counter() - start) * 1000)
    return err is None, lat, err, {k: v for k, v in values.items()}


def run_check(c: dict) -> dict:
    values = None
    try:
        if c["kind"] == "tcp":
            ok, lat, err = check_tcp(c["host"], c["port"], c["timeout_ms"])
        elif c["kind"] == "snmp":
            ok, lat, err, values = check_snmp(c["host"], c["port"] or 161, c.get("snmp_community") or "public",
                                              c.get("snmp_oids") or [], c["timeout_ms"])
        else:
            ok, lat, err = check_icmp(c["host"], c["timeout_ms"])
    except ValueError as e:
        ok, lat, err = False, None, str(e)
    r = {"check_id": c["id"], "observed_at": now_iso(), "ok": ok, "latency_ms": lat, "error": err}
    if values is not None:
        r["values"] = {k: v for k, v in list(values.items())[:20]}
    return r


# ---------------- endpoint security (Windows Defender, read-only) ----------------
# Fixed text: nothing from the server or the network is ever inserted into it.
DEFENDER_PS = r"""
$ErrorActionPreference = 'Stop'
function iso($d) { if ($d -and $d.Year -gt 1601) { $d.ToUniversalTime().ToString('o') } else { $null } }
$os = Get-CimInstance Win32_OperatingSystem
$out = [ordered]@{ os_name = $os.Caption; os_version = $os.Version; defender = $null; threats = @() }
try {
  $s = Get-MpComputerStatus
  $out.defender = [ordered]@{
    av_enabled = $s.AntivirusEnabled; realtime_enabled = $s.RealTimeProtectionEnabled
    antispyware_enabled = $s.AntispywareEnabled; behavior_monitor_enabled = $s.BehaviorMonitorEnabled
    tamper_protected = $s.IsTamperProtected; running_mode = "$($s.AMRunningMode)"
    signature_version = "$($s.AntivirusSignatureVersion)"; signature_updated_at = iso $s.AntivirusSignatureLastUpdated
    engine_version = "$($s.AMEngineVersion)"; product_version = "$($s.AMProductVersion)"
    quick_scan_at = iso $s.QuickScanEndTime; full_scan_at = iso $s.FullScanEndTime }
  $names = @{}; foreach ($t in @(Get-MpThreat)) { $names["$($t.ThreatID)"] = $t }
  $since = (Get-Date).AddDays(-30)
  $out.threats = @(foreach ($d in @(Get-MpThreatDetection)) {
    if ($d.InitialDetectionTime -lt $since) { continue }
    $t = $names["$($d.ThreatID)"]
    [ordered]@{ detection_id = "$($d.DetectionID)"; threat_id = "$($d.ThreatID)"
      threat_name = $(if ($t) { $t.ThreatName } else { "Threat $($d.ThreatID)" })
      severity_id = $(if ($t) { [int]$t.SeverityID } else { $null })
      category_id = $(if ($t) { [int]$t.CategoryID } else { $null })
      status_id = [int]$d.ThreatStatusID; action_success = $d.ActionSuccess
      detected_at = iso $d.InitialDetectionTime; resources = ($d.Resources -join "; ") } })
} catch { $out.defender = $null }
$out | ConvertTo-Json -Depth 4 -Compress
"""
CATEGORY = {1: "adware", 2: "spyware", 3: "password stealer", 4: "trojan downloader", 5: "worm", 6: "backdoor",
            8: "trojan", 10: "keylogger", 12: "monitoring software", 13: "browser modifier",
            19: "remote control software", 21: "hacktool", 23: "potentially unwanted", 27: "exploit",
            30: "ransomware", 32: "behavior", 34: "known bad", 42: "potentially unwanted"}


def parse_defender(raw: str, hostname: str) -> dict:
    """Turn the PowerShell JSON into the report NetCare expects. Pure function, unit tested."""
    data = json.loads(raw)
    threats = data.get("threats") or []
    if isinstance(threats, dict):  # ConvertTo-Json unwraps single-item arrays
        threats = [threats]
    out = []
    for t in threats:
        if not t.get("detection_id") or not t.get("detected_at"):
            continue
        out.append({"detection_id": t["detection_id"].strip("{}")[:64],
                    "threat_name": (t.get("threat_name") or "?")[:200], "severity_id": t.get("severity_id"),
                    "category": CATEGORY.get(t.get("category_id")), "status_id": t.get("status_id"),
                    "action_success": t.get("action_success"), "detected_at": t["detected_at"],
                    "resources": (t.get("resources") or None) and t["resources"][:4000]})
    d = data.get("defender")
    if d:
        d = {k: (v or None) if isinstance(v, str) else v for k, v in d.items()}
    return {"hostname": hostname[:100], "os_name": data.get("os_name") or None,
            "os_version": data.get("os_version") or None, "defender": d, "threats": out}


def collect_defender() -> dict | None:
    """Run DEFENDER_PS. None on non-Windows or when PowerShell is unavailable."""
    if platform.system() != "Windows":
        return None
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", DEFENDER_PS], capture_output=True, text=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("could not read Defender status: %s", e)
        return None
    if p.returncode != 0 or not p.stdout.strip():
        log.warning("could not read Defender status: %s", p.stderr.strip()[:300])
        return None
    return parse_defender(p.stdout, socket.gethostname())


# ---------------- queue ----------------
class Queue:
    """Results waiting to be sent, kept on disk so a restart or a long outage loses nothing (up to MAX_QUEUE)."""

    def __init__(self, path: str | None):
        self.path, self.items, self.lock = path, [], threading.Lock()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        self.items.append(json.loads(line))
                    except ValueError:
                        pass  # a torn last line after a crash
            self.items = self.items[-MAX_QUEUE:]

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(i) + "\n" for i in self.items)
        os.replace(tmp, self.path)

    def add(self, items: list[dict]):
        with self.lock:
            self.items.extend(items)
            if len(self.items) > MAX_QUEUE:
                log.warning("queue full: dropping %d oldest results", len(self.items) - MAX_QUEUE)
                self.items = self.items[-MAX_QUEUE:]
            self._save()

    def peek(self, n: int) -> list[dict]:
        with self.lock:
            return list(self.items[:n])

    def drop(self, n: int):
        with self.lock:
            del self.items[:n]
            self._save()

    def __len__(self):
        return len(self.items)


# ---------------- server ----------------
def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Agent:
    def __init__(self, server_url: str, token: str, queue_file: str | None = None, transport=urllib_transport):
        url = server_url.rstrip("/")
        local = re.match(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", url)
        if not url.startswith("https://") and not local:
            raise ValueError("server_url must use https:// (plain http is allowed only for localhost)")
        self.base = url + "/api/v1/agent"
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                        "X-Agent-Version": VERSION, "X-Agent-Hostname": socket.gethostname()[:100],
                        "User-Agent": f"netcare-agent/{VERSION}"}
        self.transport = transport
        self.queue = Queue(queue_file)
        self.checks: list[dict] = []
        self.refresh_seconds = 300
        self.collect_endpoint = False
        self.endpoint_seconds = 900

    def _call(self, method: str, path: str, payload=None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        status, data = self.transport(method, self.base + path, self.headers, body, 30)
        if status == 401:
            raise Revoked("the server rejected this agent's token (revoked or rotated)")
        if status >= 400:
            raise OSError(f"server answered {status}: {data[:200]!r}")
        return json.loads(data or b"{}")

    def fetch_config(self):
        cfg = self._call("GET", "/config")
        self.checks = [c for c in cfg["checks"] if c["kind"] in ("icmp", "tcp", "snmp")]
        self.refresh_seconds = int(cfg.get("config_refresh_seconds", 300))
        self.collect_endpoint = bool(cfg.get("collect_endpoint"))
        self.endpoint_seconds = max(300, int(cfg.get("endpoint_report_seconds", 900)))
        log.info("config: %d checks", len(self.checks))

    def flush(self) -> int:
        """Send queued results in batches. Returns how many were delivered."""
        sent = 0
        while len(self.queue):
            batch = self.queue.peek(BATCH)
            out = self._call("POST", "/results", {"results": batch})
            if out.get("rejected_check_ids"):
                log.info("server no longer has checks %s; their results were discarded", out["rejected_check_ids"])
            self.queue.drop(len(batch))
            sent += len(batch)
        return sent

    def report_endpoint(self, collector=None) -> bool:
        """Send this PC's Defender status if NetCare asked for it. Not queued: only the latest status matters."""
        if not self.collect_endpoint:
            return False
        report = (collector or collect_defender)()
        if report is None:
            return False
        self._call("POST", "/endpoint", report)
        log.info("endpoint security reported (%d detections)", len(report["threats"]))
        return True

    def run_once(self) -> int:
        self.fetch_config()
        with ThreadPoolExecutor(max_workers=16) as pool:
            self.queue.add(list(pool.map(run_check, self.checks)))
        self.report_endpoint()
        return self.flush()

    def run_forever(self):  # pragma: no cover - exercised by hand; parts are unit tested
        next_due: dict[int, float] = {}
        last_config = 0.0
        last_endpoint = -1e9
        backoff = 5.0
        next_send = 0.0
        pool = ThreadPoolExecutor(max_workers=16)
        while True:
            now = time.monotonic()
            try:
                if now - last_config >= self.refresh_seconds:
                    self.fetch_config()
                    last_config = now
                    ids = {c["id"] for c in self.checks}
                    next_due = {k: v for k, v in next_due.items() if k in ids}
                due = [c for c in self.checks if next_due.get(c["id"], 0) <= now]
                for c in due:
                    next_due[c["id"]] = now + c["interval_seconds"]
                if due:
                    self.queue.add(list(pool.map(run_check, due)))
                if now >= next_send and len(self.queue):
                    self.flush()
                    backoff, next_send = 5.0, now + 15
                if self.collect_endpoint and now - last_endpoint >= self.endpoint_seconds:
                    last_endpoint = now  # also on failure: retried at the next interval, not every second
                    self.report_endpoint()
            except Revoked:
                raise
            except (OSError, ValueError) as e:
                log.warning("server unreachable (%s); %d results queued; retry in %ds", e, len(self.queue), backoff)
                next_send = now + backoff
                backoff = min(backoff * 2, 600)
                if not self.checks:
                    time.sleep(backoff)
            time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NetCare monitoring agent")
    ap.add_argument("--config", required=True, help="path to agent.json")
    ap.add_argument("--once", action="store_true", help="run every check once, send the results and exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    queue_file = cfg.get("queue_file") or os.path.join(os.path.dirname(os.path.abspath(args.config)), "queue.jsonl")
    agent = Agent(cfg["server_url"], cfg["token"], queue_file)
    try:
        if args.once:
            log.info("sent %d results", agent.run_once())
        else:
            agent.run_forever()
    except Revoked as e:
        log.error("%s. Stopping.", e)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
