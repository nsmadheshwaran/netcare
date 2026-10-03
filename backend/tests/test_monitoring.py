"""Phase 6: monitoring agents, checks, state machine, uptime, CCTV equipment, and the agent program."""
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import add_member, register
from test_trade import TODAY, setup

from app.services import monitoring as mon

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import netcare_agent  # noqa: E402

AGENT = "/api/v1/agent"


def ts(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def make_agent(t, name="Site agent", **kw):
    r = t.post("/api/v1/monitoring/agents", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def make_check(t, agent, **kw):
    body = {"agent_id": agent["id"], "name": "Router", "kind": "icmp", "host": "192.168.1.1", **kw}
    r = t.post("/api/v1/monitoring/checks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def agent_call(client, token, method, path, **kw):
    return client.request(method, AGENT + path, headers={"Authorization": f"Bearer {token}"}, **kw)


def send(client, token, *results):
    r = agent_call(client, token, "POST", "/results", json={"results": [
        {"check_id": c, "observed_at": at, "ok": ok, "latency_ms": lat, "error": None if ok else "no reply"}
        for c, at, ok, lat in results]})
    assert r.status_code == 200, r.text
    return r.json()


def check(t, cid):
    return t.get(f"/api/v1/monitoring/checks/{cid}").json()


# ---------------- agent tokens ----------------
def test_agent_token_lifecycle(tenant, client):
    a = make_agent(tenant)
    token = a["token"]
    assert token.startswith("nca_") and a["token_prefix"] == token[4:12]
    assert "token" not in tenant.get("/api/v1/monitoring/agents").json()[0]
    c = make_check(tenant, a)

    assert agent_call(client, "nca_wrong", "GET", "/config").status_code == 401
    assert client.get(AGENT + "/config", headers=tenant.h).status_code == 401  # a user login is not an agent token
    r = client.get(AGENT + "/config", headers={"Authorization": f"Bearer {token}", "X-Agent-Version": "1.0.0",
                                               "X-Agent-Hostname": "frontdesk-pc"})
    assert r.status_code == 200
    assert r.json()["checks"] == [{"id": c["id"], "kind": "icmp", "host": "192.168.1.1", "port": None,
                                   "interval_seconds": 60, "timeout_ms": 2000}]
    ag = tenant.get("/api/v1/monitoring/agents").json()[0]
    assert ag["online"] and ag["hostname"] == "frontdesk-pc" and ag["agent_version"] == "1.0.0"

    # Rotation: the old token stops at once
    new = tenant.post(f"/api/v1/monitoring/agents/{a['id']}/rotate-token").json()["token"]
    assert agent_call(client, token, "GET", "/config").status_code == 401
    assert agent_call(client, new, "GET", "/config").status_code == 200
    # Revocation stops the agent
    assert tenant.post(f"/api/v1/monitoring/agents/{a['id']}/revoke").json()["status"] == "revoked"
    assert agent_call(client, new, "GET", "/config").status_code == 401
    assert agent_call(client, new, "POST", "/results", json={"results": []}).status_code == 401
    # No new checks on a revoked agent
    assert tenant.post("/api/v1/monitoring/checks", json={"agent_id": a["id"], "name": "x", "kind": "icmp",
                                                          "host": "10.0.0.1"}).status_code == 422


# ---------------- state machine ----------------
def test_down_incident_and_recovery(tenant, client):
    a = make_agent(tenant)
    c = make_check(tenant, a, kind="tcp", host="192.168.1.20", port=554, failure_threshold=3, latency_warn_ms=200,
                   interval_seconds=3600)  # results below are minutes old; keep them fresh enough to show
    tok, cid = a["token"], c["id"]
    send(client, tok, (cid, ts(10), True, 12))
    assert check(tenant, cid)["status"] == "up"
    send(client, tok, (cid, ts(9), False, None), (cid, ts(8), False, None))
    st = check(tenant, cid)
    assert st["status"] == "up" and st["consecutive_failures"] == 2  # below the threshold: a blip, not an outage
    send(client, tok, (cid, ts(7), False, None))
    st = check(tenant, cid)
    assert st["status"] == "down" and st["last_error"] == "no reply"
    stats = tenant.get(f"/api/v1/monitoring/checks/{cid}/stats").json()
    inc = stats["incidents"][0]
    assert inc["ended_at"] is None
    assert abs(datetime.fromisoformat(inc["started_at"]) - datetime.fromisoformat(ts(9))) < timedelta(seconds=5)
    assert tenant.get("/api/v1/monitoring/overview").json()["open_incidents"] == 1

    send(client, tok, (cid, ts(5), True, 450))  # back, but slow
    st = check(tenant, cid)
    assert st["status"] == "degraded" and st["consecutive_failures"] == 0
    send(client, tok, (cid, ts(4), True, 20))
    assert check(tenant, cid)["status"] == "up"
    stats = tenant.get(f"/api/v1/monitoring/checks/{cid}/stats").json()
    assert stats["incidents"][0]["ended_at"] is not None and stats["incidents"][0]["minutes"] == 4
    w = stats["windows"]["24h"]
    assert w["samples"] == 6 and w["uptime_pct"] == 50.0 and w["incidents"] == 1 and w["downtime_minutes"] == 4
    assert w["avg_latency_ms"] == round((12 + 450 + 20) / 3) and w["p95_latency_ms"] == 450
    assert sum(b["samples"] for b in stats["series"]) == 6

    # Uptime report
    rep = tenant.get("/api/v1/reports/uptime", params={"date_from": TODAY,
                                                       "date_to": str(datetime.now().date())}).json()
    row = rep["rows"][0]
    assert row["uptime"] == "50.00%" and row["incidents"] == 1 and row["target"] == "192.168.1.20:554"


def test_ingest_rules(tenant, client):
    a = make_agent(tenant)
    c = make_check(tenant, a)
    other = register(client, "Other")
    foreign = make_check(other, make_agent(other))
    tok, cid = a["token"], c["id"]
    t3 = ts(3)
    out = send(client, tok, (cid, t3, True, 5), (cid, t3, True, 5), (foreign["id"], t3, False, None))
    assert out["accepted"] == 1 and out["duplicates"] == 1 and out["rejected_check_ids"] == [foreign["id"]]
    assert check(other, foreign["id"])["stored_status"] == "unknown"  # another business's check is untouched
    # Re-sending the same batch (agent retry after a lost response) changes nothing
    assert send(client, tok, (cid, t3, True, 5))["duplicates"] == 1
    # A late result is stored but does not overwrite newer state
    send(client, tok, (cid, ts(1), True, 7))
    send(client, tok, (cid, ts(2), False, None))
    st = check(tenant, cid)
    assert st["status"] == "up" and st["last_latency_ms"] == 7
    # Clock sanity
    future = agent_call(client, tok, "POST", "/results", json={"results": [
        {"check_id": cid, "observed_at": ts(-30), "ok": True}]})
    assert future.status_code == 422
    old = agent_call(client, tok, "POST", "/results", json={"results": [
        {"check_id": cid, "observed_at": ts(60 * 24 * 40), "ok": True}]}).json()
    assert old["too_old"] == 1 and old["accepted"] == 0
    big = agent_call(client, tok, "POST", "/results", json={"results": [
        {"check_id": cid, "observed_at": ts(1), "ok": True}] * 1001})
    assert big.status_code == 422


def test_offline_agent_shows_unknown(tenant, client, monkeypatch):
    a = make_agent(tenant)
    c = make_check(tenant, a)
    send(client, a["token"], (c["id"], ts(0.5), True, 3))
    assert check(tenant, c["id"])["status"] == "up"
    monkeypatch.setattr(mon, "AGENT_OFFLINE_AFTER", timedelta(seconds=-1))
    st = check(tenant, c["id"])
    assert st["status"] == "unknown" and st["stored_status"] == "up"  # no guessing, and no incident
    assert tenant.get("/api/v1/monitoring/overview").json()["checks"]["unknown"] == 1


def test_check_validation(tenant):
    loc, sup, cam, svc, cust = setup(tenant)
    other_cust = tenant.post("/api/v1/customers", json={"name": "Other site"}).json()
    a = make_agent(tenant, customer_id=cust["id"])
    base = {"agent_id": a["id"], "name": "x", "kind": "icmp"}
    for host in ("192.168.1.0/24", "192.168.1.1-50", "http://10.0.0.1", "-c 5 8.8.8.8", "*.local",
                 "255.255.255.255", "0.0.0.0", "224.0.0.1", "1.2.3"):
        r = tenant.post("/api/v1/monitoring/checks", json={**base, "host": host})
        assert r.status_code == 422, host
    assert tenant.post("/api/v1/monitoring/checks", json={**base, "kind": "tcp", "host": "10.0.0.1"}).status_code == 422
    assert tenant.post("/api/v1/monitoring/checks", json={**base, "host": "10.0.0.1", "interval_seconds": 10}).status_code == 422
    assert tenant.post("/api/v1/monitoring/checks", json={**base, "host": "10.0.0.1", "interval_seconds": 30,
                                                          "timeout_ms": 30000}).status_code == 422
    assert tenant.post("/api/v1/monitoring/checks", json=base).status_code == 422  # no host, no equipment
    ok = make_check(tenant, a, host="NVR.School.Local")
    assert ok["host"] == "nvr.school.local"
    # Host defaults to the equipment's IP; equipment must be at the agent's site
    nvr = tenant.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "nvr", "name": "NVR",
                                              "ip_address": "192.168.1.50"}).json()
    c = make_check(tenant, a, asset_id=nvr["id"], host=None)
    assert c["host"] == "192.168.1.50" and c["asset_name"] == "NVR" and c["customer_name"] == "Local School"
    far = tenant.post("/api/v1/assets", json={"customer_id": other_cust["id"], "asset_type": "router",
                                              "name": "R", "ip_address": "10.1.1.1"}).json()
    assert tenant.post("/api/v1/monitoring/checks", json={**base, "asset_id": far["id"]}).status_code == 422
    # ICMP drops a stray port
    assert make_check(tenant, a, host="10.0.0.9", port=80)["port"] is None


def test_target_change_resets_state(tenant, client):
    a = make_agent(tenant)
    c = make_check(tenant, a, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(2), False, None))
    assert check(tenant, c["id"])["status"] == "down"
    body = {"agent_id": a["id"], "name": "Router", "kind": "icmp", "host": "192.168.1.254", "failure_threshold": 1}
    r = tenant.put(f"/api/v1/monitoring/checks/{c['id']}", json=body).json()
    assert r["stored_status"] == "unknown" and r["last_checked_at"] is None
    assert tenant.get(f"/api/v1/monitoring/checks/{c['id']}/stats").json()["incidents"][0]["ended_at"]
    # Renaming only keeps the state
    send(client, a["token"], (c["id"], ts(1), True, 4))
    r = tenant.put(f"/api/v1/monitoring/checks/{c['id']}", json={**body, "name": "Gateway"}).json()
    assert r["stored_status"] == "up"
    assert tenant.client.delete(f"/api/v1/monitoring/checks/{c['id']}", headers=tenant.h).status_code == 204
    assert agent_call(client, a["token"], "GET", "/config").json()["checks"] == []


