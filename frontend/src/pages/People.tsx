import { useEffect, useState, type FormEvent } from "react";
import { CalendarCheck, CheckCircle2, Plus, Wrench } from "lucide-react";
import { api, type Page } from "../api";
import { useAuth } from "../auth";
import { today } from "../components/trade";
import { Badge, Empty, ErrorBanner, Field, Modal, PageHeader, Spinner, useAsync } from "../components/ui";
import { StatusBadge, TicketDetail } from "./Service";

type Employee = { id: number; name: string; employee_code: string | null; user_id: number | null; user_email: string | null; phone: string | null; email: string | null; job_role: string | null; department: string | null; joining_date: string | null; status: string; is_technician: boolean; notes: string | null };
type Member = { user_id: number; email: string; full_name: string };
type Task = { id: number; title: string; description: string | null; assigned_to: number | null; assignee_name: string | null; priority: string; due_date: string | null; status: string; overdue: boolean };

const ATT = [["present", "Present"], ["half_day", "Half day"], ["absent", "Absent"], ["leave", "Leave"], ["holiday", "Holiday"], ["week_off", "Week off"]];
const PRIO: Record<string, "slate" | "amber" | "red"> = { low: "slate", normal: "slate", high: "amber", urgent: "red" };

function EmployeeForm({ initial, onDone }: { initial: Partial<Employee>; onDone: () => void }) {
  const { can } = useAuth();
  const members = useAsync(() => can("users.manage") ? api<Member[]>("/organization/members") : Promise.resolve([]), []);
  const [f, setF] = useState<any>({ status: "active", is_technician: false, ...initial });
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const keys = ["name", "employee_code", "user_id", "phone", "email", "job_role", "department", "joining_date", "status", "is_technician", "notes"];
    const body: any = Object.fromEntries(keys.map((k) => [k, f[k] === "" || f[k] === undefined ? null : f[k]]));
    body.user_id = body.user_id ? Number(body.user_id) : null;
    try { await api(f.id ? `/employees/${f.id}` : "/employees", { method: f.id ? "PUT" : "POST", json: body }); onDone(); } catch (err: any) { setError(err.message); }
  }
  const input = (k: string, label: string, props: any = {}) => <Field label={label}><input className="input" value={f[k] ?? ""} onChange={set(k)} {...props} /></Field>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        {input("name", "Name *", { required: true })}{input("employee_code", "Employee code")}
        {input("job_role", "Job role", { placeholder: "e.g. CCTV technician" })}{input("department", "Department")}
        {input("phone", "Phone")}{input("email", "Email", { type: "email" })}
        {input("joining_date", "Joining date", { type: "date" })}
        <Field label="Status"><select className="input" value={f.status} onChange={set("status")}><option value="active">Active</option><option value="inactive">Inactive</option><option value="left">Left</option></select></Field>
        {!!members.data?.length && <Field label="Linked NetCare login" className="sm:col-span-2"><select className="input" value={f.user_id ?? ""} onChange={set("user_id")}>
          <option value="">— no login —</option>{members.data.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name} ({m.email})</option>)}</select></Field>}
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.is_technician} onChange={set("is_technician")} /> Technician (can be assigned service tickets)</label>
      <p className="text-xs text-slate-500">Link a login so this person sees their own jobs and tasks under My work. NetCare records attendance and leave but does not run payroll.</p>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Save</button></div>
    </form>
  );
}

