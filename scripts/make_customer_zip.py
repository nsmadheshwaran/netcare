"""Builds release/NetCare-<version>.zip for a customer from the committed files (HEAD).

Run from the repository root:  python scripts/make_customer_zip.py
Files marked export-ignore in .gitattributes (tests, CI, seller-only docs) are left out; START_HERE.md
replaces the developer README. The zip uses forward-slash paths so it unpacks correctly everywhere.
"""
import io
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> None:
    if git("status", "--porcelain", "--untracked-files=no").strip():
        sys.exit("Uncommitted changes to tracked files: commit them first, so the zip matches a commit.")
    version = re.search(r'version="([\d.]+)"', (ROOT / "backend/app/main.py").read_text(encoding="utf-8")).group(1)
    commit = git("rev-parse", "--short", "HEAD").decode().strip()
    archive = tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD")))
    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"NetCare-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for m in archive.getmembers():
            if not m.isfile() or m.name in ("README.md", "install/START_HERE.md"):
                continue
            z.writestr(f"NetCare/{m.name}", archive.extractfile(m).read())
        z.writestr("NetCare/START_HERE.md", (ROOT / "install/START_HERE.md").read_bytes())
        z.writestr("NetCare/VERSION.txt", f"NetCare {version} (commit {commit})\n")
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB), version {version}, commit {commit}")


if __name__ == "__main__":
    main()
