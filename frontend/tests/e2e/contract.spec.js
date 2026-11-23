import { expect, test } from "@playwright/test";

import { createAccount, expectNoHorizontalScroll, fixtures, mockApi, signIn } from "./support";

const SAMPLE = new URL("../../../backend/samples/01_employment_loaded.pdf", import.meta.url).pathname;
const id = fixtures.review.contract_id;

test("upload a contract and work through its review", async ({ page }) => {
  const calls = await mockApi(page);
  await signIn(page, await createAccount(), "/contracts");

  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await page.getByRole("combobox", { name: "What kind of contract is it?" }).click();
  await page.getByRole("option", { name: "Employment agreement" }).click();
  // The side follows the type, weaker side first.
  await expect(page.getByRole("combobox", { name: "Which side are you on?" })).toHaveText("Employee");
  await page.getByRole("button", { name: "Review contract" }).click();

  await expect(page).toHaveURL(new RegExp(`/contracts/${id}$`));
  await expect(page.getByText("Critical risks")).toBeVisible();
  expect(calls.filter((c) => c.key.startsWith("POST /api/v1/contracts")).every((c) => c.auth?.startsWith("Bearer "))).toBe(true);

  // Red flags, then the passage in the document.
  await page.getByRole("button", { name: /^Red flags/ }).click();
  const first = fixtures.review.findings.toSorted((a, b) =>
    ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].indexOf(a.severity) - ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].indexOf(b.severity),
  )[0];
  await expect(page.getByRole("heading", { name: first.title })).toBeVisible();
  await page.getByRole("button", { name: "Show in the document" }).first().click();
  await expect(page).toHaveURL(/section=document/);
  await expect(page.locator('mark[aria-pressed="true"]')).toBeVisible();
  await expect(page.locator("mark")).toHaveCount(fixtures.review.findings.length);

  // Ask the contract.
  await page.getByRole("button", { name: "Ask the contract" }).click();
  await page.getByLabel("Your question").fill("What is my notice period?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText(fixtures.answer.answer.slice(0, 40))).toBeVisible();
  await page.keyboard.press("Escape");

  // The PDF downloads with the token attached.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Report (PDF)" }).click();
  expect((await download).suggestedFilename()).toBe(`contract-review-${id}.pdf`);

  // A reload keeps the review: it lives at its own address.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Document" })).toBeVisible();
});

test("deleting a review asks first, then removes it", async ({ page }) => {
  const calls = await mockApi(page);
  await signIn(page, await createAccount(), `/contracts/${id}`);
  await page.getByRole("button", { name: "Delete this review" }).click();
  await page.getByRole("button", { name: "Keep it" }).click();
  expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);

  await page.getByRole("button", { name: "Delete this review" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/reviews$/);
  expect(calls.some((c) => c.key === `DELETE /api/v1/contracts/${id}`)).toBe(true);
});

test("my reviews lists the account's reviews", async ({ page }) => {
  await mockApi(page);
  await signIn(page, await createAccount(), "/reviews");
  for (const item of fixtures.list.items) {
    await expect(page.getByRole("link", { name: item.filename }).first()).toBeVisible();
  }
});

test("a review that isn't yours, or no longer exists, says so plainly", async ({ page }) => {
  await mockApi(page);
  await signIn(page, await createAccount(), "/contracts/someone-elses");
  await expect(page.getByRole("heading", { name: "We can't find that review" })).toBeVisible();
});

for (const [status, detail] of [
  [413, "File exceeds the 15 MB limit."],
  [422, "Could not read 'scan.pdf': the file is password-protected."],
  [429, "Contract uploads are limited to 6 per minute. Please try again shortly."],
]) {
  test(`an upload refused with ${status} shows the server's reason`, async ({ page }) => {
    await mockApi(page, {
      "^POST /api/v1/contracts$": (route) => route.fulfill({ status, json: { detail } }),
    });
    await signIn(page, await createAccount(), "/contracts");
    await page.locator('input[type="file"]').setInputFiles(SAMPLE);
    await page.getByRole("button", { name: "Review contract" }).click();
    await expect(page.getByRole("alert").filter({ hasText: detail })).toBeVisible();
  });
}

test("an unreachable server is reported, not left spinning", async ({ page }) => {
  await mockApi(page, { "^POST /api/v1/contracts$": (route) => route.abort("connectionrefused") });
  await signIn(page, await createAccount(), "/contracts");
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await page.getByRole("button", { name: "Review contract" }).click();
  await expect(page.getByText("Can't reach the WhatLawSays server")).toBeVisible();
});

test("the review fits a phone screen @mobile", async ({ page }) => {
  await mockApi(page);
  await signIn(page, await createAccount(), `/contracts/${id}`);
  await expect(page.getByText("Critical risks")).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto(`/contracts/${id}?section=document`);
  await page.locator("mark").first().click();
  await expect(page.getByRole("dialog", { name: "Note on the selected passage" })).toBeVisible();
  await expectNoHorizontalScroll(page);
});
