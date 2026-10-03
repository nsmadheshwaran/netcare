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
}

# service.edit: create, assign, cancel, close and bill any ticket.
# service.work: update tickets assigned to *your own* employee record (enforced in the service router).
EXTRA = {
    "accountant": {"service.view", "assets.view", "employees.view"},
    "salesperson": {"service.view", "assets.view", "tasks.view"},
    "inventory_manager": {"service.view", "assets.view", "tasks.view"},
    "technician": {"service.view", "service.work", "assets.view", "tasks.view"},
    "receptionist": {"service.view", "service.edit", "assets.view", "assets.edit", "tasks.view"},
    "viewer": {"service.view", "assets.view", "tasks.view"},
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(ALL),
    "manager": ALL - {"org.manage"},
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
