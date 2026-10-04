"""SNMP v2c read-only checks: wire format, a fake device, server rules, and the agent end to end."""
import socket
import sys
import threading
from pathlib import Path

import pytest

from test_monitoring import make_agent, send, ts

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import netcare_agent as na  # noqa: E402

SYS_UPTIME, SYS_NAME, IF1_STATUS, IF1_IN = ("1.3.6.1.2.1.1.3.0", "1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.2.2.1.8.1",
                                           "1.3.6.1.2.1.31.1.1.1.6.1")
DEVICE = {SYS_UPTIME: (0x43, (123456).to_bytes(3, "big")), SYS_NAME: (0x04, b"NVR-Gate"),
          IF1_STATUS: (0x02, b"\x01"), IF1_IN: (0x46, (2 ** 40 + 5).to_bytes(6, "big"))}


def respond(request: bytes, community: str, error_status: int = 0) -> bytes | None:
    """What a real SNMP agent would answer (no answer for a wrong community, as real devices do)."""
    _, msg, _ = na._read(request, 0)
    i = 0
    _, _v, i = na._read(msg, i)
    _, comm, i = na._read(msg, i)
    if comm.decode() != community:
        return None
    tag, pdu, _ = na._read(msg, i)
    assert tag == 0xA0, "only GetRequest is ever sent"
    j = 0
    _, rid, j = na._read(pdu, j)
    _, _s, j = na._read(pdu, j)
    _, _e, j = na._read(pdu, j)
    _, vbl, _ = na._read(pdu, j)
    out, k = b"", 0
    while k < len(vbl):
        _, vb, k = na._read(vbl, k)
        _, oid, _ = na._read(vb, 0)
        name = na._decode_oid(oid)
        vt, vv = DEVICE.get(name, (0x80, b""))  # noSuchObject
        out += na._tlv(0x30, na._oid(name) + na._tlv(vt, vv))
    resp = na._tlv(0xA2, na._tlv(0x02, rid) + na._int(error_status) + na._int(0) + na._tlv(0x30, out))
    return na._tlv(0x30, na._int(1) + na._tlv(0x04, comm) + resp)