function AttendanceDay() {
  const { can } = useAuth();
  const [day, setDay] = useState(today());
  const emps = useAsync(() => api<Page<Employee>>("/employees?size=200"), []);
  const rows = useAsync(() => api<any[]>(`/attendance?date_from=${day}`), [day]);
  const [draft, setDraft] = useState<Record<number, any>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!rows.data) return;
    setDraft(Object.fromEntries(rows.data.map((r) => [r.employee_id, { status: r.status, check_in: r.check_in ?? "", check_out: r.check_out ?? "" }])));
  }, [rows.data]);
  async function save() {
    setErr(null); setMsg(null);
    const entries = Object.entries(draft).filter(([, v]) => v.status).map(([id, v]) => ({ employee_id: Number(id), status: v.status, check_in: v.check_in || null, check_out: v.check_out || null }));
    if (!entries.length) return setErr("Mark at least one employee");
    try { await api("/attendance", { method: "PUT", json: { work_date: day, entries } }); setMsg("Saved."); rows.reload(); } catch (e: any) { setErr(e.message); }
  }
  const edit = can("attendance.manage");
  return (
    <div className="card">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label="Date"><input className="input" type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        {edit && <button className="btn-ghost" onClick={() => setDraft(Object.fromEntries((emps.data?.items ?? []).map((e) => [e.id, { ...(draft[e.id] ?? {}), status: draft[e.id]?.status || "present" }])))}>Mark everyone present</button>}
        {edit && <button className="btn-primary" onClick={save}><CalendarCheck size={15} /> Save attendance</button>}
        {msg && <span className="text-sm text-emerald-600">{msg}</span>}
      </div>
      <ErrorBanner message={err || emps.error} />
      {!emps.data ? <Spinner /> : !emps.data.items.length ? <Empty title="No active employees" /> : (
        <table className="w-full text-sm"><tbody>{emps.data.items.map((e) => {
          const v = draft[e.id] ?? { status: "", check_in: "", check_out: "" };
          const upd = (patch: any) => setDraft({ ...draft, [e.id]: { ...v, ...patch } });
          return (
            <tr key={e.id} className="border-t border-slate-100 dark:border-slate-800">
              <td className="td">{e.name}<div className="text-xs text-slate-500">{e.job_role}</div></td>
              <td className="p-1"><select className="input" disabled={!edit} value={v.status} onChange={(x) => upd({ status: x.target.value })} aria-label={`Attendance for ${e.name}`}>
                <option value="">— not recorded —</option>{ATT.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
              <td className="p-1"><input className="input" type="time" disabled={!edit} value={v.check_in} onChange={(x) => upd({ check_in: x.target.value })} aria-label="Check in" /></td>
              <td className="p-1"><input className="input" type="time" disabled={!edit} value={v.check_out} onChange={(x) => upd({ check_out: x.target.value })} aria-label="Check out" /></td>
            </tr>);
        })}</tbody></table>
      )}
    </div>
  );
}

function Leave() {
  const { can } = useAuth();
  const { data, error, reload } = useAsync(() => api<any[]>("/leave-requests"), []);
  const me = useAsync(() => api<Employee | null>("/employees/me"), []);
  const [f, setF] = useState({ start_date: today(), end_date: today(), leave_type: "casual", reason: "" });
  const [err, setErr] = useState<string | null>(null);
  async function request(e: FormEvent) {
    e.preventDefault();
    try { await api("/leave-requests", { method: "POST", json: { ...f, reason: f.reason || null } }); reload(); } catch (x: any) { setErr(x.message); }
  }
  async function decide(id: number, decision: string) {
    try { await api(`/leave-requests/${id}/decide`, { method: "POST", json: { decision } }); reload(); } catch (x: any) { setErr(x.message); }
  }
  return (
    <div className="space-y-4">
      <ErrorBanner message={error || err} />
      {me.data && <form onSubmit={request} className="card grid gap-2 sm:grid-cols-5">
        <Field label="From"><input className="input" type="date" required value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></Field>
        <Field label="To"><input className="input" type="date" required value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></Field>
        <Field label="Type"><select className="input" value={f.leave_type} onChange={(e) => setF({ ...f, leave_type: e.target.value })}>{["casual", "sick", "earned", "unpaid", "other"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Reason"><input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
        <div className="flex items-end"><button className="btn-primary w-full justify-center">Request leave</button></div>
      </form>}
      <div className="card !p-0 overflow-x-auto">
        {!data ? <Spinner /> : !data.length ? <Empty title="No leave requests" /> : (
          <table className="w-full min-w-[560px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Employee</th><th className="th">Dates</th><th className="th">Type</th><th className="th">Reason</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody>{data.map((l) => (
              <tr key={l.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{l.employee_name}</td><td className="td">{l.start_date} to {l.end_date} ({l.days}d)</td><td className="td">{l.leave_type}</td><td className="td">{l.reason}</td>
                <td className="td"><Badge tone={l.status === "approved" ? "green" : l.status === "pending" ? "amber" : "slate"}>{l.status}</Badge></td>
                <td className="td whitespace-nowrap text-right">{l.status === "pending" && can("attendance.manage") && <>
                  <button className="btn-ghost !py-1 text-xs" onClick={() => decide(l.id, "approved")}>Approve</button>
                  <button className="btn-ghost !py-1 text-xs text-red-600" onClick={() => decide(l.id, "rejected")}>Reject</button></>}</td>
              </tr>))}</tbody></table>
        )}
      </div>
    </div>
  );
}

