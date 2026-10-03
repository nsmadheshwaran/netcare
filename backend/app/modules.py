"""Optional modules a business can switch off (Settings → Modules).

A switched-off module removes its permissions from every role in that business. Every endpoint is already
guarded by a permission, so the API refuses (403) and the UI hides the module without any extra checks.
Core features (customers, products, stock, dashboard, users, reports on core data) cannot be switched off.
"""
from .permissions import ROLE_PERMISSIONS

MODULES: dict[str, dict] = {
    "trade": {"label": "Buying and selling", "detail": "Suppliers, purchases, quotations, invoices, payments",
              "prefixes": ("suppliers.", "purchases.", "sales.", "payments.")},
    "finance": {"label": "Finance", "detail": "Expenses, money accounts, tax rates, analytics",
                "prefixes": ("expenses.", "finance.", "analytics."), "requires": "trade"},
    "service": {"label": "Service", "detail": "Service jobs, customer equipment, CCTV, maintenance",
                "prefixes": ("service.", "assets.")},
    "people": {"label": "People", "detail": "Employees, attendance, leave, tasks",
               "prefixes": ("employees.", "attendance.", "tasks.")},
    "documents": {"label": "Documents", "detail": "Document library and attachments", "prefixes": ("documents.",)},
    "monitoring": {"label": "Network monitoring", "detail": "Agents, ping and port checks, uptime",
                   "prefixes": ("monitoring.",)},
    "security": {"label": "Endpoint security", "detail": "Microsoft Defender status of PCs",
                 "prefixes": ("security.",), "requires": "monitoring"},
}

# Reports that belong to a module (others are core).
REPORT_MODULE = {
    "sales-register": "trade", "purchase-register": "trade", "receivables-ageing": "trade",
    "payables-ageing": "trade", "gst-summary": "trade", "expenses": "finance", "profit-loss": "finance",
    "cash-flow": "finance", "daily-closing": "finance", "service-performance": "service",
    "warranty-expiry": "service", "maintenance-due": "service", "task-completion": "people",
    "attendance": "people", "documents-expiring": "documents", "uptime": "monitoring",
    "endpoint-security": "security",
}


def enabled(org) -> set[str]:
    return set(MODULES) if org.enabled_modules is None else set(org.enabled_modules) & set(MODULES)


def disabled_permissions(org) -> set[str]:
    off = set(MODULES) - enabled(org)
    return {p for p in set().union(*ROLE_PERMISSIONS.values())
            if any(p.startswith(pre) for m in off for pre in MODULES[m]["prefixes"])}


def effective_permissions(role: str, org) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set()) - disabled_permissions(org)


def validate(selection: list[str]) -> list[str]:
    unknown = set(selection) - set(MODULES)
    if unknown:
        raise ValueError(f"Unknown module(s): {', '.join(sorted(unknown))}")
    for m in selection:
        req = MODULES[m].get("requires")
        if req and req not in selection:
            raise ValueError(f"{MODULES[m]['label']} needs {MODULES[req]['label']} switched on")
    return sorted(set(selection))