def test_permissions_and_isolation(client):
    owner = register(client)
    other = register(client, "Other")
    a = make_agent(owner)
    c = make_check(owner, a)
    tech = add_member(owner, "technician")
    sales = add_member(owner, "salesperson")
    mgr = add_member(owner, "manager")
    assert tech.get("/api/v1/monitoring/checks").status_code == 200
    assert tech.post("/api/v1/monitoring/agents", json={"name": "x"}).status_code == 403
    assert tech.post(f"/api/v1/monitoring/agents/{a['id']}/revoke").status_code == 403
    assert sales.get("/api/v1/monitoring/overview").status_code == 403
    assert mgr.post("/api/v1/monitoring/agents", json={"name": "Branch"}).status_code == 201
    assert other.get(f"/api/v1/monitoring/checks/{c['id']}").status_code == 404
    assert other.post(f"/api/v1/monitoring/agents/{a['id']}/rotate-token").status_code == 404
    assert other.post("/api/v1/monitoring/checks", json={"agent_id": a["id"], "name": "x", "kind": "icmp",
                                                         "host": "1.1.1.1"}).status_code == 422
    assert other.get("/api/v1/monitoring/checks").json() == []
    assert tech.get("/api/v1/reports/uptime").status_code == 403  # technicians have no reports.view


