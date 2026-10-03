"""Phase 8: local data organizer (scan, duplicates, plan, dry run, approval, journal, rollback, backup check)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "organizer"))
import netcare_organizer as org  # noqa: E402


def write(p: Path, data: bytes | str, mtime: float | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode() if isinstance(data, str) else data)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "Shared"
    old = time.time() - 86400 * 30
    write(root / "invoice.pdf", b"%PDF invoice A", old)
    write(root / "Accounts" / "2026" / "invoice copy.pdf", b"%PDF invoice A")  # duplicate, deeper and newer
    write(root / "photo.jpg", b"\xff\xd8 photo")
    write(root / "notes.txt", "hello")
    write(root / "empty1.txt", b"")
    write(root / "empty2.txt", b"")  # empty files are never "duplicates"
    write(root / "same-size-a.bin", b"AAAA")
    write(root / "same-size-b.bin", b"BBBB")  # same size, different content
    write(root / "AppData" / "cache.bin", b"%PDF invoice A")  # excluded folder
    write(root / "~$report.docx", b"lock")  # Office lock file
    return root


def plan_file(tmp_path, roots, organize=False) -> str:
    plan = org.make_plan([str(r) for r in roots], organize)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    return str(p)


def load(p):
    return json.loads(Path(p).read_text())


def test_plan_finds_duplicates_and_changes_nothing(tmp_path, tree):
    before = sorted(str(p) for p in tree.rglob("*"))
    plan = org.make_plan([str(tree)])
    assert sorted(str(p) for p in tree.rglob("*")) == before  # planning changes nothing
    assert plan["summary"]["files_scanned"] == 8  # AppData and the ~$ lock file are not scanned
    dups = [a for a in plan["actions"] if a["kind"] == "duplicate"]
    assert len(dups) == 1
    assert dups[0]["src"].endswith("invoice copy.pdf")  # keeps the top-level, older copy
    assert f"{org.DUP_DIR}{os.sep}" in dups[0]["dst"] and dups[0]["approve"] is False
    assert "invoice.pdf" in dups[0]["reason"]


def test_organize_only_loose_top_level_files(tmp_path, tree):
    plan = org.make_plan([str(tree)], organize=True)
    org_moves = {Path(a["src"]).name: a["dst"] for a in plan["actions"] if a["kind"] == "organize"}
    assert "invoice copy.pdf" not in org_moves  # in a subfolder: left alone (and it is a duplicate anyway)
    month = time.strftime("%Y-%m", time.localtime(time.time() - 86400 * 30))
    assert org_moves["invoice.pdf"] == str(tree / "Documents" / month / "invoice.pdf")
    assert Path(org_moves["photo.jpg"]).parts[-3] == "Images"


def test_refuses_system_folders_and_whole_drives(tmp_path, monkeypatch):
    monkeypatch.setattr(org, "PROTECTED_ROOTS", [str(tmp_path / "Windows")])
    (tmp_path / "Windows" / "System32").mkdir(parents=True)
    for bad in (tmp_path / "Windows", tmp_path / "Windows" / "System32", Path(tmp_path.anchor), tmp_path / "nope"):
        with pytest.raises(ValueError):
            org.make_plan([str(bad)])


def test_dry_run_then_approved_apply_and_rollback(tmp_path, tree):
    p = plan_file(tmp_path, [tree], organize=True)
    logs = []
    r = org.apply_plan(p, None, dry_run=True, log=logs.append)
    assert r["moved"] == 0 and r["would_move"] == len(load(p)["actions"])  # previews the whole plan
    assert org.apply_plan(p, "1", dry_run=True, log=logs.append)["would_move"] == 1
    assert (tree / "photo.jpg").exists()
    assert org.apply_plan(p, None, dry_run=False, log=logs.append)["moved"] == 0  # nothing approved: no moves

    snapshot = {str(f.relative_to(tree)): f.read_bytes() for f in tree.rglob("*") if f.is_file()}
    r = org.apply_plan(p, "all", dry_run=False, log=logs.append)
    assert r["moved"] == len(load(p)["actions"]) and not r["skipped"]
    assert not (tree / "photo.jpg").exists() and (tree / "Accounts" / "2026").is_dir()
    dup_dir = tree / org.DUP_DIR
    assert [f.name for f in dup_dir.rglob("*.pdf")] == ["invoice copy.pdf"]
    # Every file still exists somewhere: nothing deleted
    assert sorted(f.read_bytes() for f in tree.rglob("*") if f.is_file()) == sorted(snapshot.values())
    # Applying again does nothing (already done)
    assert org.apply_plan(p, "all", dry_run=False, log=logs.append)["moved"] == 0

    r = org.rollback(p, log=logs.append)
    assert r["restored"] == len(load(p)["actions"]) and not r["skipped"]
    assert {str(f.relative_to(tree)): f.read_bytes() for f in tree.rglob("*") if f.is_file()} == snapshot
    assert not dup_dir.exists() and not (tree / "Images").exists()  # folders it created are removed again
    assert org.rollback(p, log=logs.append)["restored"] == 0  # idempotent


def test_selective_approval_and_plan_flags(tmp_path, tree):
    p = plan_file(tmp_path, [tree], organize=True)
    plan = load(p)
    first, second = plan["actions"][0], plan["actions"][1]
    assert org.apply_plan(p, str(first["id"]), dry_run=False, log=lambda *_: None)["moved"] == 1
    assert not Path(first["src"]).exists() and Path(second["src"]).exists()
    plan["actions"][1]["approve"] = True  # approving by editing the plan file also works
    Path(p).write_text(json.dumps(plan))
    assert org.apply_plan(p, None, dry_run=False, log=lambda *_: None)["moved"] == 1
    with pytest.raises(ValueError):
        org.parse_selection("1,999", 3)
    assert org.parse_selection("1,3-4", 5) == {1, 3, 4}


def test_changed_missing_and_occupied_files_are_skipped(tmp_path, tree):
    p = plan_file(tmp_path, [tree], organize=True)
    acts = {Path(a["src"]).name: a for a in load(p)["actions"]}
    write(tree / "notes.txt", "edited after planning")  # changed
    (tree / "photo.jpg").unlink()  # missing
    dst = Path(acts["invoice.pdf"]["dst"])
    write(dst, "already here")  # destination taken: renamed, never overwritten
    r = org.apply_plan(p, "all", dry_run=False, log=lambda *_: None)
    reasons = {Path(acts_name).name: why for acts_name, why in
               ((next(a["src"] for a in load(p)["actions"] if a["id"] == i), why) for i, why in r["skipped"])}
    assert reasons["notes.txt"] == "changed since the plan was made"
    assert reasons["photo.jpg"] == "file no longer there"
    assert dst.read_text() == "already here" and (dst.parent / "invoice (2).pdf").exists()

    # After a move, if the original place is reused or the moved file is edited, rollback leaves it alone
    write(tree / "invoice.pdf", "new file with the old name")
    r = org.rollback(p, log=lambda *_: None)
    assert any("original location" in why for _, why in r["skipped"])
    assert (tree / "invoice.pdf").read_text() == "new file with the old name"


def test_locked_file_is_skipped_not_fatal(tmp_path, tree, monkeypatch):
    p = plan_file(tmp_path, [tree], organize=True)
    real = org._move

    def flaky(src, dst, sha):
        if src.endswith("photo.jpg"):
            raise PermissionError(13, "The process cannot access the file")
        return real(src, dst, sha)

    monkeypatch.setattr(org, "_move", flaky)
    r = org.apply_plan(p, "all", dry_run=False, log=lambda *_: None)
    assert r["moved"] == len(load(p)["actions"]) - 1
    assert len(r["skipped"]) == 1 and "locked" in r["skipped"][0][1]
    assert (tree / "photo.jpg").exists()


def test_crash_between_move_and_journal_is_recoverable(tmp_path, tree):
    p = plan_file(tmp_path, [tree])
    a = load(p)["actions"][0]
    sha = org.sha256_file(a["src"])
    journal = org.Journal(p + ".journal.jsonl")
    journal.write({"event": "intent", "id": a["id"], "src": a["src"], "dst": a["dst"], "sha256": sha,
                   "created_dirs": []})
    os.makedirs(os.path.dirname(a["dst"]))
    os.rename(a["src"], a["dst"])  # the move happened, then "power cut" before the done entry
    with open(journal.path, "a") as f:
        f.write('{"event": "do')  # torn line
    assert org.rollback(p, log=lambda *_: None)["restored"] == 1
    assert Path(a["src"]).exists()


def test_verify_backup(tmp_path, tree):
    backup = tmp_path / "Backup"
    for f in tree.rglob("*"):
        if f.is_file() and "AppData" not in f.relative_to(tree).parts and not f.name.startswith("~$"):
            write(backup / f.relative_to(tree), f.read_bytes())
    r = org.verify_backup(str(tree), str(backup))
    assert r["status"] == "verified" and r["identical"] == r["files"] == 8
    write(backup / "notes.txt", "bit rot")
    (backup / "photo.jpg").unlink()
    r = org.verify_backup(str(tree), str(backup))
    assert r["status"] == "not verified" and r["different"] == ["notes.txt"] and r["missing"] == ["photo.jpg"]
    empty = tmp_path / "Empty"
    empty.mkdir()
    assert org.verify_backup(str(empty), str(backup))["status"] == "not verified"  # nothing checked is not "verified"


def test_cli_and_preview(tmp_path, tree, capsys):
    out = tmp_path / "p.json"
    assert org.main(["plan", str(tree), "--organize", "-o", str(out)]) == 0
    assert "Nothing was changed" in capsys.readouterr().out
    assert org.main(["preview", str(out)]) == 0
    page = (tmp_path / "p.html").read_text(encoding="utf-8")
    assert "dry run" in page and "<script" not in page
    write(tree / "<img src=x onerror=alert(1)>.txt" if os.name != "nt" else tree / "a&b.txt", "x")
    assert org.main(["apply", str(out)]) == 0 and (tree / "photo.jpg").exists()
    assert "Dry run" in capsys.readouterr().out
    assert org.main(["plan", str(tmp_path / "missing")]) == 2


def test_no_network_code():
    src = Path(org.__file__).read_text(encoding="utf-8")
    for word in ("urllib", "socket", "http.client", "requests", "smtplib"):
        assert f"import {word}" not in src
