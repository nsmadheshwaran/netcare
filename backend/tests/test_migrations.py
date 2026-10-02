"""Migrations must preserve existing data (regression: SQLite batch rebuild cascaded deletes)."""
import sqlite3

from alembic import command
from alembic.config import Config


def test_upgrade_downgrade_preserves_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "0001")
    con = sqlite3.connect(tmp_path / "m.db")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("INSERT INTO organizations (id,name,currency,is_active,created_at,updated_at) "
                "VALUES (1,'O','INR',1,'2026-01-01','2026-01-01')")
    con.execute("INSERT INTO customers (organization_id,customer_type,name,status,created_at,updated_at) "
                "VALUES (1,'individual','Keep me','active','2026-01-01','2026-01-01')")
    con.execute("INSERT INTO locations (organization_id,name,is_active,created_at,updated_at) "
                "VALUES (1,'Main',1,'2026-01-01','2026-01-01')")
    con.commit()
    con.close()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(tmp_path / "m.db")
    assert con.execute("SELECT name FROM customers").fetchall() == [("Keep me",)]
    assert con.execute("SELECT count(*) FROM locations").fetchone()[0] == 1
    assert con.execute("SELECT round_invoices_to_rupee FROM organizations").fetchone()[0] == 0
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