# ---------------- CCTV equipment ----------------
def test_cctv_recorder_channels(tenant, client):
    loc, sup, cam, svc, cust = setup(tenant)
    other = tenant.post("/api/v1/customers", json={"name": "Other"}).json()
    asset = lambda **kw: tenant.post("/api/v1/assets", json={"customer_id": cust["id"], **kw})  # noqa: E731
    nvr = asset(asset_type="nvr", name="NVR 16ch", hdd_capacity_gb=4000, retention_days=30,
                mac_address="aa-bb-cc-dd-ee-ff", ip_address="192.168.1.50").json()
    assert nvr["mac_address"] == "AA:BB:CC:DD:EE:FF" and nvr["retention_days"] == 30
    cam1 = asset(asset_type="camera", name="Gate", recorder_id=nvr["id"], channel=1, resolution="4MP")
    assert cam1.status_code == 201 and cam1.json()["recorder_name"] == "NVR 16ch"
    assert asset(asset_type="camera", name="Dup", recorder_id=nvr["id"], channel=1).status_code == 409
    assert asset(asset_type="camera", name="NoRec", channel=2).status_code == 422
    assert asset(asset_type="camera", name="Bad", recorder_id=cam1.json()["id"], channel=2).status_code == 422
    assert tenant.post("/api/v1/assets", json={"customer_id": other["id"], "asset_type": "camera", "name": "X",
                                               "recorder_id": nvr["id"], "channel": 3}).status_code == 422
    assert asset(asset_type="camera", name="M", mac_address="zz").status_code == 422
    # Editing a camera keeps its own channel
    body = {k: cam1.json()[k] for k in ("customer_id", "asset_type", "name", "recorder_id", "channel")}
    assert tenant.put(f"/api/v1/assets/{cam1.json()['id']}", json={**body, "name": "Main gate"}).status_code == 200
    # Monitoring status shows on the equipment
    assert tenant.get(f"/api/v1/assets/{nvr['id']}").json()["monitor_status"] is None
    a = make_agent(tenant, customer_id=cust["id"])
    c = make_check(tenant, a, asset_id=nvr["id"], host=None, kind="tcp", port=554, failure_threshold=1)
    send(client, a["token"], (c["id"], ts(1), False, None))
    assert tenant.get(f"/api/v1/assets/{nvr['id']}").json()["monitor_status"] == "down"