@pytest.fixture()
def device():
    """A fake SNMP device on a random local UDP port, community 'secret-ro'."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                data, addr = s.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            answer = respond(data, "secret-ro")
            if answer:
                s.sendto(b"\x30\x00", addr)  # a junk packet first: the agent must ignore it
                s.sendto(answer, addr)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield s.getsockname()[1]
    stop.set()
    s.close()


def test_wire_format_round_trip():
    req = na.snmp_get_request("public", [SYS_UPTIME, "1.3.6.1.4.1.2021.10.1.3.1"], 777)
    assert req[0] == 0x30 and b"public" in req
    resp = respond(req, "public")
    values, err = na.parse_snmp_response(resp, 777)
    assert err is None and values[SYS_UPTIME] == 123456 and values["1.3.6.1.4.1.2021.10.1.3.1"] == "noSuchObject"
    with pytest.raises(ValueError):
        na.parse_snmp_response(resp, 778)  # someone else's answer
    values, err = na.parse_snmp_response(respond(req, "public", error_status=2), 777)
    assert err == "SNMP error: noSuchName"
    # Large OID arcs and long lengths encode and decode back exactly
    big = "1.3.6.1.4.1.99999.4294967295.0"
    assert na._decode_oid(na._read(na._oid(big), 0)[1]) == big
    assert na._read(na._tlv(0x04, b"x" * 300), 0)[1] == b"x" * 300


def test_agent_reads_device(device):
    ok, lat, err, values = na.check_snmp("127.0.0.1", device, "secret-ro", [SYS_UPTIME, SYS_NAME, IF1_STATUS, IF1_IN],
                                         2000)
    assert ok and err is None and lat is not None
    assert values == {SYS_UPTIME: 123456, SYS_NAME: "NVR-Gate", IF1_STATUS: 1, IF1_IN: 2 ** 40 + 5}
    ok, _, err, _ = na.check_snmp("127.0.0.1", device, "wrong", [SYS_UPTIME], 500)
    assert not ok and "no answer" in err
    ok, _, err, _ = na.check_snmp("127.0.0.1", device, "secret-ro", ["not-an-oid"], 500)
    assert not ok and "no valid OIDs" in err
    with pytest.raises(ValueError):
        na.check_snmp("-oProxyCommand=x", 161, "c", [SYS_UPTIME], 500)


def test_server_rules_and_write_only_community(tenant, client):
    a = make_agent(tenant)
    base = {"agent_id": a["id"], "name": "NVR SNMP", "kind": "snmp", "host": "192.168.1.50"}
    assert tenant.post("/api/v1/monitoring/checks", json=base).status_code == 422  # needs OIDs
    bad = tenant.post("/api/v1/monitoring/checks", json={**base, "snmp_oids": ["1.3.6.1.2.1.1.3.0", "sysUpTime"]})
    assert bad.status_code == 422 and "Not an OID" in bad.text
    r = tenant.post("/api/v1/monitoring/checks", json={**base, "snmp_community": "secret-ro",
                                                       "snmp_oids": [".1.3.6.1.2.1.1.3.0"]})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["port"] == 161 and c["snmp_oids"] == ["1.3.6.1.2.1.1.3.0"] and c["has_community"]
    assert "secret-ro" not in r.text and "secret-ro" not in tenant.get("/api/v1/monitoring/checks").text
    # Only the agent receives it
    cfg = client.get("/api/v1/agent/config", headers={"Authorization": f"Bearer {a['token']}"}).json()["checks"][0]
    assert cfg["snmp_community"] == "secret-ro" and cfg["snmp_oids"] == ["1.3.6.1.2.1.1.3.0"]
    # Editing without the community keeps it
    tenant.put(f"/api/v1/monitoring/checks/{c['id']}", json={**base, "name": "Renamed", "snmp_oids": ["1.3.6.1.2.1.1.3.0"]})
    cfg = client.get("/api/v1/agent/config", headers={"Authorization": f"Bearer {a['token']}"}).json()["checks"][0]
    assert cfg["snmp_community"] == "secret-ro"
    # Readings are stored and shown
    r = client.post("/api/v1/agent/results", headers={"Authorization": f"Bearer {a['token']}"}, json={"results": [
        {"check_id": c["id"], "observed_at": ts(1), "ok": True, "latency_ms": 4, "values": {SYS_UPTIME: 123456}}]})
    assert r.status_code == 200, r.text
    got = tenant.get(f"/api/v1/monitoring/checks/{c['id']}").json()
    assert got["last_values"] == {SYS_UPTIME: 123456} and got["status"] == "up"
    # Values are ignored for non-SNMP checks
    icmp = tenant.post("/api/v1/monitoring/checks", json={**base, "kind": "icmp", "name": "Ping",
                                                          "snmp_oids": ["1.3.6.1.2.1.1.3.0"]}).json()
    assert icmp["snmp_oids"] is None and icmp["port"] is None
    send(client, a["token"], (icmp["id"], ts(1), True, 2))


def test_agent_end_to_end(tenant, client, device):
    a = make_agent(tenant)
    r = tenant.post("/api/v1/monitoring/checks", json={
        "agent_id": a["id"], "name": "Gate NVR", "kind": "snmp", "host": "127.0.0.1", "port": device,
        "snmp_community": "secret-ro", "snmp_oids": [SYS_UPTIME, SYS_NAME, IF1_STATUS], "timeout_ms": 1500})
    assert r.status_code == 201, r.text

    def transport(method, url, headers, body, timeout):
        resp = client.request(method, url.replace("http://localhost", ""), headers=headers, content=body)
        return resp.status_code, resp.content

    agent = na.Agent("http://localhost", a["token"], None, transport=transport)
    assert agent.run_once() == 1
    got = tenant.get(f"/api/v1/monitoring/checks/{r.json()['id']}").json()
    assert got["status"] == "up" and got["last_values"] == {SYS_UPTIME: 123456, SYS_NAME: "NVR-Gate", IF1_STATUS: 1}
