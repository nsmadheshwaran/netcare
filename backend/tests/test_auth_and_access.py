from conftest import add_member, register


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200


def test_register_login_me(client):
    t = register(client, "Shop A")
    r = client.post("/api/v1/auth/login", json={"email": t.email, "password": "correct-horse-battery"})
    assert r.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["memberships"][0]["role"] == "owner"
    assert me["memberships"][0]["organization_name"] == "Shop A"
    # Default location created
    assert [loc["name"] for loc in t.get("/api/v1/organization/locations").json()] == ["Main"]


def test_password_not_stored_plaintext(client):
    t = register(client)
    from app.models import User
    from app.db import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    u = db.query(User).filter_by(email=t.email).one()
    assert "correct-horse" not in u.password_hash and u.password_hash.startswith("$argon2")


def test_duplicate_registration_and_weak_password(client):
    t = register(client)
    r = client.post("/api/v1/auth/register", json={"email": t.email.upper(), "full_name": "x",
                                                   "password": "another-long-pass", "organization_name": "x"})
    assert r.status_code == 409
    r = client.post("/api/v1/auth/register", json={"email": "new@example.com", "full_name": "x",
                                                   "password": "short", "organization_name": "x"})
    assert r.status_code == 422


def test_bad_login_and_rate_limit(client):
    t = register(client)
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": t.email, "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": t.email, "password": "correct-horse-battery"})
    assert r.status_code == 429


def test_requires_auth_and_valid_token(client):
    assert client.get("/api/v1/customers", headers={"X-Organization-ID": "1"}).status_code == 401
    r = client.get("/api/v1/customers", headers={"Authorization": "Bearer garbage", "X-Organization-ID": "1"})
    assert r.status_code == 401


def test_password_change_revokes_tokens(client):
    t = register(client)
    r = t.post("/api/v1/auth/change-password",
               json={"current_password": "correct-horse-battery", "new_password": "new-long-password-1"})
    assert r.status_code == 204
    assert t.get("/api/v1/customers").status_code == 401


def test_org_isolation_customers_products(client):
    a, b = register(client, "A"), register(client, "B")
    cust = a.post("/api/v1/customers", json={"name": "Secret Client", "phone": "9876543210"}).json()
    cat = a.post("/api/v1/product-categories", json={"name": "Laptops"}).json()
    prod = a.post("/api/v1/products", json={"name": "ThinkPad", "sku": "TP-1", "category_id": cat["id"]}).json()

    # B cannot read A's data by ID
    assert b.get(f"/api/v1/customers/{cust['id']}").status_code == 404
    assert b.put(f"/api/v1/customers/{cust['id']}", json={"name": "hacked"}).status_code == 404
    assert b.post(f"/api/v1/customers/{cust['id']}/archive").status_code == 404
    assert b.get(f"/api/v1/products/{prod['id']}").status_code == 404
    assert b.get("/api/v1/customers").json()["total"] == 0
    assert b.get("/api/v1/products").json()["total"] == 0
    # B cannot point a product at A's category
    assert b.post("/api/v1/products", json={"name": "x", "sku": "X1", "category_id": cat["id"]}).status_code == 422
    # B cannot move A's stock or use A's location
    a_loc = a.get("/api/v1/organization/locations").json()[0]["id"]
    b_loc = b.get("/api/v1/organization/locations").json()[0]["id"]
    mv = {"product_id": prod["id"], "location_id": b_loc, "movement_type": "stock_in", "quantity": "5"}
    assert b.post("/api/v1/inventory/movements", json=mv).status_code == 404
    b_prod = b.post("/api/v1/products", json={"name": "y", "sku": "Y1"}).json()
    mv = {"product_id": b_prod["id"], "location_id": a_loc, "movement_type": "stock_in", "quantity": "5"}
    assert b.post("/api/v1/inventory/movements", json=mv).status_code == 404
    # A's export does not include B's records and vice versa
    assert "Secret Client" not in b.get("/api/v1/customers/export.csv").text


def test_cannot_switch_to_foreign_org_header(client):
    a, b = register(client, "A"), register(client, "B")
    h = {"Authorization": f"Bearer {b.token}", "X-Organization-ID": str(a.org_id)}
    assert client.get("/api/v1/customers", headers=h).status_code == 404
    assert client.get("/api/v1/organization", headers=h).status_code == 404
    assert client.get("/api/v1/dashboard/summary", headers=h).status_code == 404


def test_role_permissions(client):
    owner = register(client)
    viewer = add_member(owner, "viewer")
    tech = add_member(owner, "technician")
    inv = add_member(owner, "inventory_manager")
    assert viewer.get("/api/v1/customers").status_code == 200
    assert viewer.post("/api/v1/customers", json={"name": "x"}).status_code == 403
    assert tech.post("/api/v1/products", json={"name": "x", "sku": "S1"}).status_code == 403
    assert inv.post("/api/v1/products", json={"name": "x", "sku": "S1"}).status_code == 201
    assert inv.get("/api/v1/customers").status_code == 403
    assert viewer.get("/api/v1/organization/members").status_code == 403
    assert viewer.get("/api/v1/audit-logs").status_code == 403
    assert owner.get("/api/v1/audit-logs").json()["total"] > 0


def test_manager_cannot_demote_owner_and_last_owner_kept(client):
    owner = register(client)
    mgr = add_member(owner, "manager")
    members = owner.get("/api/v1/organization/members").json()
    owner_mid = next(m["id"] for m in members if m["role"] == "owner")
    assert mgr.patch(f"/api/v1/organization/members/{owner_mid}", json={"role": "viewer"}).status_code == 403
    assert mgr.post("/api/v1/organization/members", json={"email": "o2@example.com", "full_name": "o",
                                                          "role": "owner",
                                                          "temporary_password": "temporary-pass-1"}).status_code == 403
    assert owner.patch(f"/api/v1/organization/members/{owner_mid}", json={"is_active": False}).status_code == 409


def test_deactivated_member_loses_access(client):
    owner = register(client)
    v = add_member(owner, "viewer")
    mid = next(m["id"] for m in owner.get("/api/v1/organization/members").json() if m["email"] == v.email)
    owner.patch(f"/api/v1/organization/members/{mid}", json={"is_active": False})
    assert v.get("/api/v1/customers").status_code == 404
