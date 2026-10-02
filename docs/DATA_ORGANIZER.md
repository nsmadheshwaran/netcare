# Smart Data Organizer

> **Status: not implemented.** Planned for Phase 8. This page records the design rules the implementation
> must follow.

## Design rules
- Runs **locally** on the user's Windows PC. File contents never leave the machine or go to any AI or cloud
  service.
- Analyzes only folders the user explicitly selects. System and program folders (`C:\Windows`,
  `Program Files`, `AppData`) are excluded by default.
- Finds duplicates using SHA-256 hashes, after first grouping files by size.
- **Dry run by default.** Every planned move or rename is previewed and must be approved. Nothing is ever
  deleted automatically.
- Logs every operation, and rollback replays the log in reverse where the files still exist.
- Locked, missing or inaccessible files are reported and skipped without failing the whole run.
- Backup status is shown as "verified" only after an actual verification (hash comparison or restore test).
