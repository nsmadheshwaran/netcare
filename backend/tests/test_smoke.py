"""Every GET endpoint without path parameters answers without a server error, for the owner."""
from app.main import app


def test_no_server_errors_on_plain_gets(tenant):
    paths = sorted(p for p, ops in app.openapi()["paths"].items()
                   if "get" in ops and p.startswith("/api/v1/") and "{" not in p and "/agent/" not in p)
    assert len(paths) > 40
    failures = {}
    for p in paths:
        r = tenant.get(p)
        if r.status_code >= 500:
            failures[p] = r.status_code
    assert failures == {}