# ---------------- the agent program ----------------
@pytest.fixture()
def listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    yield s.getsockname()[1]
    s.close()


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_agent_checks_and_safety(listener):
    ok, lat, err = netcare_agent.check_tcp("127.0.0.1", listener, 1000)
    assert ok and lat is not None and err is None
    ok, lat, err = netcare_agent.check_tcp("127.0.0.1", closed_port(), 1000)
    assert not ok and lat is None and err.startswith("TCP")
    for bad in ("-c 9 1.1.1.1", "1.1.1.0/24", "a b", "x;rm -rf /", ""):
        with pytest.raises(ValueError):
            netcare_agent.safe_host(bad)
    r = netcare_agent.run_check({"id": 1, "kind": "icmp", "host": "-n 100 x", "timeout_ms": 500})
    assert r["ok"] is False and "unsafe" in r["error"]
    with pytest.raises(ValueError):
        netcare_agent.Agent("http://netcare.example.com", "nca_x")  # plain http only for localhost


def test_agent_queue_persists(tmp_path, monkeypatch):
    path = str(tmp_path / "q.jsonl")
    q = netcare_agent.Queue(path)
    q.add([{"n": i} for i in range(5)])
    q.drop(2)
    assert [i["n"] for i in netcare_agent.Queue(path).items] == [2, 3, 4]
    with open(path, "a") as f:
        f.write('{"torn')  # crash mid-write
    assert len(netcare_agent.Queue(path)) == 3
    monkeypatch.setattr(netcare_agent, "MAX_QUEUE", 4)
    q = netcare_agent.Queue(path)
    q.add([{"n": 9}, {"n": 10}])
    assert [i["n"] for i in q.items] == [3, 4, 9, 10]  # oldest dropped


