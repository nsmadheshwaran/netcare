import itertools
import os
import shutil

os.environ["NETCARE_NOTIFICATIONS_WORKER"] = "false"  # tests run sweeps explicitly, never in the background

import pytest  # noqa: E402
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db, make_engine
from app.main import app
from app.security import login_limiter

_counter = itertools.count()


# Set to a PostgreSQL URL (e.g. in CI) to run the whole suite against PostgreSQL instead of SQLite.
PG_URL = os.environ.get("NETCARE_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory):
    """Run the real Alembic migrations once. SQLite: each test gets a copy of the file. PostgreSQL: the
    migrations are also run down to the start and up again, then each test starts from emptied tables."""
    cfg = Config("alembic.ini")
    if PG_URL:
        cfg.attributes["database_url"] = PG_URL
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        return None
    path = tmp_path_factory.mktemp("template") / "template.db"
    cfg.attributes["database_url"] = f"sqlite:///{path}"
    command.upgrade(cfg, "head")
    return path


@pytest.fixture(scope="session")
def pg_engine():
    """One shared engine and small connection pool for the whole PostgreSQL run, not one per test: creating
    a fresh pool (5 + 10 overflow connections) per test is what made ~140 tests take many minutes instead of
    about one, the same as SQLite."""
    if not PG_URL:
        yield None
        return
    engine = make_engine(PG_URL, pool_size=5, max_overflow=0)
    yield engine
    engine.dispose()


def _fresh_engine(tmp_path, template, pg_engine):
    if PG_URL:
        with pg_engine.begin() as con:
            # Fail fast and say so, instead of waiting forever behind a lock a previous test left open.
            con.exec_driver_sql("SET lock_timeout = '15s'")
            tables = [r[0] for r in con.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename <> 'alembic_version'")]
            con.exec_driver_sql(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
        return pg_engine
    db_path = tmp_path / "test.db"
    shutil.copyfile(template, db_path)
    return make_engine(f"sqlite:///{db_path}")


@pytest.fixture(autouse=True)
def storage_dir(tmp_path, monkeypatch):
    """Uploaded documents go to a per-test directory."""
    path = tmp_path / "storage"
    monkeypatch.setattr(get_settings(), "storage_dir", str(path))
    return path


@pytest.fixture()
def client(tmp_path, migrated_template, pg_engine):
    """Fresh database per test."""
    engine = _fresh_engine(tmp_path, migrated_template, pg_engine)
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
    if not PG_URL:  # the PostgreSQL engine is shared and disposed once, by the pg_engine fixture
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
