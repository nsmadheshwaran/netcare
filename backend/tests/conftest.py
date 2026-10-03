import itertools
import shutil

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db, make_engine
from app.main import app
from app.security import login_limiter

_counter = itertools.count()


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory):
    """Run the real Alembic migrations once; each test gets a copy of the result."""
    path = tmp_path_factory.mktemp("template") / "template.db"
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = f"sqlite:///{path}"
    command.upgrade(cfg, "head")
    return path


@pytest.fixture(autouse=True)
def storage_dir(tmp_path, monkeypatch):
    """Uploaded documents go to a per-test directory."""
    path = tmp_path / "storage"
    monkeypatch.setattr(get_settings(), "storage_dir", str(path))
    return path


@pytest.fixture()
def client(tmp_path, migrated_template):
    """Fresh database per test: a copy of the migrated template."""
    db_path = tmp_path / "test.db"
    shutil.copyfile(migrated_template, db_path)
    url = f"sqlite:///{db_path}"
    engine = make_engine(url)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    login_limiter._fails.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


class Tenant:
    def __init__(self, client, token, org_id, email):
        self.client, self.token, self.org_id, self.email = client, token, org_id, email

    @property
    def h(self):
        return {"Authorization": f"Bearer {self.token}", "X-Organization-ID": str(self.org_id)}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.h, **kw)

    def put(self, url, **kw):
        return self.client.put(url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.h, **kw)

    def upload(self, content: bytes, name="file.pdf", **form):
        return self.client.post("/api/v1/documents", headers=self.h, files={"file": (name, content)},
                                data={k: str(v) for k, v in form.items()})


def register(client, org="Acme Computers") -> Tenant:
    n = next(_counter)
    email = f"owner{n}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "full_name": f"Owner {n}",
                                                    "password": "correct-horse-battery", "organization_name": org})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return Tenant(client, token, me["memberships"][0]["organization_id"], email)


def add_member(owner: Tenant, role: str) -> Tenant:
    n = next(_counter)
    email = f"{role}{n}@example.com"
    r = owner.post("/api/v1/organization/members", json={"email": email, "full_name": role, "role": role,
                                                         "temporary_password": "temporary-pass-123"})
    assert r.status_code == 201, r.text
    tok = owner.client.post("/api/v1/auth/login", json={"email": email, "password": "temporary-pass-123"})
    return Tenant(owner.client, tok.json()["access_token"], owner.org_id, email)


@pytest.fixture()
def tenant(client):
    return register(client)
