import { expect, test } from "@playwright/test";

import { createAccount, expectNoHorizontalScroll, fixtures, mockApi, signIn } from "./support";

test("analyse a sample scenario", async ({ page }) => {
  const calls = await mockApi(page);
  await signIn(page, await createAccount(), "/scenario");

  await page.getByRole("button", { name: "Bank fraud call" }).click();
  await page.getByRole("button", { name: "Analyse" }).click();

  await expect(page.getByRole("heading", { name: "Verdict" })).toBeVisible();
  const first = fixtures.scenario.identified_offenses[0];
  await expect(page.getByRole("heading", { name: `${first.section_number}, ${first.act_name}` })).toBeVisible();
  expect(calls.find((c) => c.key === "POST /api/v1/analyze")?.auth).toMatch(/^Bearer /);

  // The result survives a reload in this tab.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Verdict" })).toBeVisible();
});

test("a too-short description can't be sent", async ({ page }) => {
  await mockApi(page);
  await signIn(page, await createAccount(), "/scenario");
  await page.getByLabel("What happened").fill("A theft.");
  await expect(page.getByRole("button", { name: "Analyse" })).toBeDisabled();
  await expect(page.getByText(/Add a little more detail/)).toBeVisible();
});

test("the home page and scenario fit a phone screen @mobile", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await signIn(page, await createAccount(), "/scenario");
  await expectNoHorizontalScroll(page);
});