export function Employees() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"staff" | "attendance" | "leave">("staff");
  const [status, setStatus] = useState("active");
  const [editing, setEditing] = useState<Partial<Employee> | null>(null);
  const { data, error, reload } = useAsync(() => api<Page<Employee>>(`/employees?size=200&status=${status}`), [status]);
  const tabs: [typeof tab, string][] = [["staff", "Employees"], ...(can("employees.view") ? [["attendance", "Attendance"]] as [typeof tab, string][] : []), ["leave", "Leave"]];
  return (
    <>
      <PageHeader title="Employees" subtitle="Staff records, attendance and leave (not payroll)"
        actions={tab === "staff" && can("employees.manage") && <button className="btn-primary" onClick={() => setEditing({})}><Plus size={16} /> Add employee</button>} />
      <div className="mb-3 flex gap-1">{tabs.map(([k, l]) => <button key={k} className={`btn ${tab === k ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"}`} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === "attendance" ? <AttendanceDay /> : tab === "leave" ? <Leave /> : <>
        <ErrorBanner message={error} />
        <div className="card !p-0">
          <div className="border-b border-slate-200 p-3 dark:border-slate-800"><select className="input !w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="active">Active</option><option value="inactive">Inactive</option><option value="left">Left</option></select></div>
          {!data ? <Spinner /> : !data.items.length ? <Empty title="No employees" hint="Add your staff to assign service jobs and tasks." /> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[640px]"><thead className="bg-slate-50 dark:bg-slate-800/50"><tr><th className="th">Name</th><th className="th">Role</th><th className="th">Phone</th><th className="th">Login</th><th className="th">Joined</th></tr></thead>
              <tbody>{data.items.map((e) => (
                <tr key={e.id} className={`border-t border-slate-100 dark:border-slate-800 ${can("employees.manage") ? "cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40" : ""}`} onClick={() => can("employees.manage") && setEditing(e)}>
                  <td className="td font-medium">{e.name} {e.is_technician && <Badge tone="indigo">technician</Badge>}<div className="text-xs font-normal text-slate-500">{e.employee_code}</div></td>
                  <td className="td">{e.job_role}<div className="text-xs text-slate-500">{e.department}</div></td><td className="td">{e.phone}</td>
                  <td className="td text-xs">{e.user_email ?? <span className="text-slate-400">none</span>}</td><td className="td">{e.joining_date ?? "—"}</td>
                </tr>))}</tbody></table></div>
          )}
        </div>
      </>}
      {editing && <Modal title={editing.id ? "Edit employee" : "Add employee"} wide onClose={() => setEditing(null)}><EmployeeForm initial={editing} onDone={() => { setEditing(null); reload(); }} /></Modal>}
    </>
  );
}

function TaskForm({ onDone }: { onDone: () => void }) {
  const emps = useAsync(() => api<Page<Employee>>("/employees?size=200"), []);
  const [f, setF] = useState({ title: "", description: "", assigned_to: "", priority: "normal", due_date: "" });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try { await api("/tasks", { method: "POST", json: { ...f, description: f.description || null, assigned_to: f.assigned_to ? Number(f.assigned_to) : null, due_date: f.due_date || null } }); onDone(); }
    catch (err: any) { setError(err.message); }
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBanner message={error} />
      <Field label="Task *"><input className="input" required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. Follow up AMC renewal with St. Mary's" /></Field>
      <Field label="Details"><textarea className="input" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Assign to"><select className="input" value={f.assigned_to} onChange={(e) => setF({ ...f, assigned_to: e.target.value })}><option value="">—</option>{emps.data?.items.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label="Priority"><select className="input" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{["low", "normal", "high", "urgent"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Due"><input className="input" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
      </div>
      <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onDone}>Cancel</button><button className="btn-primary">Create task</button></div>
    </form>
  );
}

