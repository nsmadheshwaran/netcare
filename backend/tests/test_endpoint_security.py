"""Phase 7: endpoint security visibility (Defender status and detections)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import add_member, register
from test_monitoring import AGENT, make_agent
from test_trade import setup

from app.models_security import Endpoint, EndpointThreat
from app.services import endpoint_security as es

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import netcare_agent  # noqa: E402

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def iso(days_ago: float, base=None) -> str:
    return ((base or datetime.now(timezone.utc)) - timedelta(days=days_ago)).isoformat()


def healthy(**kw):
    return {"av_enabled": True, "realtime_enabled": True, "antispyware_enabled": True,
            "behavior_monitor_enabled": True, "tamper_protected": True, "running_mode": "Normal",
            "signature_version": "1.459.1.0", "signature_updated_at": iso(0.5), "engine_version": "1.1.1",
            "product_version": "4.18.1", "quick_scan_at": iso(1), "full_scan_at": None, **kw}


def report(client, token, hostname="FRONTDESK", defender="healthy", threats=()):
    body = {"hostname": hostname, "os_name": "Microsoft Windows 11 Pro", "os_version": "10.0.26100",
            "defender": healthy() if defender == "healthy" else defender, "threats": list(threats)}
    return client.post(AGENT + "/endpoint", headers={"Authorization": f"Bearer {token}"}, json=body)


def threat(det="D1", status=3, days=1, name="Trojan:Win32/Test", sev=5):
    return {"detection_id": det, "threat_name": name, "severity_id": sev, "category": "trojan", "status_id": status,
            "action_success": True, "detected_at": iso(days), "resources": "file:_C:\\Temp\\bad.exe"}


def endpoint_agent(t, **kw):
    a = make_agent(t, collect_endpoint=True, **kw)
    assert a["collect_endpoint"] is True
    return a


# ---------------- rating rules (pure) ----------------
def ep(**kw):
    base = dict(last_report_at=NOW, defender_available=True, av_enabled=True, realtime_enabled=True,
                tamper_protected=True, running_mode="Normal", signature_updated_at=NOW - timedelta(hours=5),
                quick_scan_at=NOW - timedelta(days=2), full_scan_at=None)
    return Endpoint(**{**base, **kw})


def th(status, days=1, ack=False):
    return EndpointThreat(threat_name="T", status=status, detected_at=NOW - timedelta(days=days),
                          acknowledged_at=NOW if ack else None)


def test_rating_rules():
    assert es.evaluate(ep(), [], NOW) == ("ok", [])
    assert es.evaluate(ep(last_report_at=None), [], NOW)[0] == "unknown"
    assert es.evaluate(ep(last_report_at=NOW - timedelta(hours=25)), [th("detected")], NOW)[0] == "unknown"
    assert es.evaluate(ep(defender_available=False), [], NOW)[0] == "critical"
    level, reasons = es.evaluate(ep(realtime_enabled=False, tamper_protected=False), [], NOW)
    assert level == "critical" and reasons[0] == "Real-time protection is turned off"  # worst first
    assert es.evaluate(ep(signature_updated_at=NOW - timedelta(days=4)), [], NOW)[0] == "warning"
    assert es.evaluate(ep(quick_scan_at=NOW - timedelta(days=20)), [], NOW)[0] == "warning"
    assert es.evaluate(ep(full_scan_at=NOW - timedelta(days=1), quick_scan_at=None), [], NOW)[0] == "ok"
    # Passive mode: AV "off" is expected (another product protects), but flag it for confirmation
    level, reasons = es.evaluate(ep(running_mode="Passive Mode", av_enabled=False, realtime_enabled=False), [], NOW)
    assert level == "warning" and "passive" in reasons[0]
    for s in ("detected", "remove_failed", "quarantine_failed", "abandoned"):
        assert es.evaluate(ep(), [th(s)], NOW)[0] == "critical", s
    assert es.evaluate(ep(), [th("quarantined")], NOW)[0] == "warning"  # recent, not reviewed
    assert es.evaluate(ep(), [th("quarantined", ack=True)], NOW)[0] == "ok"
    assert es.evaluate(ep(), [th("quarantined", days=10)], NOW)[0] == "ok"
    assert es.evaluate(ep(), [th("allowed", days=20)], NOW)[0] == "warning"


# ---------------- API ----------------
def test_report_and_view(tenant, client):
    loc, sup, cam, svc, cust = setup(tenant)
    a = endpoint_agent(tenant, customer_id=cust["id"])
    assert client.get(AGENT + "/config", headers={"Authorization": f"Bearer {a['token']}"}).json()[
        "collect_endpoint"] is True
    r = report(client, a["token"], threats=[threat("{AB-1}", status=103), threat("D2", status=3, days=40)])
    assert r.status_code == 200, r.text
    rows = tenant.get("/api/v1/endpoints").json()
    assert len(rows) == 1
    e = rows[0]
    assert e["hostname"] == "FRONTDESK" and e["customer_name"] == "Local School"
    assert e["rating"] == "critical" and e["active_threats"] == 1 and e["threats_30d"] == 1  # 40-day-old one hidden
    assert e["reasons"] == ["Active threat: Trojan:Win32/Test (remove failed)"]
    d = tenant.get(f"/api/v1/endpoints/{e['id']}").json()
    assert d["tamper_protected"] is True and d["threats"][0]["severity"] == "severe"
    assert d["threats"][0]["resources"] == "file:_C:\\Temp\\bad.exe"

    # Acknowledging an active threat is refused: NetCare does not pretend it is handled
    tid = d["threats"][0]["id"]
    assert tenant.post(f"/api/v1/endpoints/{e['id']}/threats/{tid}/acknowledge",
                       json={"note": "Removed by hand"}).status_code == 409
    # Next report: Defender removed it. Same detection id is updated, not duplicated
    report(client, a["token"], threats=[threat("{AB-1}", status=4)])
    d = tenant.get(f"/api/v1/endpoints/{e['id']}").json()
    assert len(d["threats"]) == 1 and d["threats"][0]["status"] == "removed" and d["rating"] == "warning"
    r = tenant.post(f"/api/v1/endpoints/{e['id']}/threats/{tid}/acknowledge", json={"note": "Checked; user warned"})
    assert r.status_code == 200 and r.json()["acknowledged_by"]
    assert tenant.get(f"/api/v1/endpoints/{e['id']}").json()["rating"] == "ok"
    # If it comes back as active, the acknowledgement is cleared
    report(client, a["token"], threats=[threat("{AB-1}", status=1)])
    d = tenant.get(f"/api/v1/endpoints/{e['id']}").json()
    assert d["rating"] == "critical" and d["threats"][0]["acknowledged_at"] is None

    s = tenant.get("/api/v1/endpoints/summary").json()
    assert s == {"endpoints": 1, "critical": 1, "warning": 0, "ok": 0, "unknown": 0, "active_threats": 1}
    rep = tenant.get("/api/v1/reports/endpoint-security").json()
    assert rep["rows"][0]["rating"] == "CRITICAL" and rep["rows"][0]["threats"] == 1


def test_defender_missing_and_validation(tenant, client):
    a = endpoint_agent(tenant)
    assert report(client, a["token"], hostname="OLD-PC", defender=None).status_code == 200
    e = tenant.get("/api/v1/endpoints").json()[0]
    assert e["rating"] == "critical" and not e["defender_available"]
    bad = threat()
    bad["detected_at"] = iso(-1)  # tomorrow
    assert report(client, a["token"], threats=[bad]).status_code == 422
    assert report(client, a["token"], hostname="").status_code == 422


def test_opt_in_permissions_and_isolation(client):
    owner = register(client)
    other = register(client, "Other")
    plain = make_agent(owner, name="Network only")
    assert report(client, plain["token"]).status_code == 403  # endpoint reporting is opt-in per agent
    a = endpoint_agent(owner, name="With endpoint")
    report(client, a["token"])
    eid = owner.get("/api/v1/endpoints").json()[0]["id"]
    tech = add_member(owner, "technician")
    sales = add_member(owner, "salesperson")
    assert tech.get(f"/api/v1/endpoints/{eid}").status_code == 200
    assert sales.get("/api/v1/endpoints").status_code == 403
    assert other.get(f"/api/v1/endpoints/{eid}").status_code == 404
    assert other.get("/api/v1/endpoints").json() == []
    # Revoked agent can no longer report
    owner.post(f"/api/v1/monitoring/agents/{a['id']}/revoke")
    assert report(client, a["token"]).status_code == 401


def test_link_to_equipment(tenant, client):
    loc, sup, cam, svc, cust = setup(tenant)
    a = endpoint_agent(tenant)
    report(client, a["token"], hostname="PC-1")
    report(client, a["token"], hostname="PC-2")
    e1, e2 = tenant.get("/api/v1/endpoints").json()
    pc = tenant.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "computer",
                                             "name": "Reception PC"}).json()
    camera = tenant.post("/api/v1/assets", json={"customer_id": cust["id"], "asset_type": "camera",
                                                 "name": "Cam"}).json()
    r = tenant.put(f"/api/v1/endpoints/{e1['id']}/asset", json={"asset_id": pc["id"]})
    assert r.status_code == 200 and r.json()["asset_name"] == "Reception PC" and r.json()["customer_name"] == "Local School"
    assert tenant.put(f"/api/v1/endpoints/{e2['id']}/asset", json={"asset_id": pc["id"]}).status_code == 409
    assert tenant.put(f"/api/v1/endpoints/{e2['id']}/asset", json={"asset_id": camera["id"]}).status_code == 422
    assert tenant.put(f"/api/v1/endpoints/{e1['id']}/asset", json={"asset_id": None}).json()["asset_id"] is None


# ---------------- agent ----------------
SAMPLE = json.dumps({
    "os_name": "Microsoft Windows 11 Pro", "os_version": "10.0.26100",
    "defender": {"av_enabled": True, "realtime_enabled": True, "running_mode": "Normal", "signature_version": "",
                 "signature_updated_at": "2026-10-03T04:14:39.0000000Z", "quick_scan_at": None},
    # ConvertTo-Json turns a one-item array into a plain object
    "threats": {"detection_id": "{D042-11}", "threat_name": "Trojan:Win64/Example", "severity_id": 5,
                "category_id": 8, "status_id": 103, "action_success": True,
                "detected_at": "2026-09-30T04:39:04.3380000Z", "resources": "file:_C:\\Temp\\x.dll"}})


def test_agent_parses_defender_output():
    r = netcare_agent.parse_defender(SAMPLE, "FRONTDESK")
    assert r["hostname"] == "FRONTDESK" and r["defender"]["signature_version"] is None  # "" -> None
    assert r["threats"] == [{"detection_id": "D042-11", "threat_name": "Trojan:Win64/Example", "severity_id": 5,
                             "category": "trojan", "status_id": 103, "action_success": True,
                             "detected_at": "2026-09-30T04:39:04.3380000Z", "resources": "file:_C:\\Temp\\x.dll"}]
    none = netcare_agent.parse_defender(json.dumps({"os_name": "X", "defender": None, "threats": []}), "PC")
    assert none["defender"] is None and none["threats"] == []
    # The PowerShell text is fixed: no placeholders that could carry data from the server
    assert "{0}" not in netcare_agent.DEFENDER_PS and "Set-Mp" not in netcare_agent.DEFENDER_PS
    assert "Remove-Mp" not in netcare_agent.DEFENDER_PS and "Start-Mp" not in netcare_agent.DEFENDER_PS


def test_agent_reports_endpoint_end_to_end(tenant, client):
    a = endpoint_agent(tenant)

    def transport(method, url, headers, body, timeout):
        r = client.request(method, url.replace("http://localhost", ""), headers=headers, content=body)
        return r.status_code, r.content

    agent = netcare_agent.Agent("http://localhost", a["token"], None, transport=transport)
    agent.fetch_config()
    sample = json.loads(SAMPLE)
    sample["threats"]["detected_at"] = iso(1)
    assert agent.report_endpoint(lambda: netcare_agent.parse_defender(json.dumps(sample), "FRONTDESK"))
    e = tenant.get("/api/v1/endpoints").json()[0]
    assert e["hostname"] == "FRONTDESK" and e["active_threats"] == 1
    agent.collect_endpoint = False
    assert agent.report_endpoint(lambda: 1 / 0) is False  # not asked: the collector is not even run
