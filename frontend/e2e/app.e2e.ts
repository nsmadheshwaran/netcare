import { expect, test, type Page } from "@playwright/test";

const password = "e2e-password-123";

async function register(page: Page, business: string) {
  const email = `owner.${Date.now()}.${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Business name").fill(business);
  await page.getByLabel("Your name").fill("Pilot Owner");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password (min 10 characters)").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  return email;
}

test("a new business registers and sees the Get started checklist", async ({ page }) => {
  await register(page, "E2E Computers");
  await expect(page.getByText("Get started")).toBeVisible();
  await expect(page.getByText("Complete your business details")).toBeVisible();
});

test("add a customer and find it in the list", async ({ page }) => {
  await register(page, "E2E Customers Shop");
  await page.getByRole("link", { name: "Customers" }).click();
  await page.getByRole("button", { name: "Add customer" }).click();
  const dialog = page.getByRole("dialog", { name: "Add customer" });
  await dialog.getByLabel("Name *", { exact: true }).fill("Govt Higher Secondary School");
  await dialog.getByLabel("Phone").fill("9840012345");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
  await page.getByPlaceholder("Search name, phone, email, GSTIN…").fill("Higher Secondary");
  await expect(page.getByRole("cell", { name: "Govt Higher Secondary School" })).toBeVisible();
});

test("an expired sign-in is renewed silently, and sign out / sign in works", async ({ page }) => {
  const email = await register(page, "E2E Sessions");
  await page.evaluate(() => localStorage.setItem("netcare.token", "expired.access.token"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible(); // refreshed, not sent to login
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill("nobody@example.com");
  await page.getByLabel("Password", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid email or password");
});

test("forgot password explains what to do when email is not set up", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page.getByText("Email is not set up on this NetCare server")).toBeVisible();
});

test("switching a module off removes it from the menu", async ({ page }) => {
  await register(page, "E2E Modules");
  await expect(page.getByRole("link", { name: "Service Management" })).toBeVisible();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  // click(), not uncheck(): the switch shows what the server saved, so it flips once the save returns.
  const service = page.getByRole("checkbox", { name: "Service", exact: true });
  await service.click();
  await expect(service).not.toBeChecked();
  await expect(page.getByRole("link", { name: "Service Management" })).toBeHidden();
  await expect(page.getByRole("link", { name: "IT Assets" })).toBeHidden();
  await service.click();
  await expect(service).toBeChecked();
  await expect(page.getByRole("link", { name: "Service Management" })).toBeVisible();
});
