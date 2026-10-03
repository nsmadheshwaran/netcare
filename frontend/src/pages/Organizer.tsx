import { FolderSearch, Lock, RotateCcw, ShieldCheck } from "lucide-react";
import { PageHeader } from "../components/ui";

const STEPS: [string, string, string][] = [
  ["1. Make a plan (changes nothing)", "Scans only the folders you name, finds duplicate files by content (SHA-256), and optionally sorts loose files into Type\\Year-Month folders.",
    "python netcare_organizer.py plan \"D:\\Shared\" \"C:\\Users\\Reception\\Downloads\" --organize -o plan.json"],
  ["2. Review it", "Opens a readable list of every proposed move and every file that was skipped, and why.",
    "python netcare_organizer.py preview plan.json"],
  ["3. Dry run", "Shows exactly what would happen, without changing anything.",
    "python netcare_organizer.py apply plan.json"],
  ["4. Approve", "Carries out all actions, or only the numbers you choose. Every move is written to a journal first.",
    "python netcare_organizer.py apply plan.json --approve 1,4,7-12"],
  ["5. Undo if needed", "Moves files back, newest first. Files edited or replaced since are left alone and reported.",
    "python netcare_organizer.py rollback plan.json"],
];

export default function Organizer() {
  return (
    <>
      <PageHeader title="Data organizer" subtitle="Tidy shared folders and find duplicate files safely, on the PC itself" />
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <div className="card !p-3 text-sm"><Lock size={16} className="mb-1 text-indigo-600" /><b>Stays on the PC.</b> The organizer runs locally. File names and contents are never sent to NetCare or any other service.</div>
        <div className="card !p-3 text-sm"><ShieldCheck size={16} className="mb-1 text-indigo-600" /><b>Never deletes.</b> Duplicates are moved to a <code>_NetCare_Duplicates</code> folder for you to check and remove yourself.</div>
        <div className="card !p-3 text-sm"><RotateCcw size={16} className="mb-1 text-indigo-600" /><b>Dry run first, undo any time.</b> Nothing changes until you approve, and every move can be reversed.</div>
      </div>
      <div className="card space-y-4">
        <h2 className="flex items-center gap-2 font-semibold"><FolderSearch size={18} /> How to use it</h2>
        <p className="text-sm text-slate-500">Copy <code>organizer/netcare_organizer.py</code> from the NetCare package to the PC (Python 3.10 or newer), open a command prompt in that folder, then:</p>
        {STEPS.map(([title, text, cmd]) => (
          <div key={title}>
            <div className="font-medium">{title}</div>
            <div className="text-sm text-slate-500">{text}</div>
            <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-100 p-2 text-xs dark:bg-slate-800">{cmd}</pre>
          </div>
        ))}
        <div>
          <div className="font-medium">Check a backup</div>
          <div className="text-sm text-slate-500">Compares every file with its copy in the backup, by content. It reports "verified" only if every file is present and identical; otherwise it lists what is missing or different.</div>
          <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-100 p-2 text-xs dark:bg-slate-800">python netcare_organizer.py verify-backup "D:\Shared" "E:\Backup\Shared"</pre>
        </div>
        <p className="text-xs text-slate-500">Windows, Program Files, ProgramData and AppData folders are refused or skipped, as are whole drives, links, system files and Office lock files. Locked or unreadable files are skipped and listed; the rest of the run continues.</p>
      </div>
    </>
  );
}
