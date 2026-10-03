"""NetCare Smart Data Organizer: local, dry-run-first file tidying with a journal and rollback.

Everything runs on this PC. No file names or contents are sent anywhere; there is no network code in this file.
Standard library only (Python 3.10+).

    python netcare_organizer.py plan D:\\Shared C:\\Users\\me\\Downloads --organize -o plan.json
    python netcare_organizer.py preview plan.json            -> plan.html to review in a browser
    python netcare_organizer.py apply plan.json              -> dry run: shows what would happen
    python netcare_organizer.py apply plan.json --approve all   (or --approve 1,4,7-12)
    python netcare_organizer.py rollback plan.json           -> puts approved moves back, newest first
    python netcare_organizer.py verify-backup D:\\Shared E:\\Backup\\Shared

Rules: only folders you name are read; system and program folders are excluded; nothing is ever deleted
(duplicates are moved to a "_NetCare_Duplicates" folder for you to review); every move is journaled so it can
be undone; files that are locked, missing or changed since the plan are skipped and reported.
"""
import argparse
import hashlib
import html
import json
import os
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
DUP_DIR = "_NetCare_Duplicates"
CHUNK = 1 << 20
# Folder names never entered, wherever they appear.
EXCLUDED_NAMES = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin",
                  "system volume information", "recovery", "$windows.~bt", "$windows.~ws", ".git", "node_modules",
                  "__pycache__", DUP_DIR.lower()}
