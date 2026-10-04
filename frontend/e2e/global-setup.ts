// Prepares a throwaway backend database before the browser tests start (cross-platform: no shell syntax).
import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const BACKEND = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "backend");
export const DB_FILE = join(BACKEND, "e2e.db");
export const DB_URL = "sqlite:///./e2e.db";
export const PYTHON = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");

export default function globalSetup() {
  rmSync(DB_FILE, { force: true });
  execFileSync(PYTHON, ["-m", "alembic", "upgrade", "head"], {
    cwd: BACKEND,
    env: { ...process.env, NETCARE_DATABASE_URL: DB_URL },
    stdio: "inherit",
  });
}