def test_agent_end_to_end(tenant, client, listener, tmp_path):
    a = make_agent(tenant)
    up = make_check(tenant, a, name="Open port", kind="tcp", host="127.0.0.1", port=listener, failure_threshold=1)
    down = make_check(tenant, a, name="Closed port", kind="tcp", host="127.0.0.1", port=closed_port(),
                      failure_threshold=1)

    def transport(method, url, headers, body, timeout):
        r = client.request(method, url.replace("http://localhost", ""), headers=headers, content=body)
        return r.status_code, r.content

    def offline(*_):
        raise OSError("network unreachable")

    queue = str(tmp_path / "queue.jsonl")
    agent = netcare_agent.Agent("http://localhost", a["token"], queue, transport=transport)
    agent.fetch_config()
    agent.transport = offline  # results are queued while the server is unreachable
    agent.queue.add([netcare_agent.run_check(c) for c in agent.checks])
    with pytest.raises(OSError):
        agent.flush()
    assert len(netcare_agent.Queue(queue)) == 2  # survives a restart
    agent.transport = transport
    assert agent.flush() == 2 and len(agent.queue) == 0
    assert check(tenant, up["id"])["status"] == "up"
    assert check(tenant, down["id"])["status"] == "down"
    assert agent.run_once() == 2

    tenant.post(f"/api/v1/monitoring/agents/{a['id']}/revoke")
    with pytest.raises(netcare_agent.Revoked):
        agent.run_once()


def test_outages_close_when_monitoring_stops(tenant, client):
    a = make_agent(tenant)
    c1 = make_check(tenant, a, failure_threshold=1)
    c2 = make_check(tenant, a, name="Switch", host="192.168.1.2", failure_threshold=1)
    send(client, a["token"], (c1["id"], ts(2), False, None), (c2["id"], ts(2), False, None))
    body = {"agent_id": a["id"], "name": "Router", "kind": "icmp", "host": "192.168.1.1", "failure_threshold": 1,
            "enabled": False}
    assert tenant.put(f"/api/v1/monitoring/checks/{c1['id']}", json=body).status_code == 200
    inc = tenant.get(f"/api/v1/monitoring/checks/{c1['id']}/stats").json()["incidents"][0]
    assert inc["ended_at"] and "check disabled" in inc["reason"]
    tenant.post(f"/api/v1/monitoring/agents/{a['id']}/revoke")
    assert tenant.get("/api/v1/monitoring/overview").json()["open_incidents"] == 0
    # Checks of a revoked agent can still be edited, but no new ones added
    assert tenant.put(f"/api/v1/monitoring/checks/{c2['id']}",
                      json={**body, "name": "Switch", "host": "192.168.1.2"}).status_code == 200
    assert tenant.post("/api/v1/monitoring/checks", json={**body, "name": "New"}).status_code == 422
