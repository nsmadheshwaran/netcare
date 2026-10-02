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
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(ALL),
    "manager": ALL - {"org.manage"},
    "accountant": {"customers.view", "products.view", "inventory.view", "dashboard.view", "audit.view",
                   "suppliers.view", "purchases.view", "sales.view", "payments.view", "payments.edit"},
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


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, set())
