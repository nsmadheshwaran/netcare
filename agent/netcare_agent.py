"""NetCare monitoring agent.

Runs on a computer at a customer's site and reports to NetCare over outbound HTTPS. It only runs the checks
configured for it in NetCare (ping or a TCP connect to one named host and port). It never scans, discovers,
logs in to devices, runs remote commands or reads files.

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

VERSION = "1.0.0"
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


def run_check(c: dict) -> dict:
    try:
        if c["kind"] == "tcp":
            ok, lat, err = check_tcp(c["host"], c["port"], c["timeout_ms"])
        else:
            ok, lat, err = check_icmp(c["host"], c["timeout_ms"])
    except ValueError as e:
        ok, lat, err = False, None, str(e)
    return {"check_id": c["id"], "observed_at": now_iso(), "ok": ok, "latency_ms": lat, "error": err}


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
        self.checks = [c for c in cfg["checks"] if c["kind"] in ("icmp", "tcp")]
        self.refresh_seconds = int(cfg.get("config_refresh_seconds", 300))
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

    def run_once(self) -> int:
        self.fetch_config()
        with ThreadPoolExecutor(max_workers=16) as pool:
            self.queue.add(list(pool.map(run_check, self.checks)))
        return self.flush()

    def run_forever(self):  # pragma: no cover - exercised by hand; parts are unit tested
        next_due: dict[int, float] = {}
        last_config = 0.0
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