function TaskList({ tasks, onChange }: { tasks: Task[]; onChange: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  async function set(t: Task, status: string) {
    try { await api(`/tasks/${t.id}/status`, { method: "POST", json: { status } }); onChange(); } catch (e: any) { setErr(e.message); }
  }
  if (!tasks.length) return <Empty title="No tasks" />;
  return (
    <>
      <ErrorBanner message={err} />
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">{tasks.map((t) => (
        <li key={t.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
          <button className={`rounded-full border p-0.5 ${t.status === "done" ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-300 text-transparent hover:text-slate-400"}`} onClick={() => set(t, t.status === "done" ? "todo" : "done")} aria-label={t.status === "done" ? "Mark not done" : "Mark done"}><CheckCircle2 size={16} /></button>
          <div className="min-w-0 flex-1">
            <div className={`text-sm ${t.status === "done" ? "text-slate-400 line-through" : "font-medium"}`}>{t.title}</div>
            <div className="text-xs text-slate-500">{t.assignee_name ?? "Unassigned"}{t.due_date ? ` · due ${t.due_date}` : ""}{t.description ? ` · ${t.description}` : ""}</div>
          </div>
          {t.overdue && <Badge tone="red">overdue</Badge>}{t.priority !== "normal" && <Badge tone={PRIO[t.priority]}>{t.priority}</Badge>}
          {t.status === "todo" && <button className="text-xs text-indigo-600 hover:underline" onClick={() => set(t, "in_progress")}>start</button>}
          {t.status === "in_progress" && <Badge tone="amber">in progress</Badge>}
        </li>))}</ul>
    </>
  );
}

export function Tasks() {
  const { can } = useAuth();
  const [filter, setFilter] = useState("open");
  const [adding, setAdding] = useState(false);
  const { data, error, reload } = useAsync(() => api<Page<Task>>(`/tasks?size=200${filter === "mine" ? "&mine=true&status=open" : filter ? `&status=${filter}` : ""}`), [filter]);
  return (
    <>
      <PageHeader title="Tasks" subtitle="Follow-ups and to-dos for your team" actions={can("tasks.edit") && <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> New task</button>} />
      <ErrorBanner message={error} />
      <div className="card !p-0">
        <div className="border-b border-slate-200 p-3 dark:border-slate-800"><select className="input !w-auto" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
          <option value="open">Open</option><option value="mine">My open tasks</option><option value="done">Done</option><option value="">All</option></select></div>
        {!data ? <Spinner /> : <TaskList tasks={data.items} onChange={reload} />}
      </div>
      {adding && <Modal title="New task" onClose={() => setAdding(false)}><TaskForm onDone={() => { setAdding(false); reload(); }} /></Modal>}
    </>
  );
}

export function MyWork() {
  const { data, error, reload } = useAsync(() => api<any>("/my-work"), []);
  const [open, setOpen] = useState<number | null>(null);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;
  if (!data.employee) return (
    <><PageHeader title="My work" /><div className="card"><Empty title="Your login isn't linked to an employee record" hint="Ask the owner to link your login under Employees. Then your jobs and tasks appear here." /></div></>
  );
  const visits = new Set<number>(data.visits_today);
  return (
    <>
      <PageHeader title={`My work: ${data.employee.name}`} subtitle={`${data.tickets.length} open job(s), ${data.tasks.length} open task(s), ${data.completed_this_month} completed this month`} />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="card !p-0">
          <h3 className="flex items-center gap-2 border-b border-slate-200 p-3 font-medium dark:border-slate-800"><Wrench size={16} /> My jobs</h3>
          {!data.tickets.length ? <Empty title="No open jobs" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">{data.tickets.map((t: any) => (
              <li key={t.id} className="cursor-pointer px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => setOpen(t.id)}>
                <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs">{t.number}</span><StatusBadge s={t.status} />{visits.has(t.id) && <Badge tone="indigo">visit today</Badge>}{t.priority !== "normal" && <Badge tone={PRIO[t.priority]}>{t.priority}</Badge>}</div>
                <div className="text-sm font-medium">{t.customer_name}{t.contact_phone ? ` · ${t.contact_phone}` : ""}</div>
                <div className="text-xs text-slate-500">{t.asset_name ?? t.equipment ?? ""} · {t.reported_problem}</div>
                {t.scheduled_visit && <div className="text-xs text-slate-500">Visit: {new Date(t.scheduled_visit).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</div>}
              </li>))}</ul>
          )}
        </div>
        <div className="card !p-0">
          <h3 className="border-b border-slate-200 p-3 font-medium dark:border-slate-800">My tasks</h3>
          <TaskList tasks={data.tasks} onChange={reload} />
        </div>
      </div>
      {open && <Modal title="Job" wide onClose={() => { setOpen(null); reload(); }}><TicketDetail id={open} onChanged={reload} /></Modal>}
    </>
  );
}