# Roots that are refused outright.
PROTECTED_ROOTS = [p for p in (os.environ.get("SystemRoot"), os.environ.get("ProgramFiles"),
                               os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramData")) if p]
CATEGORIES = {
    "Documents": {"pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv", "ppt", "pptx", "odp"},
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "tif", "tiff", "svg", "raw", "cr2", "nef"},
    "Videos": {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "3gp", "dav"},
    "Audio": {"mp3", "wav", "aac", "flac", "m4a", "ogg", "wma"},
    "Archives": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"},
    "Installers": {"exe", "msi", "msix", "appx"},
    "Disk images": {"iso", "img", "vhd", "vhdx"},
}
FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_REPARSE_POINT = 0x2, 0x4, 0x400


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        remaining = limit
        while True:
            chunk = f.read(CHUNK if remaining is None else min(CHUNK, remaining))
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
                if remaining <= 0:
                    break
    return h.hexdigest()


def category_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return next((c for c, exts in CATEGORIES.items() if ext in exts), "Other")


def check_root(root: str) -> Path:
    p = Path(root).resolve()
    if not p.is_dir():
        raise ValueError(f"not a folder: {root}")
    for prot in PROTECTED_ROOTS:
        pr = Path(prot).resolve()
        if p == pr or pr in p.parents:
            raise ValueError(f"refusing system/program folder: {p}")
    if p == Path(p.anchor):
        raise ValueError(f"refusing a whole drive ({p}); choose specific folders")
    return p


# ---------------- scan ----------------
@dataclass
class FileInfo:
    path: str
    root: str
    size: int
    mtime: float


def _skip_entry(entry: os.DirEntry) -> str | None:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError as e:
        return f"cannot read: {e.strerror or e}"
    if entry.is_symlink():
        return "link (not followed)"
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return "junction or cloud placeholder (not followed)"
    if attrs & FILE_ATTRIBUTE_SYSTEM:
        return "system file"
    return None


def scan(roots: list[str]) -> tuple[list[FileInfo], list[dict]]:
    files, skipped = [], []
    seen_roots = set()
    for r in roots:
        root = check_root(r)
        if any(root == s or s in root.parents for s in seen_roots):
            continue  # nested inside a root already scanned
        seen_roots.add(root)
        stack = [str(root)]
        while stack:
            d = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError as e:
                skipped.append({"path": d, "reason": f"cannot open folder: {e.strerror or e}"})
                continue
            for e in entries:
                why = _skip_entry(e)
                if why:
                    if why not in ("system file",):
                        skipped.append({"path": e.path, "reason": why})
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name.lower() not in EXCLUDED_NAMES:
                        stack.append(e.path)
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat(follow_symlinks=False)
                if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_HIDDEN or e.name.startswith("~$"):
                    continue  # hidden files and Office lock files
                files.append(FileInfo(e.path, str(root), st.st_size, st.st_mtime))
    return files, skipped


def find_duplicates(files: list[FileInfo], skipped: list[dict]) -> list[tuple[str, list[FileInfo]]]:
    """Group by size, then by a hash of the first 64 KB, then by full SHA-256. Empty files are ignored."""
    by_size = defaultdict(list)
    for f in files:
        if f.size > 0:
            by_size[f.size].append(f)
    groups = []
    for same_size in (g for g in by_size.values() if len(g) > 1):
        by_head = defaultdict(list)
        for f in same_size:
            try:
                by_head[sha256_file(f.path, 65536)].append(f)
            except OSError as e:
                skipped.append({"path": f.path, "reason": f"cannot read (locked?): {e.strerror or e}"})
        for cands in (g for g in by_head.values() if len(g) > 1):
            by_full = defaultdict(list)
            for f in cands:
                try:
                    by_full[sha256_file(f.path)].append(f)
                except OSError as e:
                    skipped.append({"path": f.path, "reason": f"cannot read (locked?): {e.strerror or e}"})
            groups += [(h, g) for h, g in by_full.items() if len(g) > 1]
    return groups


# ---------------- plan ----------------
def make_plan(roots: list[str], organize: bool = False) -> dict:
    files, skipped = scan(roots)
    actions, taken = [], set()

    def add(kind, f: FileInfo, dst: str, reason: str, sha: str | None = None):
        actions.append({"id": len(actions) + 1, "kind": kind, "root": f.root, "src": f.path, "dst": dst, "size": f.size,
                        "mtime": f.mtime, "sha256": sha, "reason": reason, "approve": False})
        taken.add(f.path)

    for sha, group in find_duplicates(files, skipped):
        # Keep the copy nearest the top of its folder tree, then the oldest, then by name.
        keep, *extra = sorted(group, key=lambda f: (len(Path(f.path).relative_to(f.root).parts), f.mtime, f.path))
        for f in extra:
            dst = os.path.join(f.root, DUP_DIR, sha[:12], os.path.basename(f.path))
            add("duplicate", f, dst, f"Same content as {keep.path}", sha)

    if organize:
        for f in files:
            if f.path in taken or os.path.dirname(f.path) != f.root:
                continue  # only loose files at the top of a chosen folder
            month = datetime.fromtimestamp(f.mtime).strftime("%Y-%m")
            cat = category_of(f.path)
            add("organize", f, os.path.join(f.root, cat, month, os.path.basename(f.path)),
                f"{cat}, last changed {month}")

    return {"tool": "netcare-organizer", "version": VERSION, "created_at": now_iso(),
            "roots": [str(check_root(r)) for r in roots], "organize": organize, "actions": actions,
            "skipped": skipped,
            "summary": {"files_scanned": len(files), "duplicates": sum(a["kind"] == "duplicate" for a in actions),
                        "duplicate_bytes": sum(a["size"] for a in actions if a["kind"] == "duplicate"),
                        "organize": sum(a["kind"] == "organize" for a in actions), "skipped": len(skipped)}}


def preview_html(plan: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{a['id']}</td><td>{e(a['kind'])}</td><td>{e(a['src'])}</td><td>{e(a['dst'])}</td>"
        f"<td style='text-align:right'>{a['size']:,}</td><td>{e(a['reason'])}</td></tr>" for a in plan["actions"])
    skipped = "".join(f"<li>{e(s['path'])}: {e(s['reason'])}</li>" for s in plan["skipped"])
    s = plan["summary"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>NetCare organizer plan</title>
<style>body{{font:14px system-ui;margin:24px;color:#0f172a}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #e2e8f0;padding:4px 6px;text-align:left;vertical-align:top;word-break:break-all}}
th{{background:#f1f5f9}}.note{{background:#fef3c7;padding:8px;border-radius:6px}}</style></head><body>
<h1>Organizer plan (dry run)</h1>
<p class="note">Nothing has been changed. Nothing will ever be deleted: duplicates are moved to a
<b>{DUP_DIR}</b> folder for you to check. Approve with <code>apply plan.json --approve all</code> or by number.</p>
<p>Folders: {e(", ".join(plan["roots"]))}<br>Files scanned: {s["files_scanned"]:,} · duplicate copies:
{s["duplicates"]:,} ({s["duplicate_bytes"] / 1e6:,.1f} MB) · files to organise: {s["organize"]:,} · skipped:
{s["skipped"]:,}</p>
<table><tr><th>#</th><th>Type</th><th>From</th><th>To</th><th>Bytes</th><th>Why</th></tr>{rows}</table>
<h2>Skipped</h2><ul>{skipped or "<li>None</li>"}</ul></body></html>"""


# ---------------- apply / rollback ----------------
def parse_selection(sel: str | None, n: int) -> set[int]:
    if not sel:
        return set()
    if sel.strip().lower() == "all":
        return set(range(1, n + 1))
    out = set()
    for part in sel.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out |= set(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    bad = [i for i in out if not 1 <= i <= n]
    if bad:
        raise ValueError(f"no such action number(s): {sorted(bad)}")
    return out


class Journal:
    """Append-only JSON lines, flushed and fsynced per entry, next to the plan."""

    def __init__(self, path: str):
        self.path = path

    def write(self, entry: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**entry, "at": now_iso()}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass  # torn last line after a crash
        return out


def _unique(dst: str) -> str:
    if not os.path.exists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    i = 2
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def _move(src: str, dst: str, sha: str) -> None:
    """Rename when possible; across drives copy, verify the hash, then remove the source."""
    try:
        os.rename(src, dst)  # never overwrites on Windows; dst was checked free on POSIX
        return
    except OSError as e:
        if getattr(e, "winerror", None) != 17 and e.errno != 18:  # not "different drive"
            raise
    shutil.copy2(src, dst)
    if sha256_file(dst) != sha:
        os.remove(dst)
        raise OSError("copy verification failed")
    os.remove(src)


def _created_dirs(dst: str, root: str) -> list[str]:
    created, d = [], os.path.dirname(dst)
    while not os.path.exists(d) and d.startswith(root + os.sep):
        created.append(d)
        d = os.path.dirname(d)
    return created


def apply_plan(plan_path: str, approve: str | None = None, dry_run: bool = True, log=print) -> dict:
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    chosen = parse_selection(approve, len(plan["actions"])) | {a["id"] for a in plan["actions"] if a.get("approve")}
    if dry_run and not chosen:  # a plain dry run previews the whole plan
        chosen = {a["id"] for a in plan["actions"]}
    journal = Journal(plan_path + ".journal.jsonl")
    done_before = {j["id"] for j in journal.read() if j["event"] == "done"}
    result = {"moved": 0, "skipped": [], "would_move": 0}
    for a in plan["actions"]:
        if a["id"] not in chosen or a["id"] in done_before:
            continue
        src = a["src"]
        try:
            st = os.stat(src)
        except FileNotFoundError:
            result["skipped"].append((a["id"], "file no longer there"))
            continue
        except OSError as e:
            result["skipped"].append((a["id"], f"cannot read: {e.strerror or e}"))
            continue
        if st.st_size != a["size"] or abs(st.st_mtime - a["mtime"]) > 2:
            result["skipped"].append((a["id"], "changed since the plan was made"))
            continue
        if dry_run:
            log(f"[dry run] #{a['id']} {src} -> {a['dst']}")
            result["would_move"] += 1
            continue
        try:
            sha = sha256_file(src)
            if a["sha256"] and sha != a["sha256"]:
                result["skipped"].append((a["id"], "content changed since the plan was made"))
                continue
            dst = _unique(a["dst"])
            created = _created_dirs(dst, a["root"])
            journal.write({"event": "intent", "id": a["id"], "src": src, "dst": dst, "sha256": sha,
                           "created_dirs": created})
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _move(src, dst, sha)
            journal.write({"event": "done", "id": a["id"], "src": src, "dst": dst, "sha256": sha,
                           "created_dirs": created})
            result["moved"] += 1
            log(f"#{a['id']} moved {src} -> {dst}")
        except OSError as e:
            result["skipped"].append((a["id"], f"could not move (locked or no permission?): {e.strerror or e}"))
    for i, why in result["skipped"]:
        log(f"#{i} skipped: {why}")
    return result


def rollback(plan_path: str, log=print) -> dict:
    journal = Journal(plan_path + ".journal.jsonl")
    entries = journal.read()
    rolled = {j["id"] for j in entries if j["event"] == "rolled_back"}
    done = {j["id"]: j for j in entries if j["event"] == "done"}
    # An intent without "done" (crash mid-move) counts if the file reached its destination intact.
    for j in entries:
        if j["event"] == "intent" and j["id"] not in done and os.path.exists(j["dst"]) and not os.path.exists(j["src"]):
            done[j["id"]] = j
    result = {"restored": 0, "skipped": []}
    order = [j["id"] for j in entries if j["event"] in ("intent", "done")]
    for i in sorted(done, key=lambda k: order.index(k), reverse=True):
        j = done[i]
        if i in rolled:
            continue
        if not os.path.exists(j["dst"]):
            result["skipped"].append((i, "file is no longer where it was moved"))
            continue
        if os.path.exists(j["src"]):
            result["skipped"].append((i, "something else is now at the original location"))
            continue
        try:
            if sha256_file(j["dst"]) != j["sha256"]:
                result["skipped"].append((i, "file was edited after the move; left in place"))
                continue
            os.makedirs(os.path.dirname(j["src"]), exist_ok=True)
            _move(j["dst"], j["src"], j["sha256"])
        except OSError as e:
            result["skipped"].append((i, f"could not move back: {e.strerror or e}"))
            continue
        for d in j.get("created_dirs", []):  # innermost first
            try:
                os.rmdir(d)  # only if empty
            except OSError:
                pass
        journal.write({"event": "rolled_back", "id": i})
        result["restored"] += 1
        log(f"#{i} restored {j['src']}")
    for i, why in result["skipped"]:
        log(f"#{i} not restored: {why}")
    return result


# ---------------- backup verification ----------------
def verify_backup(source: str, backup: str) -> dict:
    """Compare every file under source with the same relative path under backup, by SHA-256.
    'verified' is only reported when every readable source file has an identical copy."""
    src_root, bak_root = check_root(source), Path(backup).resolve()
    if not bak_root.is_dir():
        raise ValueError(f"backup folder not found: {backup}")
    files, skipped = scan([str(src_root)])
    missing, different, ok = [], [], 0
    for f in files:
        rel = os.path.relpath(f.path, src_root)
        b = bak_root / rel
        if not b.is_file():
            missing.append(rel)
            continue
        try:
            same = b.stat().st_size == f.size and sha256_file(str(b)) == sha256_file(f.path)
        except OSError as e:
            skipped.append({"path": f.path, "reason": f"cannot read: {e.strerror or e}"})
            continue
        if same:
            ok += 1
        else:
            different.append(rel)
    status = "verified" if files and not missing and not different and not skipped else "not verified"
    return {"status": status, "checked_at": now_iso(), "files": len(files), "identical": ok, "missing": missing,
            "different": different, "unreadable": skipped}


# ---------------- CLI ----------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="netcare_organizer", description="Local, dry-run-first file organizer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="scan folders and write a plan (changes nothing)")
    p.add_argument("folders", nargs="+")
    p.add_argument("--organize", action="store_true", help="also sort loose top-level files into Type\\YYYY-MM")
    p.add_argument("-o", "--output", default="plan.json")
    p = sub.add_parser("preview", help="write an HTML page of the plan")
    p.add_argument("plan")
    p = sub.add_parser("apply", help="dry run, or carry out approved actions")
    p.add_argument("plan")
    p.add_argument("--approve", help='"all" or numbers like 1,4,7-12 (without it: dry run)')
    p = sub.add_parser("rollback", help="undo applied moves, newest first")
    p.add_argument("plan")
    p = sub.add_parser("verify-backup", help="compare a folder with its backup by SHA-256")
    p.add_argument("source")
    p.add_argument("backup")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "plan":
            plan = make_plan(args.folders, args.organize)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=1)
            s = plan["summary"]
            print(f"Scanned {s['files_scanned']} files: {s['duplicates']} duplicate copies "
                  f"({s['duplicate_bytes'] / 1e6:.1f} MB), {s['organize']} to organise, {s['skipped']} skipped.")
            print(f"Plan written to {args.output}. Nothing was changed.")
        elif args.cmd == "preview":
            out = os.path.splitext(args.plan)[0] + ".html"
            with open(args.plan, encoding="utf-8") as f, open(out, "w", encoding="utf-8") as o:
                o.write(preview_html(json.load(f)))
            print(f"Preview written to {out}")
        elif args.cmd == "apply":
            r = apply_plan(args.plan, args.approve, dry_run=not args.approve)
            if args.approve:
                print(f"Moved {r['moved']}, skipped {len(r['skipped'])}. Undo with: rollback {args.plan}")
            else:
                print(f"Dry run: {r['would_move']} would move. Nothing was changed. Add --approve to carry out.")
        elif args.cmd == "rollback":
            r = rollback(args.plan)
            print(f"Restored {r['restored']}, could not restore {len(r['skipped'])}.")
        elif args.cmd == "verify-backup":
            r = verify_backup(args.source, args.backup)
            print(json.dumps(r, indent=1))
            return 0 if r["status"] == "verified" else 1
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
