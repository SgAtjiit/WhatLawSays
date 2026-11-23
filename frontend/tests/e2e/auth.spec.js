import { expect, test } from "@playwright/test";

import { confirmEmail, createAccount, mockApi, signIn } from "./support";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("the tools ask you to sign in, then take you where you were going", async ({ page }) => {
  await page.goto("/contracts");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fcontracts/);

  const account = await createAccount();
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  await expect(page).toHaveURL(/\/contracts$/);
  await expect(page.getByRole("heading", { name: "Review a contract before you sign" })).toBeVisible();
});

test("a wrong password is explained without saying whether the account exists", async ({ page }) => {
  const account = await createAccount();
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("That email and password don't match.")).toBeVisible();
});

test("a new email account must confirm its address before using the tools", async ({ page }) => {
  const email = `new-${Date.now()}@example.com`;
  await page.goto("/sign-up?next=%2Fscenario");
  await page.getByLabel("Your name").fill("Asha Rao");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-1");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();

  // Not confirmed yet: the tools stay out of reach.
  await page.getByRole("button", { name: "I've confirmed my email" }).click();
  await expect(page.getByText("Not confirmed yet.")).toBeVisible();
  await page.goto("/scenario");
  await expect(page).toHaveURL(/verify-email/);

  await confirmEmail(email);
  await page.getByRole("button", { name: "I've confirmed my email" }).click();
  await expect(page).toHaveURL(/\/scenario$/);
  await expect(page.getByRole("navigation", { name: "Main" }).first()).toBeVisible();
});

test("signing out leaves nothing of the account behind", async ({ page }) => {
  const account = await createAccount();
  await signIn(page, account, "/scenario");
  await page.getByRole("button", { name: /Account/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
  await page.goto("/reviews");
  await expect(page).toHaveURL(/sign-in/);
});

test("a password reset never reveals whether an email is registered", async ({ page }) => {
  await page.goto("/reset-password");
  await page.getByLabel("Email").fill(`nobody-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists for/)).toBeVisible();
});
