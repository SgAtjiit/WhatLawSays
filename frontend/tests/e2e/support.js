import { readFileSync } from "node:fs";
import { expect } from "@playwright/test";

const EMULATOR = "http://127.0.0.1:9099";
const PROJECT = "demo-whatlawsays";
const fixture = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url)));

export const fixtures = {
  review: fixture("contract-review"),
  document: fixture("contract-document"),
  answer: fixture("contract-answer"),
  list: fixture("contract-list"),
  supported: fixture("supported"),
  scenario: fixture("scenario-analysis"),
};

async function emulator(path, body) {
  const response = await fetch(`${EMULATOR}${path}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  return response.json();
}

/** An account in the Auth emulator, with its email already confirmed unless asked not to. */
export async function createAccount({ verified = true } = {}) {
  const email = `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
  const password = "correct-horse-1";
  const { idToken } = await emulator("/identitytoolkit.googleapis.com/v1/accounts:signUp?key=e2e", {
    email,
    password,
    returnSecureToken: true,
  });
  if (verified) {
    await emulator("/identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=e2e", {
      requestType: "VERIFY_EMAIL",
      idToken,
    });
    await confirmEmail(email);
  }
  return { email, password };
}

export async function confirmEmail(email) {
  const { oobCodes } = await emulator(`/emulator/v1/projects/${PROJECT}/oobCodes`);
  const code = oobCodes.filter((c) => c.email === email && c.requestType === "VERIFY_EMAIL").at(-1);
  await fetch(code.oobLink);
}

export async function signIn(page, account, next = "/") {
  await page.goto(`/sign-in?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/sign-in/);
}

/**
 * Serve the API from recorded responses. Every request must carry a bearer
 * token, as the real backend demands; anything unexpected fails the test.
 */
export async function mockApi(page, overrides = {}) {
  const calls = [];
  await page.route("**/health", (route) => route.fulfill({ json: { status: "healthy" } }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    calls.push({ key, auth: request.headers().authorization });

    const custom = Object.entries(overrides).find(([pattern]) => new RegExp(pattern).test(key));
    if (custom) return custom[1](route, request);

    if (key === "GET /api/v1/contracts/meta/supported") return route.fulfill({ json: fixtures.supported });
    if (!request.headers().authorization?.startsWith("Bearer ")) {
      return route.fulfill({ status: 401, json: { detail: "Sign in to continue." } });
    }
    const id = fixtures.review.contract_id;
    const routes = {
      "POST /api/v1/contracts": () => ({ json: fixtures.review }),
      "GET /api/v1/contracts": () => ({ json: fixtures.list }),
      [`GET /api/v1/contracts/${id}`]: () => ({ json: fixtures.review }),
      [`GET /api/v1/contracts/${id}/document`]: () => ({ json: fixtures.document }),
      [`POST /api/v1/contracts/${id}/ask`]: () => ({ json: fixtures.answer }),
      [`DELETE /api/v1/contracts/${id}`]: () => ({ json: { contract_id: id, deleted: true } }),
      [`GET /api/v1/contracts/${id}/report.pdf`]: () => ({
        body: "%PDF-1.4\n%fake\n",
        contentType: "application/pdf",
      }),
      "POST /api/v1/analyze": () => ({ json: fixtures.scenario }),
    };
    const handler = routes[key];
    if (!handler) return route.fulfill({ status: 404, json: { detail: `No mock for ${key}` } });
    return route.fulfill(handler());
  });
  return calls;
}

/** Nothing on the page may be wider than the screen. */
export async function expectNoHorizontalScroll(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}
