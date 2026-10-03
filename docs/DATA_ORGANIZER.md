# Smart Data Organizer

A local command-line tool, [`organizer/netcare_organizer.py`](../organizer/netcare_organizer.py), using only the
Python standard library. It has no network code (a test checks this), and the NetCare server never sees file
names or contents.

## Design rules (enforced)
| Rule | How |
|---|---|
| Runs locally; contents never leave the PC | No network imports. Plans, previews and journals are files next to where you run it. |
| Only folders the user selects | Only the folders named on the command line are read. `C:\Windows`, Program Files and ProgramData are refused, and so are whole drives. Folders named Windows, Program Files, ProgramData, AppData, `$Recycle.Bin`, System Volume Information, `.git`, `node_modules` or `_NetCare_Duplicates` are skipped wherever they appear below a chosen folder. Links, junctions and cloud placeholders are not followed. System and hidden files and Office lock files (`~$`) are ignored. |
| Duplicates by SHA-256 after grouping by size | Size first, then a hash of the first 64 KB, then the full SHA-256. Empty files are never treated as duplicates. Of each group it keeps the copy nearest the top of its folder tree, then the oldest. |
| Dry run by default; every change approved | `plan` and `preview` change nothing. `apply` without `--approve` is a dry run of the whole plan. Moves happen only for actions approved with `--approve all` or `--approve 1,4,7-12`, or marked `"approve": true` in the plan file. |
| Nothing deleted automatically | Duplicates are *moved* to `_NetCare_Duplicates\<hash>\` inside the chosen folder. An existing file at a destination is never overwritten (the new one gets " (2)"). Moves across drives copy, verify the SHA-256, then remove the original. |
| Every operation logged; rollback replays in reverse | `plan.json.journal.jsonl` records an *intent* before each move and *done* after it, fsynced. `rollback` restores newest first and removes the folders it created if they are empty. A move interrupted between the two entries is still recognised. Rollback skips (and reports) files that were edited after the move or whose original location is taken. Running it twice is harmless. |
| Locked or missing files skipped, run continues | Unreadable folders, locked files, files changed since the plan (size, time or content) and missing files are listed with the reason. |
| Backup "verified" only after real verification | `verify-backup` compares every file with the same path in the backup by SHA-256. It says `verified` only if every file was read and has an identical copy; otherwise it lists missing, different and unreadable files and exits with code 1. An empty source is not "verified". |

## Use
```bat
python netcare_organizer.py plan "D:\Shared" "C:\Users\Reception\Downloads" --organize -o plan.json
python netcare_organizer.py preview plan.json
python netcare_organizer.py apply plan.json
python netcare_organizer.py apply plan.json --approve all
python netcare_organizer.py rollback plan.json
python netcare_organizer.py verify-backup "D:\Shared" "E:\Backup\Shared"
```
`--organize` also proposes moving loose files at the top of each chosen folder into
`Documents|Images|Videos|Audio|Archives|Installers|Disk images|Other\YYYY-MM` by last-modified month. Files in
subfolders are left where they are.

Keep `plan.json` and its `.journal.jsonl` until you are sure you will not need to undo.
