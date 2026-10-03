"""Role -> permission mapping. Enforced server-side via deps.require()."""

ROLES = ["owner", "manager", "accountant", "salesperson", "inventory_manager", "technician",
         "receptionist", "viewer"]

ALL = {
    "org.manage", "users.manage", "audit.view",
    "customers.view", "customers.edit",
    "products.view", "products.edit",
    "inventory.view", "inventory.adjust",
    "locations.manage", "dashboard.view",
    "suppliers.view", "suppliers.edit",
    "purchases.view", "purchases.edit", "purchases.approve",
    "sales.view", "sales.edit",
    "payments.view", "payments.edit",
    "expenses.view", "expenses.edit", "finance.view", "finance.manage", "reports.view",
    "service.view", "service.edit", "service.work", "assets.view", "assets.edit",
    "employees.view", "employees.manage", "attendance.manage", "tasks.view", "tasks.edit",
    "documents.view", "documents.edit", "documents.sensitive", "documents.purge", "analytics.view",
}

# service.edit: create, assign, cancel, close and bill any ticket.
# service.work: update tickets assigned to *your own* employee record (enforced in the service router).
# documents.*: a document is also visible only if the caller can view the record it is attached to.
# documents.sensitive (ID proofs, contracts) and documents.purge (permanent removal) stay with owner/manager.
EXTRA = {
    "accountant": {"service.view", "assets.view", "employees.view", "documents.view", "documents.edit",
                   "analytics.view"},
    "salesperson": {"service.view", "assets.view", "tasks.view", "documents.view", "documents.edit"},
    "inventory_manager": {"service.view", "assets.view", "tasks.view", "documents.view", "documents.edit"},
    "technician": {"service.view", "service.work", "assets.view", "tasks.view", "documents.view",
                   "documents.edit"},
    "receptionist": {"service.view", "service.edit", "assets.view", "assets.edit", "tasks.view",
                     "documents.view", "documents.edit"},
    "viewer": {"service.view", "assets.view", "tasks.view", "documents.view"},
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(ALL),
    "manager": ALL - {"org.manage", "documents.purge"},
    "accountant": {"customers.view", "products.view", "inventory.view", "dashboard.view", "audit.view",
                   "suppliers.view", "purchases.view", "sales.view", "payments.view", "payments.edit",
                   "expenses.view", "expenses.edit", "finance.view", "finance.manage", "reports.view"},
    "salesperson": {"customers.view", "customers.edit", "products.view", "inventory.view", "dashboard.view",
                    "sales.view", "sales.edit", "payments.view", "payments.edit"},
    "inventory_manager": {"products.view", "products.edit", "inventory.view", "inventory.adjust",
                          "locations.manage", "dashboard.view", "suppliers.view", "suppliers.edit",
                          "purchases.view", "purchases.edit"},
    "technician": {"customers.view", "products.view", "inventory.view", "dashboard.view"},
    "receptionist": {"customers.view", "customers.edit", "products.view", "dashboard.view", "sales.view"},
    "viewer": {"customers.view", "products.view", "inventory.view", "dashboard.view", "suppliers.view",
               "purchases.view", "sales.view", "payments.view"},
}


for _role, _perms in EXTRA.items():
    ROLE_PERMISSIONS[_role] |= _perms


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, set())
